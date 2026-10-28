from datetime import datetime, timedelta, timezone
import socket
import pytest
from app import models as m
from app.extensions import db
from app.services import relay
from app.services.relay_transport import validate_url, allowed_addresses
from tests.test_web import app, admin_client
from tests.test_phase3_dj import dj_client

BASE = '/admin/stations/test-station/settings/relay'


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 80))])


def test_configuration_permissions_revision_and_station_scope(app, public_dns, dj_client):
    client = admin_client(app)
    form = dict(csrf='test-admin-csrf-token', relay_revision='0', relay_enabled='yes', relay_url='https://radio.example/audio?secret=hidden')
    assert app.test_client().post(BASE, data=form).status_code == 302
    assert dj_client.post(BASE, data=form).status_code == 403
    assert client.post(BASE, data={}).status_code == 400
    assert client.post(BASE, data=form).status_code == 303
    assert client.post(BASE, data=form, headers={'Accept':'application/json'}).status_code == 400
    status = client.get(BASE).json
    assert status['enabled'] and status['pending'] and status['connected'] is None
    assert 'hidden' not in str(status)
    assert client.get('/admin/stations/second-station/settings/relay').json['enabled'] is False
    page = client.get('/admin/stations/test-station/settings')
    assert page.status_code == 200 and 'id="relay-settings"' in page.text
    with app.app_context():
        assert m.StationRelay.query.count() == 1
        assert 'hidden' not in m.AuditEvent.query.filter_by(action='relay_settings').one().summary
    form.update(relay_revision='1', relay_enabled='no', relay_url='')
    assert client.post(BASE, data=form).status_code == 303
    assert not client.get(BASE).json['enabled']


@pytest.mark.parametrize('url', ['file:///etc/passwd','ftp://radio.test/a','http://user:pass@radio.test/a',
    'https://radio.test/a\nfreo_queue.skip', 'http://radio.test:0/a', 'http://radio.test:65536/a',
    'https://radio.test/a#fragment', 'http://[fe80::1%eth0]/a','http://radio.test/a b'])
def test_url_rejections(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize('ip,networks,valid', [('127.0.0.1','',False),('10.0.0.4','10.0.0.0/24',True),
    ('10.0.1.4','10.0.0.0/24',False),('169.254.169.254','169.254.0.0/16',False),
    ('::ffff:127.0.0.1','',False),('93.184.216.34','',True),('::1','::1/128',True)])
def test_network_policy(monkeypatch, ip, networks, valid):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(0,0,0,'',(ip,80))])
    if valid:
        assert allowed_addresses(validate_url('http://radio.test/audio'), networks) == [ip]
    else:
        with pytest.raises(ValueError):
            allowed_addresses(validate_url('http://radio.test/audio'), networks)


def test_status_metadata_and_staleness(app):
    from app.services.player import now_playing
    with app.test_request_context():
        station = m.Station.query.filter_by(slug='test-station').one()
        now = datetime.now(timezone.utc)
        row = m.StationRelay(station_id=station.id, enabled=True, url='https://hidden.test/token', revision=1,
            applied_revision=1, observed_at=now, observation=dict(connected=True, ready=True, selected=True,
                source='relay', title='<b>Stream title</b>', artist='Artist'))
        db.session.add_all([row, m.LiveQueueSnapshot(station_id=station.id, observed_at=now, queued_decision_ids=[], mixer={'mode':'AUTO'})]);db.session.commit()
        state = now_playing(station)
        assert state['current'][0]['title'] == '<b>Stream title</b>'
        assert state['current'][0]['track'] is None and not state['current'][0]['votable']
        row.observed_at = now-timedelta(seconds=11);db.session.commit()
        assert relay.describe(station)['source'] == 'unknown'
        assert now_playing(station)['current'] == []


def test_disabled_stations_do_not_contact_engine(app, monkeypatch):
    monkeypatch.setattr('app.services.playout_queue._command', lambda *a: pytest.fail('unexpected engine call'))
    with app.app_context():
        assert relay.reconcile(m.Station.query.first(), object()) is None


def test_socket_rejects_upstream_and_command_injection(app):
    from app.services.playout_queue import _command
    with app.app_context():
        for value in ['freo_relay.apply 1 https://radio.test/a', 'freo_relay.apply 1 http://127.0.0.1:8092/abc\nfreo_queue.skip']:
            with pytest.raises(ValueError):
                _command('test-station', value)


def test_deferred_events_expire_without_queueing(app):
    from app.services.timed_events import save_event, generate_occurrences
    with app.app_context():
        station=m.Station.query.filter_by(slug='test-station').one();track=m.Track.query.first()
        now=datetime.now(timezone.utc)
        event=save_event(station.slug,name='Relay waiting',timing_mode='NON_INTERRUPTING',recurrence_type='ONE_TIME',
            content_type='TRACK',content_identifier=track.uuid,local_date=now.date().isoformat(), local_time=(now-timedelta(seconds=1)).time().replace(microsecond=0).isoformat(),
            interrupt_policy='NEVER',late_tolerance_seconds=60)
        generate_occurrences(station,now);db.session.commit()
        relay.defer_events(station)
        occurrence=m.TimedEventOccurrence.query.filter_by(timed_event_id=event.id).one()
        assert occurrence.failure_reason=='waiting_for_relay' and occurrence.state=='PENDING'
        occurrence.deadline_at_utc=now-timedelta(seconds=1);db.session.commit()
        relay.defer_events(station)
        assert occurrence.state=='MISSED'
        assert occurrence.selection_decision_id is None


def test_relay_migration_roundtrip(app):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('phase7','migrations/versions/f706a1b2c3d4_station_relays.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with app.app_context():
        with db.engine.begin() as connection:
            migration.op=Operations(MigrationContext.configure(connection))
            migration.downgrade();migration.upgrade()
        assert m.Station.query.count()==2 and m.SelectionDecision.query.count()==1
        assert not relay.describe(m.Station.query.first())['enabled']


def test_worker_reapplies_after_restart_and_does_not_publish_transport(app,monkeypatch):
    from app.automation_worker import EventReader
    calls=[]
    class Transport:
        def __init__(self,*args):pass
        def configure(self,*args):return 'http://127.0.0.1:8092/'+'a'*64
    monkeypatch.setattr(relay,'RelayTransport',Transport)
    identity=['engine-1']
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda slug:identity[0])
    def command(slug,value):
        calls.append(value)
        if value=='freo_relay.state':
            return '{"connected":true,"ready":true,"selected":true,"source":"relay","title":"Music","artist":"Artist","failure":0,"reconnect":1}'
        return 'OK'
    monkeypatch.setattr('app.services.playout_queue._command',command)
    with app.app_context():
        station=m.Station.query.filter_by(slug='test-station').one()
        db.session.add(m.StationRelay(station_id=station.id,enabled=True,url='https://private.test/secret'));db.session.commit()
        reader=EventReader()
        for _ in range(2):relay.reconcile(station,reader)
        assert len([call for call in calls if call.startswith('freo_relay.apply')])==1
        identity[0]='engine-2';relay.reconcile(station,reader)
        assert len([call for call in calls if call.startswith('freo_relay.apply')])==2
        assert 'private.test' not in str(calls)+str(relay.describe(station))
        relay.reconcile(station,EventReader())
        assert len([call for call in calls if call.startswith('freo_relay.apply')])==3


def test_enabling_relay_creates_worker_state_and_fallback(app, public_dns):
    client=admin_client(app)
    with app.app_context():
        assert m.Station.query.filter_by(slug='second-station').one().automation is None
    result=client.post('/admin/stations/second-station/settings/relay',data=dict(
        csrf='test-admin-csrf-token',relay_enabled='yes',relay_url='https://radio.test/audio',relay_revision=0))
    assert result.status_code==303
    with app.app_context():
        station=m.Station.query.filter_by(slug='second-station').one()
        assert station.automation.enabled and station.automation.operator_mode=='AUTO'


def test_disable_does_not_depend_on_upstream_dns(app,public_dns,monkeypatch):
    client=admin_client(app)
    form=dict(csrf='test-admin-csrf-token',relay_enabled='yes',relay_url='https://radio.test/audio',relay_revision=0)
    assert client.post(BASE,data=form).status_code==303
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k: (_ for _ in ()).throw(socket.gaierror()))
    form.update(relay_enabled='no',relay_revision=1)
    assert client.post(BASE,data=form).status_code==303
    assert not client.get(BASE).json['enabled']


def test_stopped_station_revokes_transport_and_resume_reapplies():
    from types import SimpleNamespace
    calls=[]
    reader=SimpleNamespace(relay_transport=SimpleNamespace(configure=lambda *args:calls.append(args)),
                           relay_applied={1:(2,'engine'),2:(3,'other-engine')})
    relay.suspend(1,reader)
    assert calls==[(1,'')] and reader.relay_applied=={2:(3,'other-engine')}
