from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app import create_app
from app.extensions import db
from app.models import AutomationHeartbeat, AutomationState, MediaCategory, SelectionDecision, Track
from app.services import automation
from app.services.media_storage import LocalMediaStorage
from app.services.stations import create_station


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        create_station('One', 'one')
        create_station('Two', 'two')
        storage = LocalMediaStorage(tmp_path / 'media')
        yield app, storage
        db.drop_all()


def make_track(slug, artist, storage, title=None):
    station = automation.require_station(slug)
    key = uuid.uuid4().hex + '.mp3'
    path = storage.station_dir(slug) / 'originals'
    path.mkdir(parents=True, exist_ok=True)
    (path / key).write_bytes(b'audio fixture')
    track = Track(station_id=station.id, uuid=str(uuid.uuid4()), title=title or key[:6],
        artist=artist, album='', original_filename='fixture.mp3', storage_key=key,
        media_type='mp3', duration_ms=1000, sample_rate_hz=44100, channels=1,
        file_size_bytes=13, checksum_sha256=uuid.uuid4().hex * 2,
        enabled=True, ingest_status='accepted')
    db.session.add(track)
    db.session.commit()
    return track


def make_rotation(storage):
    power = automation.category_create('one', 'Power', 'power')
    medium = automation.category_create('one', 'Medium', 'medium')
    a = make_track('one', 'Artist A', storage)
    b = make_track('one', 'Artist B', storage)
    c = make_track('one', 'Artist C', storage)
    automation.assign_track('one', a.uuid, 'power')
    automation.assign_track('one', b.uuid, 'power')
    automation.assign_track('one', c.uuid, 'medium')
    automation.rotation_create('one', 'Main', 'main')
    automation.add_slot('one', 'main', 'power')
    automation.add_slot('one', 'main', 'medium')
    automation.activate('one', 'main')
    automation.set_automation('one', True, 3600, 3600)
    return a, b, c


def test_station_scoping_and_category_membership(setup):
    app, storage = setup
    with app.app_context():
        a, b, c = make_rotation(storage)
        other = make_track('two', 'Other Artist', storage)
        with pytest.raises(ValueError, match='Track not found'):
            automation.assign_track('one', other.uuid, 'power')
        with pytest.raises(ValueError, match='Category not found'):
            automation.add_slot('one', 'main', 'missing')
        with pytest.raises(ValueError):
            automation.category_create('one', 'Bad', '../escape')
        with pytest.raises(ValueError, match='already exists'):
            automation.category_create('one', 'Power Again', 'power')
        client = app.test_client()
        assert len(client.get('/api/stations/one/categories').json['categories']) == 2
        assert client.get('/api/stations/two/categories').json['categories'] == []
        assert client.post('/api/stations/one/categories', json={'slug':'evil'}).status_code in (404, 405)
        assert client.post('/api/stations/one/automation/enable').status_code in (404, 405)


def test_slot_cursor_preview_and_started_history(setup):
    app, storage = setup
    with app.app_context():
        a, b, c = make_rotation(storage)
        state = automation.require_station('one').automation
        before = (state.next_slot_index, SelectionDecision.query.count())
        plan = automation.preview('one', 4, storage)
        assert [row['category'] for row in plan] == ['power', 'medium', 'power', 'medium']
        assert (state.next_slot_index, SelectionDecision.query.count()) == before
        now = datetime.now(timezone.utc)
        first = automation.select_next('one', storage, now)
        assert first.category.slug == 'power' and first.status == 'selected'
        assert state.next_slot_index == 1
        assert app.test_client().get('/api/stations/one/history').json['history'] == []
        assert automation.playback_started(first.id, 'two') is False
        assert automation.playback_started(first.id, 'one', now + timedelta(seconds=1)) is True
        assert automation.playback_started(first.id, 'one') is False
        assert len(app.test_client().get('/api/stations/one/history').json['history']) == 1
        second = automation.select_next('one', storage, now + timedelta(seconds=2))
        assert second.category.slug == 'medium'
        third = automation.select_next('one', storage, now + timedelta(seconds=3))
        assert third.category.slug == 'power' and third.track_id != first.track_id


def test_relaxation_empty_disabled_and_missing(setup):
    app, storage = setup
    with app.app_context():
        a, b, c = make_rotation(storage)
        b.artist = ' artist a '
        db.session.commit()
        now = datetime.now(timezone.utc)
        first = automation.select_next('one', storage, now)
        automation.playback_started(first.id, 'one', now)
        automation.select_next('one', storage, now + timedelta(seconds=1))
        third = automation.select_next('one', storage, now + timedelta(seconds=2))
        assert third.relaxation == 'artist' and third.track_id != first.track_id
        b.enabled = False
        db.session.commit()
        automation.select_next('one', storage, now + timedelta(seconds=3))
        fifth = automation.select_next('one', storage, now + timedelta(seconds=4))
        assert fifth.relaxation == 'track' and fifth.track_id == first.track_id
        # Missing files and disabled categories are skipped within a bounded slot cycle.
        storage.regular_file('one', a.storage_key).unlink()
        medium = automation.category_for('one', 'medium')
        medium.enabled = False
        db.session.commit()
        assert automation.select_next('one', storage, now + timedelta(seconds=5)) is None
        assert SelectionDecision.query.filter_by(reason='disabled_category').count() >= 1
        assert SelectionDecision.query.filter_by(reason='empty_category').count() >= 1


def test_api_sanitization_and_no_path_queueing(setup, monkeypatch):
    app, storage = setup
    with app.app_context():
        a, b, c = make_rotation(storage)
        decision = automation.select_next('one', storage)
        body = app.test_client().get('/api/stations/one/rotation').get_data(as_text=True)
        assert str(storage.root) not in body and 'password' not in body
        body = app.test_client().get('/api/stations/one/automation/status').get_data(as_text=True)
        assert '/run/freo' not in body
        from app.services import playout_queue
        with pytest.raises(ValueError):
            playout_queue._command('../one', 'freo_queue.queue')
        with pytest.raises(ValueError):
            playout_queue._command('one', 'help\nquit')
        with pytest.raises(ValueError, match='allowlisted'):
            playout_queue._command('one', 'server.shutdown')
        decision.track.station_id = automation.require_station('two').id
        db.session.flush()
        with pytest.raises(ValueError, match='not approved'):
            playout_queue.push_decision(decision, storage)
        db.session.rollback()


def test_no_eligible_tracks_do_not_spin_forever(setup):
    app, storage = setup
    with app.app_context():
        make_rotation(storage)
        for track in Track.query.all():
            track.enabled = False
        db.session.commit()
        assert automation.select_next('one', storage) is None
        assert SelectionDecision.query.count() == 2


def test_real_event_can_correct_failed_queue_record(setup):
    app, storage = setup
    with app.app_context():
        make_rotation(storage)
        decision = automation.select_next('one', storage)
        decision.status = 'failed'
        decision.reason = 'request_not_started'
        db.session.commit()
        assert automation.playback_started(decision.id, 'one')
        assert decision.status == 'started' and decision.reason == 'late_event_confirmation'


def test_worker_event_reader_rejects_untrusted_lines(monkeypatch, tmp_path):
    from app import automation_worker
    monkeypatch.setattr(automation_worker, 'EVENT_ROOT', tmp_path)
    event_dir = tmp_path / 'one'
    event_dir.mkdir()
    import time
    stamp = time.time()
    (event_dir / 'events.log').write_text(f'12 {stamp}\n../etc/passwd\nserver.shutdown\n13\n14 nan\n')
    seen = []
    monkeypatch.setattr(automation_worker, 'playback_started', lambda value, slug, started: seen.append((value, slug, started)) or True)
    reader = automation_worker.EventReader()
    assert reader.collect('one') == 2
    assert [(value, slug) for value, slug, _ in seen] == [(12, 'one'), (13, 'one')]
    assert abs(seen[0][2].timestamp() - stamp) < 0.001 and seen[1][2] is None
    assert reader.collect('one') == 0


def test_queue_reconciliation_marks_only_vanished_requests(setup, monkeypatch):
    app, storage = setup
    with app.app_context():
        make_rotation(storage)
        first = automation.select_next('one', storage)
        first.status = 'queued'
        first.liquidsoap_request_id = 10
        first.socket_identity = '1:2'
        second = automation.select_next('one', storage)
        second.status = 'queued'
        second.liquidsoap_request_id = 11
        second.socket_identity = '1:2'
        db.session.commit()
        from app import automation_worker
        monkeypatch.setattr(automation_worker, 'socket_identity', lambda slug: '1:2')
        monkeypatch.setattr(automation_worker, 'queued_ids', lambda slug: {11})
        monkeypatch.setattr(automation_worker, 'active_ids', lambda slug: set())
        assert automation_worker.reconcile_requests('one') == 1
        assert first.status == 'failed' and first.reason == 'request_not_started'
        assert second.status == 'queued'


def test_heartbeat_reports_stale_worker(setup):
    app, storage = setup
    with app.app_context():
        client = app.test_client()
        assert client.get('/health/automation').status_code == 503
        row = AutomationHeartbeat(id=1, seen_at=datetime.now(timezone.utc))
        db.session.add(row)
        db.session.commit()
        assert client.get('/health/automation').status_code == 200
        row.seen_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        db.session.commit()
        assert client.get('/health/automation').status_code == 503


def test_worker_refills_only_to_target_depth(setup, monkeypatch):
    app, storage = setup
    with app.app_context():
        make_rotation(storage)
        from app import automation_worker
        pushed = []
        monkeypatch.setattr(automation_worker, 'reconcile_requests', lambda slug: 0)
        monkeypatch.setattr(automation_worker, 'queue_depth', lambda slug: len(pushed))
        monkeypatch.setattr(automation_worker, 'select_next', lambda slug: automation.select_next(slug, storage))
        monkeypatch.setattr(automation_worker, 'push_decision', lambda decision: pushed.append(decision.id) or len(pushed))
        monkeypatch.setattr(automation_worker, 'socket_identity', lambda slug: '1:2')
        reader = automation_worker.EventReader()
        monkeypatch.setattr(reader, 'collect', lambda slug: 0)
        assert automation_worker.refill_station('one', reader, target_depth=2) == 2
        assert len(pushed) == 2
        assert automation_worker.refill_station('one', reader, target_depth=2) == 0


def test_disabled_empty_slot_does_not_block_activation(setup):
    app, storage = setup
    with app.app_context():
        make_rotation(storage)
        empty = automation.category_create('one', 'Empty', 'empty')
        slot = automation.add_slot('one', 'main', 'empty')
        slot.enabled = False
        empty.enabled = False
        db.session.commit()
        automation.activate('one', 'main')
        assert automation.require_station('one').automation.active_rotation.slug == 'main'
