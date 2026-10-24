"""Actual reporter behavior for the explicitly negotiated 2026-10-v1.1 contract."""
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from tests.test_central_api import app, central, FakeAPI, iso, TOKEN, INSTALLATION_ID
from app.extensions import db
from app.models import Station, CentralHourlyMetric, CentralStationState
from app.services.central_api import Reporter, installation, metadata
from app.services.central_api.client import APIError, CONTRACT_REVISION
from app.services.central_api.metrics import sample, wire_metric, machine_snapshot


def due():
    row = installation()
    row.state = dict(row.state, report={'due': 0}, license={'due': 0}, contract_probe={'due': 0})
    db.session.commit()


def payloads(api, path):
    return [payload for _, endpoint, payload, _ in api.calls if endpoint == path]


@pytest.mark.parametrize('configured,canonical', [('self-hosted','self-hosted'),('freo-studio','freo-studio'),('freo-live','freo-studio')])
@pytest.mark.parametrize('revision', [None, '2027-unknown', CONTRACT_REVISION])
def test_classification_requires_explicit_advertised_support(central, configured, canonical, revision):
    from flask import current_app
    reporter, api = central
    current_app.config.update(FREO_INSTALL_TYPE=configured, FREO_DEPLOYMENT_LABEL='freo-world', FREO_INSTALLATION_LIFECYCLE='active')
    api.revision = revision
    reporter.tick()
    assert api.health_calls == [('GET','/health',None,None)]
    machine = payloads(api, '/v1/heartbeat')[-1]['installation']
    assert machine['install_type'] == (canonical if revision == CONTRACT_REVISION or canonical == 'self-hosted' else 'freo-live')
    assert ('deployment_label' in machine) == (revision == CONTRACT_REVISION)
    assert ('lifecycle_state' in machine) == (revision == CONTRACT_REVISION)
    credentials = reporter.store.read()
    Reporter(api.factory).tick()
    assert len(api.health_calls) == 2
    assert reporter.store.read() == credentials
    assert all(station.enabled for station in Station.query)


@pytest.mark.parametrize('local,enabled,deleted,expected', [
    ('ready',True,False,'active'), ('ready',False,False,'active'),
    ('pending_create',True,False,'active'), ('retired',False,False,'retired'),
    ('pending_delete',False,False,'retired'), ('delete_failed',False,False,'retired'),
    ('deleted',False,False,'deleted'), ('ready',False,True,'deleted'),
    ('unrecognized',True,False,None),
])
def test_lifecycle_uses_database_and_stop_is_independent(central, local, enabled, deleted, expected):
    reporter, api = central
    api.revision = CONTRACT_REVISION
    station = db.session.get(Station, 1)
    station.lifecycle_state, station.enabled, station.desired_state = local, enabled, 'stopped'
    station.deleted_at = datetime(2026, 1, 1, tzinfo=timezone.utc) if deleted else None
    station.directory_opt_in = True
    identity = station.freo_station_id
    db.session.commit()
    reporter.tick()
    entry = next(s for s in payloads(api,'/v1/stations/sync')[-1]['stations'] if s['station_id'] == identity)
    assert entry.get('lifecycle_state') == expected
    if expected:
        assert entry['enabled'] is (enabled and expected == 'active')
        assert entry['deleted_at'] == ('2026-01-01T00:00:00Z' if deleted else None)
    else:
        assert 'enabled' not in entry and 'deleted_at' not in entry
    if expected in ('deleted','retired'):
        assert not entry['directory_opt_in']
        assert CentralHourlyMetric.query.filter_by(station_id=station.id).count() == 0


def test_tombstone_survives_outage_rollback_and_restores_same_uuid(central):
    reporter, api = central
    api.revision = CONTRACT_REVISION
    reporter.tick()
    station = db.session.get(Station, 1)
    identity, credentials = station.freo_station_id, reporter.store.read()
    station.lifecycle_state='deleted';station.enabled=False
    station.deleted_at=datetime.now(timezone.utc)
    db.session.commit();due()
    api.fail['/v1/stations/sync']=APIError('http_503',status=503)
    reporter.tick()
    assert station.deleted_at
    count=len(payloads(api,'/v1/stations/sync'))
    api.fail.clear();api.revision=None;due()
    Reporter(api.factory).tick()
    assert all(s['station_id'] != identity for batch in payloads(api,'/v1/stations/sync')[count:] for s in batch['stations'])
    assert station.deleted_at and reporter.store.read() == credentials
    api.revision=CONTRACT_REVISION;due()
    Reporter(api.factory).tick()
    deleted=next(s for s in payloads(api,'/v1/stations/sync')[-1]['stations'] if s['station_id']==identity)
    assert deleted['lifecycle_state']=='deleted' and not deleted['enabled']
    # Periodic reconciliation reasserts a tombstone even after its prior receipt.
    installation().state=dict(installation().state,reconcile_due=0);db.session.commit();due()
    reporter.tick()
    assert any(s['station_id']==identity for s in payloads(api,'/v1/stations/sync')[-1]['stations'])
    station.lifecycle_state='ready';station.enabled=True;station.deleted_at=None
    db.session.commit();due();reporter.tick()
    restored=next(s for s in payloads(api,'/v1/stations/sync')[-1]['stations'] if s['station_id']==identity)
    assert restored['lifecycle_state']=='active' and restored['deleted_at'] is None
    assert restored['enabled'] and reporter.store.read()==credentials


def test_rejection_rechecks_revision_and_changes_payload_only_after_backoff(central):
    reporter, api = central
    api.revision=CONTRACT_REVISION;reporter.tick();due()
    api.fail['/v1/heartbeat']=APIError('http_400',status=400)
    reporter.tick()
    calls=len(api.calls);probes=len(api.health_calls)
    reporter.tick()
    assert len(api.calls)==calls and len(api.health_calls)==probes
    api.fail.clear();api.revision=None
    row=installation();row.state=dict(row.state,contract_probe={'due':0});db.session.commit()
    reporter.tick()
    assert len(api.health_calls)==probes+1
    assert not row.state['report'].get('blocked')
    assert 'lifecycle_state' not in payloads(api,'/v1/stations/sync')[-1]['stations'][0]


def test_public_health_failure_never_rejects_installation_credentials(central):
    reporter, api=central
    reporter.tick();credentials=reporter.store.read();cache=installation().license_cache['entitlement']
    api.fail['/health']=APIError('unauthorized',status=401)
    Reporter(api.factory).tick()
    assert installation().registration_state=='enrolled'
    assert reporter.store.read()==credentials and installation().license_cache['entitlement']==cache
    assert all(s.enabled for s in Station.query)


def test_unknown_and_partial_coverage_preserve_precision(central, monkeypatch):
    reporter, api=central;api.revision=CONTRACT_REVISION
    hour=int(time.time()//3600)*3600-3600
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(True,7))
    sample(hour+1.125);sample(hour+61.375)
    row=db.session.get(CentralHourlyMetric,(1,hour));wire=wire_metric(row,True)
    assert wire['observed_seconds']==60.25
    assert abs(wire['average_listeners']*wire['observed_seconds']-wire['listener_hours']*3600)<1e-6
    sample(hour+300)
    assert row.observed_seconds==60.25
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(None,None))
    sample(hour+360)
    assert row.snapshot['current_listeners'] == 7 and row.snapshot['stream_running'] is None
    due();reporter.tick()
    entry=payloads(api,'/v1/heartbeat')[-1]['stations'][0]
    assert entry['on_air'] is None
    assert entry['metrics'][0]['current_listeners'] == 7
    assert entry['metrics'][0]['observed_seconds']==60.25
    # A completed, accepted hour cannot be replaced by an older partial sample.
    original=(row.observed_seconds,row.listener_seconds,dict(row.snapshot))
    state=db.session.get(CentralStationState,1);state.last_sample={'at':hour+10,'listeners':3};db.session.commit()
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(True,3))
    sample(hour+50)
    assert (row.observed_seconds,row.listener_seconds,row.snapshot)==original


def test_zero_and_historical_unknown_coverage_are_distinct(central):
    now=int(time.time()//3600)*3600
    zero=SimpleNamespace(period_start=now,observed_seconds=0,listener_seconds=0,peak_listeners=0,
                         snapshot={},coverage={'known':True})
    wire=wire_metric(zero,True)
    assert wire['observed_seconds']==0 and wire['average_listeners'] is None and wire['listener_hours'] is None
    zero.coverage=None
    assert wire_metric(zero,True)['observed_seconds'] is None
    assert 'observed_seconds' not in wire_metric(zero,False)


def test_legacy_unknown_hours_remain_queued_but_do_not_block_known_hours(central, monkeypatch):
    reporter,api=central
    hour=int(time.time()//3600)*3600
    for offset in range(1,8):
        snapshot=dict(current_listeners=0,songs_in_library=0,artists=0,albums=0,
                      library_duration_seconds=0,library_storage_bytes=0,stream_running=False,scheduler_running=False)
        if offset>1:snapshot['current_listeners']=None
        db.session.add(CentralHourlyMetric(station_id=1,period_start=hour-offset*3600,
            observed_seconds=60,listener_seconds=0,peak_listeners=0,snapshot=snapshot,sent=False))
    db.session.commit();reporter.tick()
    assert db.session.get(CentralHourlyMetric,(1,hour-3600)).sent
    assert not db.session.get(CentralHourlyMetric,(1,hour-7200)).sent
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(None,None))
    due();reporter.tick()
    assert payloads(api,'/v1/heartbeat')[-1]['stations']==[]


def test_deleted_backlog_drains_without_new_hours_or_identity_loss(central):
    reporter,api=central;api.revision=CONTRACT_REVISION
    hour=int(time.time()//3600)*3600
    sample(hour-120);sample(hour-60)
    station=db.session.get(Station,1);identity=station.freo_station_id
    station.lifecycle_state='deleted';station.deleted_at=datetime.now(timezone.utc);station.enabled=False
    db.session.commit();before=CentralHourlyMetric.query.filter_by(station_id=1).count()
    reporter.tick()
    assert db.session.get(CentralHourlyMetric,(1,hour-3600)).sent
    for offset in (60,3600,7200,8*86400):sample(time.time()+offset)
    assert CentralHourlyMetric.query.filter_by(station_id=1).count()==before
    assert station.freo_station_id==identity and station.deleted_at


def test_explicit_installation_lifecycle_never_follows_api_failure(central):
    from flask import current_app
    reporter,api=central;api.revision=CONTRACT_REVISION
    current_app.config['FREO_INSTALLATION_LIFECYCLE']='decommissioned'
    reporter.tick()
    assert payloads(api,'/v1/heartbeat')[-1]['installation']['lifecycle_state']=='decommissioned'
    api.fail['/v1/heartbeat']=APIError('http_503',status=503);due();reporter.tick()
    assert current_app.config['FREO_INSTALLATION_LIFECYCLE']=='decommissioned'
    current_app.config['FREO_INSTALLATION_LIFECYCLE']='active';api.fail.clear();due();reporter.tick()
    assert payloads(api,'/v1/heartbeat')[-1]['installation']['lifecycle_state']=='active'
    assert all(s.enabled for s in Station.query)


def test_unknown_hardware_is_null_and_empty_label_explicitly_clears(central,monkeypatch):
    from flask import current_app
    import app.services.central_api.metrics as metrics
    monkeypatch.setattr(metrics.os,'cpu_count',lambda:None)
    def unavailable(*args):raise OSError('unavailable')
    monkeypatch.setattr(metrics.os,'sysconf',unavailable);monkeypatch.setattr(metrics.shutil,'disk_usage',unavailable)
    current_app.config['FREO_DEPLOYMENT_LABEL']=''
    snapshot=machine_snapshot(True)
    assert all(snapshot[k] is None for k in ('cpu_count','ram_bytes','disk_total_bytes','disk_free_bytes','deployment_label'))


def test_shared_disabled_nondeleted_library_is_counted_for_each_available_channel(central):
    from app.models import Track
    from app.services.central_api.metrics import library_snapshot
    track=Track.query.first();track.available_to_all=True;track.enabled=False;db.session.commit()
    snapshots=[library_snapshot(station,False,0,time.time()) for station in Station.query.order_by(Station.id)]
    assert all(s['songs_in_library']==1 and s['library_storage_bytes']==1000 for s in snapshots)
    track.deleted_at=datetime.now(timezone.utc);db.session.commit()
    assert all(library_snapshot(station,False,0,time.time())['songs_in_library']==0 for station in Station.query)


def test_public_health_recovers_after_durable_backoff_without_credential_recovery(central):
    reporter,api=central
    api.fail['/health']=APIError('unauthorized',status=401)
    reporter.tick();retry=installation().state['contract_probe']['due']
    assert not installation().state['contract_probe']['blocked']
    api.fail.clear();Reporter(api.factory).tick(now=retry+1)
    assert installation().registration_state=='enrolled'
    assert installation().state.get('last_heartbeat')


def test_rejected_enrollment_never_retries_on_contract_revision_change(central):
    reporter,api=central
    installation().registration_state='unconfigured';db.session.commit()
    api.fail['/v1/enroll']=APIError('unauthorized',status=401)
    reporter.tick();credential=reporter.store.read()
    assert installation().registration_state=='credentials_rejected'
    api.fail.clear();api.revision=CONTRACT_REVISION;due();Reporter(api.factory).tick()
    assert len(payloads(api,'/v1/enroll'))==1
    assert reporter.store.read()==credential
    assert not payloads(api,'/v1/register')


def test_hour_boundary_keeps_last_valid_listener_and_library_observations(central,monkeypatch):
    from app.models import Track
    hour=int(time.time()//3600)*3600
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(True,2))
    sample(hour-30)
    track=Track.query.first();track.file_size_bytes=2000;db.session.commit()
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(True,9))
    sample(hour+30)
    previous=wire_metric(db.session.get(CentralHourlyMetric,(1,hour-3600)),True)
    current=wire_metric(db.session.get(CentralHourlyMetric,(1,hour)),True)
    assert previous['current_listeners']==previous['peak_listeners']==2
    assert previous['observed_seconds']==30 and previous['average_listeners']==2
    assert previous['library_storage_bytes']==1000
    assert current['current_listeners']==current['peak_listeners']==9
    assert current['observed_seconds']==30 and current['average_listeners']==2
    assert current['library_storage_bytes']==2000
    monkeypatch.setattr('app.services.central_api.metrics.observation',lambda slug:(None,None))
    sample(hour+60)
    current=wire_metric(db.session.get(CentralHourlyMetric,(1,hour)),True)
    assert current['current_listeners']==9 and current['stream_running'] is None
    assert current['observed_seconds']==30
    sample(hour+3600)
    unknown=wire_metric(db.session.get(CentralHourlyMetric,(1,hour+3600)),True)
    assert unknown['current_listeners'] is None and unknown['observed_seconds']==0
