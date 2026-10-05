"""Station permissions, ownership, observed sessions and private recordings."""
from datetime import datetime, timezone, timedelta
import uuid
import pytest
from app.extensions import db
from app.models import AdminUser, DJStationAssignment, LiveSession, ShowRecording, Station, LiveQueueSnapshot
from app.services import live_sessions as shows
from tests.test_web import app, admin_client
from tests.auth import authenticate


@pytest.fixture
def dj_client(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        user = AdminUser(email='dj@example.test', username='Night DJ', password_hash='unused', role='DJ')
        db.session.add(user); db.session.flush()
        db.session.add(DJStationAssignment(admin_user_id=user.id, station_id=station.id)); db.session.commit()
        identifier = user.id
    client = app.test_client(); authenticate(client, identifier, 'dj-csrf')
    return client


def test_dj_routes_and_assignment_revocation(app, dj_client, monkeypatch):
    assert dj_client.get('/admin', follow_redirects=True).status_code == 200
    assert dj_client.get('/admin/stations/test-station/live').status_code == 200
    for suffix in ('live', 'recordings', 'media', 'settings'):
        assert dj_client.get('/admin/stations/second-station/'+suffix).status_code == 403
    for url in ('/admin/djs', '/admin/stations/test-station/media', '/admin/audit',
                '/admin/api/operations', '/admin/stations/test-station/song/foreign'):
        assert dj_client.get(url).status_code in (403, 404)
    assert dj_client.get('/admin/api/stations/second-station/song-search').status_code == 403
    assert dj_client.post('/admin/api/stations/second-station/live-mic/offer',data={'csrf':'dj-csrf'}).status_code == 403
    assert dj_client.post('/admin/stations/test-station/live/hold',data={'csrf':'dj-csrf'}).status_code == 302
    with app.app_context():
        DJStationAssignment.query.delete(); db.session.commit()
    assert dj_client.get('/admin/stations/test-station/live').status_code == 403
    assert 'No stations are assigned' in dj_client.get('/admin', follow_redirects=True).text


def test_existing_admin_and_account_management(app):
    client=admin_client(app)
    with app.app_context():
        assert AdminUser.query.first().role == 'ADMIN'
    assert client.get('/admin/djs').status_code == 200
    assert client.post('/admin/djs', data={'email':'new@example.test'}).status_code == 400
    result=client.post('/admin/djs',data={'csrf':'test-admin-csrf-token','email':'new@example.test',
        'username':'New DJ','password':'a-long-initial-password','active':'yes','station_id':'1'})
    assert result.status_code==302
    with app.app_context():
        user=AdminUser.query.filter_by(email='new@example.test').one()
        assert user.role=='DJ' and db.session.get(DJStationAssignment,(user.id,1))


def test_owned_show_rejects_other_dj_and_admin_can_end(app, dj_client):
    admin=admin_client(app)
    result=dj_client.post('/admin/stations/test-station/live/mode', data={'csrf':'dj-csrf','mode':'DJ_BOOTH','record_show':'yes'})
    assert result.status_code==302
    response=admin.post('/admin/stations/test-station/live/hold',data={'csrf':'test-admin-csrf-token'},headers={'Accept':'application/json'})
    assert response.status_code==409
    assert admin.post('/admin/stations/test-station/live/end-show',data={'csrf':'test-admin-csrf-token'}).status_code==302
    with app.app_context():
        show=LiveSession.query.one()
        assert show.started_at is None and show.end_requested
        assert show.recording.status=='pending'


def observe(monkeypatch, source, start=0, end=0):
    monkeypatch.setattr(shows,'engine_observation',lambda slug:dict(source=source,started_at=start,ended_at=end,observed_at=shows.now().isoformat()))
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda slug:'engine-one')


def test_confirmed_session_spans_booth_mic_and_return(app, monkeypatch):
    with app.app_context():
        station=Station.query.first(); user=AdminUser.query.first()
        show=shows.claim(station,user); db.session.commit()
        db.session.add(LiveQueueSnapshot(station_id=station.id,observed_at=shows.now(),queued_decision_ids=[]));db.session.commit()
        observe(monkeypatch,'AUTO'); shows.sync(station)
        assert show.started_at is None and shows.describe(station)['source']=='AUTO'
        start=shows.now().timestamp();observe(monkeypatch,'DJ',start);shows.sync(station)
        assert show.started_at.timestamp()==pytest.approx(start)
        observe(monkeypatch,'MIC',start);shows.sync(station)
        observe(monkeypatch,'RETURNING',start);shows.sync(station)
        observe(monkeypatch,'DJ',start);shows.sync(station)
        assert shows.active_session(station).id==show.id
        end=start+100;observe(monkeypatch,'AUTO',start,end);shows.sync(station)
        assert shows.active_session(station) is None and show.ended_at.timestamp()==pytest.approx(end)
        assert LiveSession.query.count()==1
        snapshot=db.session.get(LiveQueueSnapshot,station.id)
        snapshot.show_observation=dict(source='AUTO',observed_at=(shows.now()-timedelta(seconds=20)).isoformat());db.session.commit()
        assert shows.describe(station)['source']=='UNKNOWN'


def test_revocation_returns_existing_booth_even_on_old_engine(app, dj_client, monkeypatch):
    with app.app_context():
        station=Station.query.first();user=AdminUser.query.filter_by(role='DJ').one()
        shows.claim(station,user);station.automation.operator_mode='DJ_BOOTH';db.session.commit()
        DJStationAssignment.query.delete();db.session.commit()
        monkeypatch.setattr(shows,'engine_observation',lambda slug: (_ for _ in ()).throw(ValueError('old engine')))
        shows.sync(station)
        assert station.automation.operator_mode=='AUTO'
        assert shows.active_session(station).end_reason=='permission_revoked'
        assert not shows.authorized_intent(station,user)


def test_recording_idor_and_path_validation(app, dj_client, tmp_path, monkeypatch):
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path))
    with app.app_context():
        station=Station.query.first();user=AdminUser.query.filter_by(role='DJ').one()
        show=shows.claim(station,user,True);db.session.commit()
        row=show.recording;row.status='complete';row.duration_ms=1000
        path=tmp_path/station.slug/'recordings'/row.storage_key;path.parent.mkdir(parents=True);path.write_bytes(b'test audio')
        identifier=row.id;db.session.commit()
    url=f'/admin/stations/test-station/recordings/{identifier}/audio'
    assert dj_client.get(url).status_code==200
    assert dj_client.get(url).headers['Cache-Control']=='private, no-store'
    assert dj_client.get(url.replace('test-station','second-station')).status_code==403
    with app.app_context():
        row=db.session.get(ShowRecording,identifier);row.admin_user_id=1;db.session.commit()
    assert dj_client.get(url).status_code==403
    from app.services.media_storage import LocalMediaStorage
    with pytest.raises(ValueError):LocalMediaStorage().recording_path('test-station','../secret.mp3')
    path.unlink();path.symlink_to('/etc/passwd')
    with pytest.raises(ValueError):LocalMediaStorage().recording_file('test-station',path.name)


def test_worker_restart_keeps_session_but_engine_restart_interrupts(app, monkeypatch):
    with app.app_context():
        station=Station.query.first();show=shows.claim(station,AdminUser.query.first());db.session.commit()
        observe(monkeypatch,'DJ',shows.now().timestamp());shows.sync(station)
        shows.sync(station);assert LiveSession.query.count()==1 and shows.active_session(station)
        monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda slug:'replacement')
        shows.sync(station)
        assert show.end_reason=='playout_restarted' and show.ended_at is None and not show.active_station_id


def test_recording_disk_failure_is_independent_of_broadcast(app, monkeypatch, tmp_path):
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path))
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:'|IDLE|0|0|')
    with app.app_context():
        station=Station.query.first();show=shows.claim(station,AdminUser.query.first(),True);db.session.commit()
        observe(monkeypatch,'AUTO');shows.sync(station)
        assert show.recording.status=='failed' and 'storage' in show.recording.error
        assert show.active_station_id==station.id and not show.end_requested


def test_additive_migration_preserves_accounts_and_defaults(app):
    import importlib
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text, inspect
    migration=importlib.import_module('migrations.versions.f306a1b2c3d4_dj_sessions_and_recordings')
    with app.app_context():
        original=[(u.id,u.email,u.installation_admin) for u in AdminUser.query.all()]
        db.session.remove()
        with db.engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
                assert 'role' not in {c['name'] for c in inspect(connection).get_columns('admin_users')}
                migration.upgrade()
            rows=connection.execute(text('SELECT id,email,installation_admin,role FROM admin_users ORDER BY id')).all()
            assert [(r.id,r.email,bool(r.installation_admin)) for r in rows]==original
            assert all(r.role=='ADMIN' for r in rows)
            assert connection.execute(text('SELECT count(*) FROM dj_station_assignments')).scalar()==0


def test_database_rejects_two_active_owners(app):
    from sqlalchemy.exc import IntegrityError
    with app.app_context():
        station=Station.query.first();shows.claim(station,AdminUser.query.first());db.session.commit()
        with pytest.raises(IntegrityError):
            with db.session.begin_nested():
                db.session.add(LiveSession(station_id=station.id,active_station_id=station.id,dj_name='Racer'))
                db.session.flush()
        assert LiveSession.query.count()==1


def test_recording_provisioning_is_narrow_and_rejects_symlinks(tmp_path, monkeypatch):
    import importlib.util
    from types import SimpleNamespace
    spec=importlib.util.spec_from_file_location('recording_storage','scripts/recording-storage.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module.os,'chown',lambda *args:None)
    monkeypatch.setattr(module.pwd,'getpwnam',lambda name:SimpleNamespace(pw_uid=123))
    monkeypatch.setattr(module.grp,'getgrnam',lambda name:SimpleNamespace(gr_gid=456))
    calls=[];monkeypatch.setattr(module.subprocess,'run',lambda args,**kwargs:calls.append(args))
    root=tmp_path/'media';root.mkdir();units=tmp_path/'units'
    module.provision(root,'test-station',units)
    override=(units/'freo-playout@test-station.service.d'/'recordings.conf').read_text()
    assert str(root/'test-station'/'recordings') in override
    worker=(units/'freo-automation.service.d'/'recordings-test-station.conf').read_text()
    assert worker == override
    assert 'u:freo:r-x,u:freo-automation:rwx' in calls[1][2]
    assert len(calls)==2 and all('setfacl'==c[0] for c in calls)
    (root/'bad').symlink_to(root/'test-station')
    with pytest.raises(ValueError):module.provision(root,'bad',units)


def test_short_show_recovered_after_worker_gap(app,monkeypatch):
    with app.app_context():
        station=Station.query.first();show=shows.claim(station,AdminUser.query.first());db.session.commit()
        start=shows.now().timestamp();observe(monkeypatch,'AUTO',start,start+2)
        shows.sync(station)
        assert show.started_at and show.ended_at and not show.active_station_id


def test_second_assigned_dj_cannot_end_or_signal_owned_show(app,dj_client):
    with app.app_context():
        station=Station.query.first();owner=AdminUser.query.first();shows.claim(station,owner);db.session.commit()
    assert dj_client.post('/admin/stations/test-station/live/end-show',data={'csrf':'dj-csrf'}).status_code==403
    assert dj_client.post('/admin/api/stations/test-station/live-mic/offer',data={'csrf':'dj-csrf','sdp':'fake'}).status_code==409


def test_cancelled_pending_show_does_not_arm_recording(app,monkeypatch):
    calls=[]
    def command(slug,value):
        calls.append(value);return '|IDLE|0|0|'
    monkeypatch.setattr('app.services.playout_queue._command',command)
    with app.app_context():
        station=Station.query.first();show=shows.claim(station,AdminUser.query.first(),True)
        show.end_requested=True;db.session.commit();observe(monkeypatch,'AUTO');shows.sync(station)
        assert not any('arm ' in value for value in calls)
        assert show.recording.status=='failed'


def test_low_space_refuses_recording_without_rejecting_show(app,monkeypatch,tmp_path):
    from types import SimpleNamespace
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path))
    monkeypatch.setattr(shows.shutil,'disk_usage',lambda path:SimpleNamespace(free=10))
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:'|IDLE|0|0|')
    with app.app_context():
        station=Station.query.first();(tmp_path/station.slug/'recordings').mkdir(parents=True)
        show=shows.claim(station,AdminUser.query.first(),True);db.session.commit()
        observe(monkeypatch,'AUTO');shows.sync(station)
        assert show.recording.status=='failed' and '256 MiB' in show.recording.error
        assert show.active_station_id==station.id


def test_worker_owned_cue_recovery_and_orphaned_commands(app,dj_client):
    from app.models import CuePlayback, LiveControlCommand, SelectionDecision, Track
    with app.app_context():
        station=Station.query.first();user=AdminUser.query.filter_by(role='DJ').one()
        shows.claim(station,user);db.session.commit()
        decision=SelectionDecision(station_id=station.id,track=Track.query.first(),selection_method='cue_auto',status='selected')
        command=LiveControlCommand(station_id=station.id,action='DECK_LOAD',deck='A',target_decision=decision,
                                   status='pending',idempotency_key=str(uuid.uuid4()))
        db.session.add(command);db.session.flush()
        assert not shows.authorized_command(station,command)
        db.session.add(CuePlayback(decision_id=decision.id,station_id=station.id,generation=str(uuid.uuid4())))
        db.session.commit()
        assert shows.authorized_command(station,command)
        DJStationAssignment.query.delete();db.session.commit()
        assert not shows.authorized_command(station,command)
        # A deleted operator's ordinary manual command remains denied.
        command.action='SKIP';db.session.commit()
        assert not shows.authorized_command(station,command)
