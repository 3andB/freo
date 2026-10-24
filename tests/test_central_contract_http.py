"""Actual Client + Reporter over verified local HTTPS, with server-side receipts.

The published validators are optional for ordinary development, required in the
release acceptance command via FREO_API_CONTRACT_SOURCE. No external API writes.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest
from packaging.version import Version, InvalidVersion
from tests.test_central_api import app, central, iso, license_payload
from tests.test_central_contract import due
from app.extensions import db
from app.models import Station, CentralHourlyMetric
from app.services.central_api import Reporter, installation
from app.services.central_api.client import Client, CONTRACT_REVISION
from app.services.central_api.metrics import sample
from app.routes.central_api import queue_activation


@pytest.fixture
def mothership(tmp_path, monkeypatch):
    source=os.environ.get('FREO_API_CONTRACT_SOURCE')
    if not source:pytest.skip('Set FREO_API_CONTRACT_SOURCE to the verified 2026-10-v1.1 bundle')
    path=Path(source)/'validation.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='70de2051b2b0f8b29de02cbf18c2b65e6f8700b584c8ffffd1fb742168ebbe8b'
    spec=importlib.util.spec_from_file_location('contract_http_validation',path)
    validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)
    certificate,key=tmp_path/'cert.pem',tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=localhost',
                    '-addext','subjectAltName=DNS:localhost','-keyout',str(key),'-out',str(certificate)],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    state=SimpleNamespace(revision=CONTRACT_REVISION,identities={},machines={},stations={},metrics={},owners={},
                          calls=[],heartbeats=[],drop=set(),wrong_counts=False,reject=False,latest='0.3.2',rotate=False,
                          malformed=set(),fail={},health_auth=[])
    validators={'/v1/enroll':validation.Enrollment,'/v1/activate':validation.Activation,
                '/v1/stations/sync':validation.StationSync,'/v1/heartbeat':validation.Heartbeat}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):self.handle_request()
        def do_POST(self):self.handle_request()
        def reply(self,status,data,headers=None):
            raw=json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json')
            if state.revision:self.send_header('X-Freo-Contract-Revision',state.revision)
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def handle_request(self):
            path=self.path;state.calls.append(path)
            if path=='/health':
                state.health_auth.append(self.headers.get('Authorization'))
                return self.reply(200,{'status':'ok'})
            if path in state.fail:
                status,headers=state.fail[path]
                return self.reply(status,{'error':{'code':'fixture_failure'}},headers)
            token=self.headers.get('Authorization','')
            if not token.startswith('Bearer freo_') or state.reject:
                return self.reply(401,{'error':{'code':'unauthorized'}})
            credential=hashlib.sha256(token.encode()).hexdigest()
            identity=state.identities.get(credential)
            if path!='/v1/enroll' and identity is None:
                return self.reply(401,{'error':{'code':'unauthorized'}})
            payload=None
            if self.command=='POST':
                try:
                    payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    validators[path].model_validate_json(json.dumps(payload))
                    if state.revision!=CONTRACT_REVISION:
                        machine=payload.get('installation',{})
                        assert machine.get('install_type')!='freo-studio'
                        assert not {'deployment_label','lifecycle_state'} & machine.keys()
                        for station in payload.get('stations',[]):
                            assert not {'lifecycle_state','enabled','deleted_at'} & station.keys()
                            if path=='/v1/heartbeat':
                                assert station['on_air'] is not None
                                for metric in station['metrics']:
                                    assert 'observed_seconds' not in metric and all(v is not None for v in metric.values())
                except Exception:
                    return self.reply(400,{'error':{'code':'invalid_payload'}})
            status=200
            if path=='/v1/enroll':
                if identity is None:
                    identity=str(uuid4());state.identities[credential]=identity
                    state.machines[identity]=payload['installation'];status=201
                result=dict(installation_id=identity,token_type='Bearer',server_time=iso(time.time()),heartbeat_interval_seconds=3600)
            elif path=='/v1/license':
                result=license_payload(installation_id=identity,channel_limit=2,station_profile_id=state.owners.get(identity),
                                       registration_status='registered' if identity in state.owners else 'unregistered')
            elif path=='/v1/activate':
                profile=state.owners.setdefault(identity,str(uuid4()))
                result=dict(installation_id=identity,station_profile_id=profile,registration_status='registered',token_type='Bearer',
                            heartbeat_interval_seconds=3600,server_time=iso(time.time()),
                            license=license_payload(installation_id=identity,channel_limit=2,station_profile_id=profile,registration_status='registered'))
                if state.rotate:result['access_token']='freo_'+'r'*43
            elif path=='/v1/stations/sync':
                if any(state.stations.get(s['station_id'],{}).get('owner',identity)!=identity for s in payload['stations']):
                    return self.reply(409,{'error':{'code':'station_conflict'}})
                for station in payload['stations']:
                    old=state.stations.get(station['station_id'],{})
                    state.stations[station['station_id']]=dict(old,**station,owner=identity)
                result=dict(server_time=iso(time.time()),stations=[dict(station_id=s['station_id'],created_at=iso(time.time()),updated_at=iso(time.time())) for s in payload['stations']])
            elif path=='/v1/heartbeat':
                if any(state.stations.get(s['station_id'],{}).get('owner')!=identity for s in payload['stations']):
                    return self.reply(409,{'error':{'code':'station_not_synced'}})
                state.machines[identity]=payload['installation']
                state.heartbeats.append(payload)
                for station in payload['stations']:
                    for metric in station['metrics']:state.metrics[(station['station_id'],metric['period_start'])]=metric
                installed=payload['installation']['freo_version'];latest=state.latest
                try:status_name='CURRENT' if Version(installed)==Version(latest) else 'AHEAD' if Version(installed)>Version(latest) else 'UPDATE_AVAILABLE'
                except (InvalidVersion,TypeError):status_name='UNKNOWN'
                result=dict(server_time=iso(time.time()),next_heartbeat_seconds=3600,stations_accepted=len(payload['stations']),
                    metrics_accepted=sum(len(s['metrics']) for s in payload['stations'])+int(state.wrong_counts),
                    installed_version=installed,latest_version=latest,version_status=status_name,
                    update_available=None if status_name=='UNKNOWN' else status_name=='UPDATE_AVAILABLE')
            else:return self.reply(404,{'error':{'code':'unknown_path'}})
            if path in state.drop:
                state.drop.remove(path);self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            if path in state.malformed:
                state.malformed.remove(path);self.send_response(200);self.end_headers();self.wfile.write(b'not json');return
            return self.reply(status,result)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certificate,key)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    original=ssl.create_default_context
    monkeypatch.setattr('app.services.central_api.client.ssl.create_default_context',lambda:original(cafile=certificate))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    state.url='https://localhost:'+str(server.server_port)
    try:yield state
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def actual_reporter(central,mothership):
    from flask import current_app
    current_app.config['FREO_API_URL']=mothership.url
    row=installation();row.registration_state='unconfigured';db.session.commit()
    return Reporter(Client)


def test_https_lost_enroll_and_activation_responses_preserve_identity(central,mothership):
    reporter=actual_reporter(central,mothership)
    mothership.drop.add('/v1/enroll');reporter.tick()
    pending=reporter.store.read();assert set(pending)=={'enrollment_token'}
    assert len(mothership.identities)==1
    installation().state=dict(installation().state,enrollment={'due':0});db.session.commit()
    reporter=Reporter(Client);reporter.tick()
    credentials=reporter.store.read()
    assert credentials['access_token']==pending['enrollment_token']
    assert credentials['installation_id']==next(iter(mothership.identities.values()))
    queue_activation('FREO-7K4P-M9Q2');mothership.drop.add('/v1/activate');reporter.tick()
    assert 'activation' in installation().state
    owner=mothership.owners[credentials['installation_id']]
    installation().state=dict(installation().state,claim={'due':0});db.session.commit()
    Reporter(Client).tick()
    assert installation().state['owner_profile_id']==owner and 'activation' not in installation().state
    assert reporter.store.read()==credentials and len(mothership.identities)==1
    assert all(value is None for value in mothership.health_auth)
    assert '/v1/register' not in mothership.calls


def test_https_wrong_receipt_and_lost_heartbeat_replace_existing_hour(central,mothership):
    reporter=actual_reporter(central,mothership)
    hour=int(time.time()//3600)*3600
    sample(hour-120);sample(hour-60)
    mothership.wrong_counts=True;reporter.tick()
    assert not db.session.get(CentralHourlyMetric,(1,hour-3600)).sent
    accepted=dict(mothership.metrics);assert len(accepted)==2
    mothership.wrong_counts=False;mothership.drop.add('/v1/heartbeat');due();Reporter(Client).tick()
    assert not db.session.get(CentralHourlyMetric,(1,hour-3600)).sent
    assert mothership.metrics==accepted
    due();Reporter(Client).tick()
    assert db.session.get(CentralHourlyMetric,(1,hour-3600)).sent
    assert mothership.metrics==accepted
    assert installation().state['last_heartbeat']['metrics_accepted']==2


def test_https_rejects_foreign_uuid_atomically_and_preserves_credential(central,mothership):
    reporter=actual_reporter(central,mothership)
    station=db.session.get(Station,1)
    mothership.stations[station.freo_station_id]={'owner':str(uuid4())}
    reporter.tick();saved=reporter.store.read()
    assert len(mothership.stations)==1
    assert installation().last_error=='report:station_conflict'
    assert not any(s.synced_digest for s in __import__('app.models',fromlist=['CentralStationState']).CentralStationState.query)
    assert reporter.store.read()==saved and len(mothership.identities)==1


@pytest.mark.parametrize('latest,status', [('0.3.2','AHEAD'),('1.0.0','UPDATE_AVAILABLE'),('1.0.0-rc.11','CURRENT'),(None,'UNKNOWN')])
def test_https_version_statuses_use_real_response_parser(central,mothership,monkeypatch,latest,status):
    monkeypatch.setattr('app.services.central_api.metrics.VERSION','1.0.0-rc.11')
    reporter=actual_reporter(central,mothership);mothership.latest=latest
    reporter.tick();receipt=installation().state['last_heartbeat']
    assert receipt['version_status']==status
    assert receipt['update_available'] is (None if status=='UNKNOWN' else status=='UPDATE_AVAILABLE')


def test_https_outage_rate_limit_malformed_and_401_keep_local_rights(central,mothership):
    from app.services.stations import create_station
    from app.services.central_api.licensing import check_expansion
    reporter=actual_reporter(central,mothership);reporter.tick()
    credentials=reporter.store.read();cache=installation().license_cache['entitlement']
    assert cache['channel_limit']==2
    create_station('Third local station','third-local');assert Station.query.filter_by(enabled=True).count()==3
    mothership.fail['/v1/license']=(429,{'Retry-After':'7200'});due();Reporter(Client).tick()
    assert installation().state['retry_after']>time.time()+7100
    before=len(mothership.calls);Reporter(Client).tick();assert len(mothership.calls)==before
    row=installation();row.state=dict(row.state,retry_after=0);db.session.commit();mothership.fail.clear()
    mothership.malformed.add('/v1/license');due();Reporter(Client).tick()
    assert row.license_cache['entitlement']==cache
    mothership.fail['/v1/license']=(503,{});due();Reporter(Client).tick()
    assert row.license_cache['entitlement']==cache
    mothership.fail.clear();mothership.reject=True;due();Reporter(Client).tick()
    assert row.registration_state=='credentials_rejected' and reporter.store.read()==credentials
    assert all(s.enabled for s in Station.query) and len(mothership.identities)==1
    with pytest.raises(ValueError,match='three stations'):check_expansion()


def test_https_activation_cannot_replace_bearer(central,mothership):
    reporter=actual_reporter(central,mothership);reporter.tick();credentials=reporter.store.read()
    mothership.rotate=True;queue_activation('FREO-7K4P-M9Q2');reporter.tick()
    assert reporter.store.read()==credentials
    assert installation().last_error=='claim:invalid_activation_response'
    assert 'owner_profile_id' not in installation().state or installation().state['owner_profile_id'] is None


def test_https_twenty_channels_five_hours_and_sequential_catchup(central,mothership):
    reporter=actual_reporter(central,mothership)
    for number in range(3,22):db.session.add(Station(name=f'Batch channel {number}',slug=f'batch-{number}'))
    db.session.commit();hour=int(time.time()//3600)*3600
    for station in Station.query:
        for offset in range(1,7):
            db.session.add(CentralHourlyMetric(station_id=station.id,period_start=hour-offset*3600,
                observed_seconds=60,listener_seconds=120,peak_listeners=2,sent=False,
                snapshot=dict(current_listeners=2,songs_in_library=0,artists=0,albums=0,
                    library_duration_seconds=0,library_storage_bytes=0,stream_running=True,scheduler_running=False)))
    db.session.commit();reporter.tick()
    assert [len(p['stations']) for p in mothership.heartbeats]==[20,1]
    assert all(len(s['metrics'])==5 for p in mothership.heartbeats for s in p['stations'])
    assert len(mothership.metrics)==105
    due();reporter.tick()
    assert len(mothership.metrics)==126
    assert all(sum(len(s['metrics']) for s in p['stations'])<=100 for p in mothership.heartbeats)
    assert all(len(p['stations'])<=20 for p in mothership.heartbeats)


def test_https_nullable_observations_and_lifecycle_survive_server_rollback(central,mothership,monkeypatch):
    from datetime import datetime,timezone
    reporter=actual_reporter(central,mothership)
    hour=int(time.time()//3600)*3600
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(None,None))
    sample(hour-120);sample(hour-60);reporter.tick()
    wire=mothership.heartbeats[-1]['stations'][0]
    assert wire['on_air'] is None
    assert wire['metrics'][0]['observed_seconds']==0
    assert wire['metrics'][0]['average_listeners'] is None and wire['metrics'][0]['listener_hours'] is None
    station=db.session.get(Station,1);identity=station.freo_station_id
    station.lifecycle_state='deleted';station.enabled=False;station.deleted_at=datetime.now(timezone.utc)
    db.session.commit();due();mothership.drop.add('/v1/stations/sync');reporter.tick()
    assert mothership.stations[identity]['lifecycle_state']=='deleted'
    mothership.revision=None;due();Reporter(Client).tick()
    assert mothership.stations[identity]['lifecycle_state']=='deleted'
    mothership.revision=CONTRACT_REVISION;due();Reporter(Client).tick()
    assert mothership.stations[identity]['lifecycle_state']=='deleted'
    station.lifecycle_state='ready';station.enabled=True;station.deleted_at=None
    db.session.commit();due();Reporter(Client).tick()
    assert mothership.stations[identity]['lifecycle_state']=='active'
    assert mothership.stations[identity]['deleted_at'] is None
    assert len(mothership.identities)==1
