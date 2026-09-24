from datetime import datetime, time, timezone
from io import BytesIO
import os
import subprocess

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import (AdminUser, AutomationState, Clock, ClockSlot, MediaCategory,
                        MediaIngestJob, AuditEvent, Rotation, RotationSlot, ScheduleAssignment, SelectionDecision,
                        Station, StreamMount, Track)


@pytest.fixture
def app(monkeypatch, request, tmp_path):
    # Browser requests and fixture observations need separate SQL connections.
    database = f'sqlite:///{tmp_path}/browser.sqlite' if 'booth' in request.fixturenames else 'sqlite:///:memory:'
    monkeypatch.setenv('DATABASE_URL', database)
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        station = Station(name='Test Station', slug='test-station', description='Test stream', desired_state='running')
        station.stream = StreamMount()
        db.session.add(station)
        second = Station(name='Second Station', slug='second-station', description='Separate station', desired_state='stopped')
        second.stream = StreamMount()
        db.session.add(second)
        db.session.add(AdminUser(email='admin@example.test', password_hash=generate_password_hash('test-password-long-enough')))
        db.session.commit()
        category = MediaCategory(station_id=station.id, name='Power', slug='power', enabled=True)
        track = Track(station_id=station.id, uuid='00000000-0000-4000-8000-000000000001',
                      title='Verified Test Track', artist='Test Artist', album='Test Album',
                      original_filename='safe.mp3', storage_key='internal.mp3', media_type='mp3',
                      duration_ms=20000, sample_rate_hz=44100, channels=2, file_size_bytes=1000,
                      checksum_sha256='a' * 64, enabled=True, ingest_status='accepted')
        track.categories.append(category)
        rotation = Rotation(station_id=station.id, name='Main Rotation', slug='main', enabled=True)
        rotation.slots.append(RotationSlot(position=1, category=category, enabled=True))
        clock = Clock(station_id=station.id, name='Music Clock', slug='music', enabled=True)
        clock.slots.append(ClockSlot(position=1, slot_type='CATEGORY', category=category, enabled=True))
        db.session.add_all([category, track, rotation, clock])
        db.session.flush()
        db.session.add(AutomationState(station_id=station.id, enabled=True, active_rotation_id=rotation.id,
                                       observed_queue_depth=2))
        db.session.add(ScheduleAssignment(station_id=station.id, weekday=0, start_time=time(0, 0),
                                          clock_id=clock.id, enabled=True))
        db.session.add(SelectionDecision(station_id=station.id, track_id=track.id, category_id=category.id,
                                         rotation_id=rotation.id, clock_id=clock.id, clock_slot_id=clock.slots[0].id,
                                         status='started', started_at=datetime.now(timezone.utc),
                                         selected_at=datetime.now(timezone.utc)))
        db.session.commit()
    yield application


def test_public_pages_and_no_mutations(app):
    client = app.test_client()
    assert 'Test Station' in client.get('/').get_data(as_text=True)
    assert 'Test Station' in client.get('/stations', follow_redirects=True).get_data(as_text=True)
    assert '/stream/test-station' in client.get('/player/test-station').get_data(as_text=True)
    assert client.post('/api/stations').status_code == 405
    assert client.post('/api/stations/test-station/start').status_code == 404
    assert client.get('/player/../etc/passwd').status_code == 404


def test_dashboard_requires_login_and_password_not_leaked(app):
    client = app.test_client()
    assert client.get('/dashboard/test-station').status_code == 302
    for path in ('/admin', '/admin/stations', '/admin/media', '/admin/history',
                 '/admin/api/stations/test-station/snapshot', '/admin/api/stations/test-station/now'):
        assert client.get(path).headers['Location'].endswith('/admin/login')
    login_page = client.get('/admin/login')
    with client.session_transaction() as state:
        token = state['login_csrf']
    bad = client.post('/admin/login', data={'email':'admin@example.test','password':'wrong','csrf':token})
    assert bad.status_code == 401
    assert 'test-password-long-enough' not in bad.get_data(as_text=True)
    with client.session_transaction() as state:
        token = state['login_csrf']
    good = client.post('/admin/login', data={'email':'admin@example.test','password':'test-password-long-enough','csrf':token})
    assert good.status_code == 302
    assert good.headers['Location'].endswith('/admin')
    page = client.get('/admin')
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert 'Operations overview' in body
    assert 'Verified Test Track' in body
    assert 'Test Artist' in body
    assert 'Music Clock' in body
    assert 'Listening hours' in body
    assert 'FREO.LIVE / MOTHER SHIP' in body
    assert 'test-password-long-enough' not in page.get_data(as_text=True)
    assert page.headers['Cache-Control'] == 'private, no-store'
    assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']
    assert client.get('/dashboard/test-station').headers['Location'].endswith('/admin/stations/test-station')
    assert client.get('/admin/stations/test-station').status_code == 200
    assert 'Second Station' in client.get('/admin/stations', follow_redirects=True).get_data(as_text=True)
    for section in ('media', 'categories', 'rotations', 'clocks', 'schedule', 'history', 'system'):
        response = client.get(f'/admin/{section}?station=test-station', follow_redirects=True)
        assert response.status_code == 200, section
    assert 'Verified Test Track' in client.get('/admin/media?station=test-station', follow_redirects=True).get_data(as_text=True)
    assert 'Main Rotation' in client.get('/admin/rotations?station=test-station', follow_redirects=True).get_data(as_text=True)
    assert 'Monday' in client.get('/admin/schedule?station=test-station', follow_redirects=True).get_data(as_text=True)
    assert 'Verified Test Track' in client.get('/admin/history?station=test-station').get_data(as_text=True)
    assert 'Verified Test Track' not in client.get('/admin/history?station=second-station').get_data(as_text=True)
    assert 'Operations overview' in client.get('/admin?station=second-station').get_data(as_text=True)
    assert client.get('/admin?station=missing').status_code == 200
    assert client.get('/admin/unsupported').status_code == 404
    assert client.post('/admin/media').status_code == 405
    assert client.get('/admin/api/stations/test-station/now').json['now_playing']['title'] == 'Verified Test Track'
    snapshot = client.get('/admin/api/stations/test-station/snapshot').json
    assert snapshot['queue_depth'] == 2
    assert client.get('/admin/api/stations/test-station/snapshot').headers['Cache-Control'] == 'private, no-store'
    assert 'storage_key' not in str(snapshot)
    assert 'password_hash' not in str(snapshot)
    assert 'internal.mp3' not in client.get('/admin/media?station=test-station', follow_redirects=True).get_data(as_text=True)
    assert 'internal.mp3' not in client.get('/admin/stations/test-station').get_data(as_text=True)
    assert client.get('/admin/api/stations/second-station/now').json['now_playing'] is None


def test_login_csrf_and_client_lockout(app):
    client = app.test_client()
    assert client.post('/admin/login', data={'email':'admin@example.test','password':'anything'}).status_code == 400
    client.get('/admin/login')
    with client.session_transaction() as state:
        token = state['login_csrf']
    for _ in range(5):
        assert client.post('/admin/login', data={'email':'admin@example.test','password':'wrong','csrf':token}).status_code == 401
        with client.session_transaction() as state:
            token = state['login_csrf']
    assert client.post('/admin/login', data={'email':'admin@example.test','password':'test-password-long-enough','csrf':token}).status_code == 429


def admin_client(app):
    client = app.test_client()
    with app.app_context():
        user = AdminUser.query.filter_by(email='admin@example.test').first()
        identity = user.id
    from tests.auth import authenticate
    authenticate(client, identity)
    return client


def test_media_mutations_require_auth_csrf_and_station_ownership(app):
    client = app.test_client()
    base = '/admin/stations/test-station/media/00000000-0000-4000-8000-000000000001'
    assert client.post(base + '/disable').status_code == 302
    assert client.get(base).status_code == 302
    client = admin_client(app)
    assert client.get(base).status_code == 200
    assert client.post(base + '/disable').status_code == 400
    assert client.post(base + '/disable', data={'csrf': 'wrong'}).status_code == 400
    assert client.get('/admin/stations/second-station/media/00000000-0000-4000-8000-000000000001').status_code == 404
    assert client.post('/admin/stations/second-station/media/00000000-0000-4000-8000-000000000001/disable', data={'csrf': 'test-admin-csrf-token'}).status_code == 404
    assert client.get(base + '/disable').status_code == 405
    assert client.get('/admin/stations/test-station/media?sort=storage_key').status_code == 400
    assert 'internal.mp3' not in client.get(base).get_data(as_text=True)
    assert client.get('/admin/audit').status_code == 200
    assert 'internal.mp3' not in client.get('/admin/audit').get_data(as_text=True)
    assert client.get('/media/00000000-0000-4000-8000-000000000001').status_code == 404
    with app.app_context():
        second = Station.query.filter_by(slug='second-station').first()
        foreign = MediaCategory(station_id=second.id, name='Foreign', slug='foreign')
        db.session.add(foreign)
        db.session.commit()
        foreign_id = foreign.id
    assert client.post(base + '/categories', data={'csrf':'test-admin-csrf-token', 'category_id':str(foreign_id)}).status_code == 404
    assert client.post(base + '/edit', data={'csrf':'test-admin-csrf-token', 'title':'Changed', 'artist':'Artist', 'album':'Album'}).status_code == 303
    assert client.post(base + '/disable', data={'csrf':'test-admin-csrf-token'}).status_code == 303
    assert client.post(base + '/decommission', data={'csrf':'test-admin-csrf-token'}).status_code == 400
    assert client.post('/admin/stations/test-station/media/upload', data={'csrf':'test-admin-csrf-token', 'file':(BytesIO(b'unsafe'),'../escape.mp3')}).status_code == 302
    with app.app_context():
        track = Track.query.filter_by(uuid='00000000-0000-4000-8000-000000000001').first()
        assert track.title == 'Changed' and not track.enabled
        assert AuditEvent.query.count() >= 2


@pytest.mark.skipif(os.geteuid() != 0, reason='full filesystem ingest fixture requires the root-run test environment')
def test_web_upload_reuses_ingest_pipeline_and_review_policy(app, tmp_path, monkeypatch):
    upload_root = tmp_path / 'uploads'
    upload_root.mkdir()
    media_root = tmp_path / 'media'
    app.config['FREO_UPLOAD_ROOT'] = str(upload_root)
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(media_root))
    monkeypatch.setattr('app.services.media.os.chown', lambda *_args: None)
    audio = tmp_path / 'source.mp3'
    subprocess.run(['/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:duration=1', '-metadata', 'title=Phase 7 Test',
                    '-metadata', 'artist=Freo Test Artist', '-codec:a', 'libmp3lame', '-b:a', '64k',
                    str(audio)], check=True)
    payload = audio.read_bytes()
    client = admin_client(app)
    upload = '/admin/stations/test-station/media/upload'
    assert client.get(upload).status_code == 200
    assert client.post(upload, data={'file':(BytesIO(payload),'test.mp3')}).status_code == 400
    response = client.post(upload, data={'csrf':'test-admin-csrf-token', 'file':(BytesIO(payload),'test.mp3')})
    assert response.status_code == 303
    with app.app_context():
        from app.ingest_worker import process_one
        assert process_one()
        job = MediaIngestJob.query.order_by(MediaIngestJob.created_at.desc()).first()
        assert job.status == 'accepted'
        track = job.track
        assert track and not track.enabled and track.title == 'Phase 7 Test'
        assert track.original_filename == 'test.mp3'
        assert track.categories == []
        track_uuid = track.uuid
        assert (media_root / 'test-station' / 'originals' / track.storage_key).is_file()
    detail = f'/admin/stations/test-station/media/{track_uuid}'
    assert client.get(detail).status_code == 200
    with app.app_context():
        category = MediaCategory.query.filter_by(station_id=track.station_id, slug='power').first()
        category_id = category.id
    assert client.post(detail + '/categories', data={'csrf':'test-admin-csrf-token', 'category_id':str(category_id)}).status_code == 303
    enabled = client.post(detail + '/enable', data={'csrf':'test-admin-csrf-token'})
    assert enabled.status_code == 303
    with app.app_context():
        assert process_one()
        track = Track.query.filter_by(uuid=track_uuid).first()
        assert track.enabled and track in track.categories[0].tracks
    assert client.post(detail + '/disable', data={'csrf':'test-admin-csrf-token'}).status_code == 303
    with app.app_context():
        assert not Track.query.filter_by(uuid=track_uuid).first().enabled
    duplicate = client.post(upload, data={'csrf':'test-admin-csrf-token', 'file':(BytesIO(payload),'again.mp3')})
    assert duplicate.status_code == 303
    with app.app_context():
        assert process_one()
        assert MediaIngestJob.query.order_by(MediaIngestJob.created_at.desc()).first().status == 'duplicate'
        assert Track.query.filter_by(station_id=track.station_id).count() == 2
    invalid = client.post(upload, data={'csrf':'test-admin-csrf-token', 'file':(BytesIO(b'not audio'),'fake.mp3')})
    assert invalid.status_code == 303
    with app.app_context():
        assert process_one()
        assert MediaIngestJob.query.order_by(MediaIngestJob.created_at.desc()).first().status == 'rejected'
    assert client.post(detail + '/decommission', data={'csrf':'test-admin-csrf-token','confirm':'decommission'}).status_code == 303
    with app.app_context():
        track = Track.query.filter_by(uuid=track_uuid).first()
        assert track.decommissioned_at and not track.enabled and not track.categories
        assert AuditEvent.query.count() >= 6
    assert client.post(detail + '/enable', data={'csrf':'test-admin-csrf-token'}).status_code == 409
    app.config['MAX_CONTENT_LENGTH'] = 1000
    assert client.post(upload, data={'csrf':'test-admin-csrf-token', 'file':(BytesIO(payload),'too-large.mp3')}).status_code == 413


def test_programming_pages_and_mutation_boundary(app):
    anon = app.test_client()
    base = '/admin/stations/test-station'
    assert anon.get(base + '/rotations').status_code == 302
    assert anon.post(base + '/categories/create', data={'name': 'Gold', 'slug': 'gold'}).status_code == 302
    client = admin_client(app)
    for section in ('categories', 'rotations', 'clocks', 'schedule'):
        assert client.get(base + '/' + section).status_code == 200
    assert client.get(base + '/categories/power').status_code == 200
    assert client.get(base + '/rotations/main').status_code == 200
    assert client.get(base + '/clocks/music').status_code == 200
    assert client.post(base + '/categories/create', data={'name':'Gold','slug':'gold'}).status_code == 400
    assert client.get(base + '/categories/create').status_code in (404, 405)
    token = 'test-admin-csrf-token'
    assert client.post(base + '/categories/create', data={'csrf':token,'name':'Gold','slug':'gold'}).status_code == 303
    assert client.post(base + '/rotations/create', data={'csrf':token,'name':'Second','slug':'second'}).status_code == 303
    assert client.post(base + '/rotations/second/slots/add', data={'csrf':token,'category':'gold'}).status_code == 303
    assert client.post(base + '/rotations/second/slots/add', data={'csrf':token,'category':'power'}).status_code == 303
    assert client.post(base + '/rotations/second/slots/move', data={'csrf':token,'position':'1','to':'2'}).status_code == 303
    assert client.post(base + '/clocks/create', data={'csrf':token,'name':'Second','slug':'second'}).status_code == 303
    assert client.post(base + '/clocks/second/slots/add', data={'csrf':token,'slot_type':'CATEGORY','target':'gold'}).status_code == 303
    assert client.post(base + '/clocks/second/slots/add', data={'csrf':token,'slot_type':'ROTATION','target':'second'}).status_code == 303
    assert client.post(base + '/clocks/second/slots/move', data={'csrf':token,'position':'1','to':'2'}).status_code == 303
    assert client.post(base + '/schedule/create', data={'csrf':token,'weekday':'2','time':'09:00','clock':'second'}).status_code == 303
    assert client.post(base + '/schedule/create', data={'csrf':token,'weekday':'2','time':'09:00','clock':'second'}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert ScheduleAssignment.query.filter_by(weekday=2, start_time=time(9,0)).count() == 1
        assert Rotation.query.filter_by(slug='second').one().slots[0].category.slug == 'power'
        assert Clock.query.filter_by(slug='second').one().slots[0].slot_type == 'ROTATION'
        assert AuditEvent.query.filter_by(action='rotation_slot_reordered').count() == 1
    assert client.post(base + '/clocks/second/slots/add', data={'csrf':token,'slot_type':'CART','target':'gold'}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert len(Clock.query.filter_by(slug='second').one().slots) == 2
    assert client.post('/admin/stations/second-station/clocks/second/slots/add', data={'csrf':token,'slot_type':'CATEGORY','target':'power'}, follow_redirects=True).status_code == 404
    assert client.get('/admin/stations/second-station/clocks/second').status_code == 404
    assert client.post(base + '/schedule/timezone', data={'csrf':token,'timezone':'../../etc','confirm':'UTC'}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().timezone == 'UTC'


def test_programming_membership_schedule_edit_and_idor(app):
    client = admin_client(app)
    base = '/admin/stations/test-station'
    token = 'test-admin-csrf-token'
    track_id = '00000000-0000-4000-8000-000000000001'
    assert client.post(base + '/categories/power/remove', data={'csrf':token,'track_uuid':track_id}).status_code == 303
    with app.app_context():
        assert not Track.query.filter_by(uuid=track_id).one().categories
    assert client.post(base + '/categories/power/assign', data={'csrf':token,'track_uuid':track_id}).status_code == 303
    with app.app_context():
        assert len(Track.query.filter_by(uuid=track_id).one().categories) == 1
        other = Station.query.filter_by(slug='second-station').one()
        foreign_track = Track(station_id=other.id, uuid='00000000-0000-4000-8000-000000000002',
            title='Foreign', artist='Other', album='', original_filename='foreign.mp3', storage_key='foreign.mp3',
            media_type='mp3', duration_ms=1000, sample_rate_hz=44100, channels=1, file_size_bytes=1,
            checksum_sha256='b'*64, enabled=True, ingest_status='accepted')
        db.session.add(foreign_track)
        db.session.commit()
    response = client.post(base + '/categories/power/assign', data={'csrf':token,'track_uuid':'00000000-0000-4000-8000-000000000002'}, follow_redirects=True)
    assert 'does not belong to this station' in response.get_data(as_text=True)
    with app.app_context():
        assert not Track.query.filter_by(uuid='00000000-0000-4000-8000-000000000002').one().categories
        assignment = ScheduleAssignment.query.filter_by(station_id=Station.query.filter_by(slug='test-station').one().id).one()
        assignment_id = assignment.id
    assert client.post(base + '/schedule/edit', data={'csrf':token,'assignment_id':assignment_id,
        'weekday':'1','time':'12:30','clock':'music'}).status_code == 303
    with app.app_context():
        row = db.session.get(ScheduleAssignment, assignment_id)
        assert row.weekday == 1 and row.start_time == time(12,30)
    assert client.post('/admin/stations/second-station/schedule/remove', data={'csrf':token,
        'assignment_id':assignment_id,'confirm':str(assignment_id)}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert db.session.get(ScheduleAssignment, assignment_id)
    assert client.post(base + '/schedule/remove', data={'csrf':token,'assignment_id':assignment_id,
        'confirm':str(assignment_id)}).status_code == 303
    with app.app_context():
        assert db.session.get(ScheduleAssignment, assignment_id) is None
        assert AuditEvent.query.filter_by(action='schedule_assignment_removed').count() == 1


def test_programming_preview_is_read_only_and_invalid_inputs(app):
    client = admin_client(app)
    base = '/admin/stations/test-station'
    with app.app_context():
        state = AutomationState.query.one()
        before = state.next_slot_index
        decisions = SelectionDecision.query.count()
    assert client.get(base + '/schedule?date=2026-09-14&hours=24').status_code == 200
    assert client.get(base + '/schedule?date=2026-09-14&hours=168').status_code == 200
    assert client.get(base + '/clocks/music?preview=10').status_code == 200
    assert client.get(base + '/rotations/main?preview=10').status_code == 200
    with app.app_context():
        assert AutomationState.query.one().next_slot_index == before
        assert SelectionDecision.query.count() == decisions
    token = 'test-admin-csrf-token'
    assert client.post(base + '/schedule/create', data={'csrf':token,'weekday':'7','time':'07:00','clock':'music'}, follow_redirects=True).status_code == 200
    assert client.post(base + '/schedule/create', data={'csrf':token,'weekday':'1','time':'25:00','clock':'music'}, follow_redirects=True).status_code == 200
    assert client.post(base + '/clocks/music/slots/add', data={'csrf':token,'slot_type':'SCRIPT','target':'power'}, follow_redirects=True).status_code == 200
    assert client.post(base + '/rotations/main/slots/move', data={'csrf':token,'position':'1','to':'999'}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert ScheduleAssignment.query.count() == 1
        assert len(Clock.query.filter_by(slug='music').one().slots) == 1
        assert len(Rotation.query.filter_by(slug='main').one().slots) == 1


def test_programming_final_slot_and_active_resource_protection(app):
    client = admin_client(app)
    base = '/admin/stations/test-station'
    token = 'test-admin-csrf-token'
    response = client.post(base + '/rotations/main/slots/remove', data={'csrf':token,'position':'1'}, follow_redirects=True)
    assert 'final enabled slot' in response.get_data(as_text=True)
    response = client.post(base + '/clocks/music/slots/remove', data={'csrf':token,'position':'1'}, follow_redirects=True)
    assert 'final enabled slot' in response.get_data(as_text=True)
    response = client.post(base + '/rotations/main/disable', data={'csrf':token}, follow_redirects=True)
    assert 'active' in response.get_data(as_text=True)
    response = client.post(base + '/categories/power/disable', data={'csrf':token}, follow_redirects=True)
    assert 'referenced' in response.get_data(as_text=True)
    response = client.post(base + '/clocks/music/disable', data={'csrf':token}, follow_redirects=True)
    assert 'weekly assignments' in response.get_data(as_text=True)
    with app.app_context():
        assert Rotation.query.filter_by(slug='main').one().enabled
        assert Clock.query.filter_by(slug='music').one().enabled
        assert MediaCategory.query.filter_by(slug='power').one().enabled
        assert AuditEvent.query.filter(AuditEvent.action.in_(['rotation_disabled','clock_disabled','category_disabled'])).count() == 0


def test_programming_timezone_change_is_validated_and_audited(app):
    client = admin_client(app)
    route = '/admin/stations/test-station/schedule/timezone'
    token = 'test-admin-csrf-token'
    assert client.post(route, data={'csrf':token,'timezone':'America/Phoenix','confirm':'wrong'}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().timezone == 'UTC'
    assert client.post(route, data={'csrf':token,'timezone':'America/Phoenix','confirm':'UTC'}).status_code == 303
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().timezone == 'America/Phoenix'
        assert AuditEvent.query.filter_by(action='station_timezone_changed').count() == 1
    assert client.post(route, data={'csrf':token,'timezone':'UTC','confirm':'America/Phoenix'}).status_code == 303
    with app.app_context():
        assert Station.query.filter_by(slug='test-station').one().timezone == 'UTC'
