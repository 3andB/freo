"""Imaging stays separate from music and cannot cross station boundaries."""
from datetime import datetime, timezone
import io
import subprocess
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import AdminUser, ClockState, ImagingAsset, SelectionDecision
from app.services.automation import category_create, assign_track, set_automation, select_next
from app.services.clocks import add_clock_slot, create_clock, preview_clock, set_default_clock
from app.services.imaging import create_group, set_group_membership, choose_group
from app.services.media_storage import LocalMediaStorage
from app.services.stations import create_station
from app.models import Track
from app.ingest_worker import process_one
from app.models import MediaIngestJob
from app.services.playout_queue import _metadata


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(tmp_path / 'media'))
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        one = create_station('One', 'one')
        two = create_station('Two', 'two')
        storage = LocalMediaStorage(tmp_path / 'media')
        for slug in ('one','two'):
            (storage.station_dir(slug) / 'imaging').mkdir(parents=True)
            (storage.station_dir(slug) / 'originals').mkdir()
        yield app, one, two, storage
        db.session.remove(); db.drop_all()


def imaging(station, storage, name='ID', enabled=True):
    key = uuid.uuid4().hex + '.mp3'
    storage.imaging_path(station.slug, key).write_bytes(b'fixture')
    row = ImagingAsset(station_id=station.id, uuid=str(uuid.uuid4()), name=name,
        cart_code=name.upper(), asset_type='STATION_ID', original_filename='id.mp3', storage_key=key,
        media_type='mp3', duration_ms=1000, sample_rate_hz=44100, channels=1,
        file_size_bytes=7, checksum_sha256=uuid.uuid4().hex * 2,
        enabled=enabled, ingest_status='accepted')
    db.session.add(row); db.session.commit()
    return row


def music(station, storage, category):
    key = uuid.uuid4().hex + '.mp3'
    storage.approved_path(station.slug, key).write_bytes(b'fixture')
    row = Track(station_id=station.id, uuid=str(uuid.uuid4()), title='Song', artist='Artist',
        album='', original_filename='song.mp3', storage_key=key, media_type='mp3',
        duration_ms=1000, sample_rate_hz=44100, channels=1, file_size_bytes=7,
        checksum_sha256=uuid.uuid4().hex * 2, enabled=True, ingest_status='accepted')
    db.session.add(row); db.session.commit(); assign_track(station.slug, row.uuid, category)
    return row


def test_cart_group_clock_preview_and_selection(world):
    app, one, _, storage = world
    category_create('one', 'Power', 'power')
    track = music(one, storage, 'power')
    asset = imaging(one, storage)
    group = create_group('one', 'IDs', 'ids')
    set_group_membership('one', 'ids', asset.uuid, True)
    clock = create_clock('one', 'Imaging', 'imaging')
    add_clock_slot('one', 'imaging', 'CATEGORY', 'power')
    add_clock_slot('one', 'imaging', 'IMAGING_GROUP', 'ids')
    add_clock_slot('one', 'imaging', 'CART', asset.uuid)
    set_default_clock('one', 'imaging')
    set_automation('one', True)
    before = SelectionDecision.query.count()
    result = preview_clock('one', 'imaging', 3, storage=storage)
    assert [row['type'] for row in result] == ['CATEGORY','IMAGING_GROUP','CART']
    assert result[1]['imaging_asset'] == asset.uuid
    assert SelectionDecision.query.count() == before
    first = select_next('one', storage=storage)
    second = select_next('one', storage=storage)
    third = select_next('one', storage=storage)
    assert first.track_id == track.id
    assert second.imaging_asset_id == third.imaging_asset_id == asset.id
    assert second.track_id is None and second.selection_method == 'imaging_group'
    assert third.selection_method == 'cart'
    assert db.session.get(ClockState, one.id).next_slot_index == 0


def test_cross_station_imaging_clock_targets_rejected(world):
    _, one, two, storage = world
    asset = imaging(two, storage)
    create_group('two', 'IDs', 'ids')
    create_group('one', 'IDs', 'ids')
    create_clock('one', 'Clock', 'clock')
    with pytest.raises(ValueError):
        add_clock_slot('one', 'clock', 'CART', asset.uuid)
    with pytest.raises(ValueError):
        add_clock_slot('one', 'clock', 'IMAGING_GROUP', 'ids')
    with pytest.raises(ValueError):
        add_clock_slot('one', 'clock', 'SCRIPT', 'anything')
    with pytest.raises(ValueError):
        set_group_membership('one', 'ids', asset.uuid, True)


def test_imaging_routes_require_auth_and_csrf(world):
    app, one, _, storage = world
    asset = imaging(one, storage)
    client = app.test_client()
    assert client.get('/admin/stations/one/imaging').status_code == 302
    assert client.post(f'/admin/stations/one/imaging/{asset.uuid}/disable').status_code == 302
    user = AdminUser(email='test@example.com', password_hash='unused', active=True)
    db.session.add(user); db.session.commit()
    with client.session_transaction() as session:
        session['admin_user_id'] = user.id
        session['admin_csrf'] = 'test-csrf'
    assert client.get('/admin/stations/one/imaging').status_code == 200
    assert client.get(f'/admin/stations/one/imaging/{asset.uuid}').status_code == 200
    assert client.post(f'/admin/stations/one/imaging/{asset.uuid}/disable').status_code == 400
    assert client.post(f'/admin/stations/one/imaging/{asset.uuid}/disable', data={'csrf':'test-csrf'}).status_code == 303
    assert not db.session.get(ImagingAsset, asset.id).enabled
    assert client.get(f'/admin/stations/two/imaging/{asset.uuid}').status_code == 404
    assert client.post(f'/admin/stations/two/imaging/{asset.uuid}/disable', data={'csrf':'test-csrf'}).status_code == 404
    assert client.get(f'/admin/stations/one/imaging/{asset.uuid}/disable').status_code == 405
    response = client.get('/api/stations/one/history')
    assert response.status_code == 200
    assert '/originals/' not in response.get_data(as_text=True) and '/imaging/' not in response.get_data(as_text=True)
    app.config['MAX_CONTENT_LENGTH'] = 100
    too_large = client.post('/admin/stations/one/imaging/upload', data={'csrf':'test-csrf',
        'asset_type':'CART', 'file':(io.BytesIO(b'x'*200), 'large.mp3')}, content_type='multipart/form-data')
    assert too_large.status_code == 413
    assert b'Upload exceeds' in too_large.data


def test_clock_editor_rejects_cross_station_imaging_target(world):
    app, one, two, storage = world
    asset = imaging(two, storage)
    clock = create_clock('one', 'Clock', 'clock')
    user = AdminUser(email='clock@example.com', password_hash='unused', active=True)
    db.session.add(user); db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_user_id'] = user.id
        session['admin_csrf'] = 'csrf'
    url = '/admin/stations/one/clocks/clock/slots/add'
    assert client.post(url, data={'slot_type':'CART','target':asset.uuid}).status_code == 400
    response = client.post(url, data={'csrf':'csrf','slot_type':'CART','target':asset.uuid})
    assert response.status_code == 303
    db.session.expire_all()
    assert not clock.slots


def test_imaging_group_recency_uses_confirmed_starts(world):
    _, one, _, storage = world
    first = imaging(one, storage, 'A')
    second = imaging(one, storage, 'B')
    group = create_group('one', 'IDs', 'ids', minimum_separation_seconds=600)
    set_group_membership('one', 'ids', first.uuid, True)
    set_group_membership('one', 'ids', second.uuid, True)
    now = datetime.now(timezone.utc)
    choice, relaxation, _ = choose_group(group, one.id, storage, now)
    assert choice.id == first.id and relaxation == 'none'
    db.session.add(SelectionDecision(station_id=one.id, imaging_asset_id=first.id,
        selected_at=now, started_at=now, status='started', selection_method='imaging_group'))
    db.session.commit()
    choice, relaxation, _ = choose_group(group, one.id, storage, now)
    assert choice.id == second.id and relaxation == 'none'
    db.session.add(SelectionDecision(station_id=one.id, imaging_asset_id=second.id,
        selected_at=now, started_at=now, status='started', selection_method='imaging_group'))
    db.session.commit()
    choice, relaxation, _ = choose_group(group, one.id, storage, now)
    assert choice.id == first.id and relaxation == 'imaging_separation'


def test_imaging_metadata_cannot_inject_queue_commands():
    assert _metadata('ID"\nfreo_queue.push evil', 'ID') == 'ID freo_queue.push evil'
    assert _metadata('Émission — nuit', 'ID') == 'Emission nuit'


def test_web_imaging_ingest_duplicate_and_invalid(world, tmp_path, monkeypatch):
    app, one, _, storage = world
    # The managed test namespace cannot chown temp files; only that OS boundary is stubbed.
    monkeypatch.setattr('os.chown', lambda *args: None)
    stage = tmp_path / 'uploads'; stage.mkdir()
    app.config['FREO_UPLOAD_ROOT'] = stage
    fixture = tmp_path / 'legal.mp3'
    subprocess.run(['/usr/bin/ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi',
        '-i', 'sine=frequency=440:duration=1', '-codec:a', 'libmp3lame', '-qscale:a', '8', str(fixture)], check=True)
    user = AdminUser(email='ingest@example.com', password_hash='unused', active=True)
    db.session.add(user); db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session['admin_user_id'] = user.id
        session['admin_csrf'] = 'csrf'
    endpoint = '/admin/stations/one/imaging/upload'
    def upload_audio(payload, filename):
        response = client.post(endpoint, data={'csrf':'csrf', 'asset_type':'STATION_ID',
            'name':'Top of Hour', 'cart_code':'ID-TOH', 'file':(io.BytesIO(payload), filename)},
            content_type='multipart/form-data')
        assert response.status_code == 303
        return MediaIngestJob.query.order_by(MediaIngestJob.created_at.desc(), MediaIngestJob.id.desc()).first()
    data = fixture.read_bytes()
    first = upload_audio(data, 'one.mp3')
    assert process_one()
    db.session.refresh(first)
    assert first.status == 'accepted'
    assert not first.imaging_asset.enabled
    assert storage.imaging_file('one', first.imaging_asset.storage_key).exists()
    second = upload_audio(data, 'duplicate.mp3')
    assert process_one()
    db.session.refresh(second)
    assert second.status == 'duplicate'
    assert ImagingAsset.query.filter_by(station_id=one.id).count() == 1
    assert len(list((storage.station_dir('one') / 'imaging').glob('*.mp3'))) == 1
    third = upload_audio(b'not audio', 'pretend.mp3')
    assert process_one()
    db.session.refresh(third)
    assert third.status == 'rejected'
    assert ImagingAsset.query.filter_by(station_id=one.id).count() == 1
