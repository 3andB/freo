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
def app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
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
    assert 'Put your station on the air.' in client.get('/').get_data(as_text=True)
    assert 'Test Station' in client.get('/stations').get_data(as_text=True)
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
    assert 'OPERATIONAL OVERVIEW' in body
    assert 'Verified Test Track' in body
    assert 'Test Artist' in body
    assert 'Music Clock' in body
    assert 'Power' in body
    assert 'Accepted tracks' in body
    assert 'test-password-long-enough' not in page.get_data(as_text=True)
    assert page.headers['Cache-Control'] == 'private, no-store'
    assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']
    assert client.get('/dashboard/test-station').headers['Location'].endswith('/admin/stations/test-station')
    assert client.get('/admin/stations/test-station').status_code == 200
    assert 'Second Station' in client.get('/admin/stations').get_data(as_text=True)
    for section in ('media', 'categories', 'rotations', 'clocks', 'schedule', 'history', 'system'):
        response = client.get(f'/admin/{section}?station=test-station', follow_redirects=True)
        assert response.status_code == 200, section
    assert 'Verified Test Track' in client.get('/admin/media?station=test-station', follow_redirects=True).get_data(as_text=True)
    assert 'Main Rotation' in client.get('/admin/rotations?station=test-station').get_data(as_text=True)
    assert 'Monday' in client.get('/admin/schedule?station=test-station').get_data(as_text=True)
    assert 'Verified Test Track' in client.get('/admin/history?station=test-station').get_data(as_text=True)
    assert 'Verified Test Track' not in client.get('/admin/history?station=second-station').get_data(as_text=True)
    assert 'No track start has been confirmed' in client.get('/admin?station=second-station').get_data(as_text=True)
    assert client.get('/admin?station=missing').status_code == 404
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
    with client.session_transaction() as state:
        state['admin_user_id'] = identity
        state['admin_csrf'] = 'test-admin-csrf-token'
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
