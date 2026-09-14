"""Live Assist intent and socket boundary regressions."""
import uuid

import pytest

from app.extensions import db
from app.models import AdminUser, AuditEvent, AutomationState, LiveQueueSnapshot, SelectionDecision, Station, Track
from app.services.live_assist import queue_playable, request_skip, set_hold
from app.services.playout_queue import _command
from tests.test_web import app as app_fixture, admin_client


@pytest.fixture
def app(app_fixture):
    return app_fixture


def test_live_auth_csrf_and_idor(app):
    anonymous = app.test_client()
    base = '/admin/stations/test-station/live'
    assert anonymous.get(base).status_code == 302
    assert anonymous.get('/admin/api/stations/test-station/live-status').status_code == 302
    assert anonymous.post(base + '/hold').status_code == 302
    client = admin_client(app)
    assert client.post(base + '/hold').status_code == 400
    assert client.get(base + '/hold').status_code in (404, 405)
    nonce = str(uuid.uuid4())
    assert client.post('/admin/stations/second-station/live/queue-track', data={
        'csrf':'test-admin-csrf-token','identifier':'00000000-0000-4000-8000-000000000001','nonce':nonce}).status_code == 302
    with app.app_context():
        assert SelectionDecision.query.filter_by(idempotency_key=nonce).first() is None
    assert client.post(base + '/queue-track', data={'csrf':'test-admin-csrf-token',
        'identifier':'/etc/passwd','nonce':str(uuid.uuid4())}).status_code == 302
    assert client.post(base + '/skip', data={'csrf':'test-admin-csrf-token',
        'expected_decision_id':'../../socket','nonce':str(uuid.uuid4())}).status_code == 302


def test_hold_resume_and_audit(app):
    client = admin_client(app)
    base = '/admin/stations/test-station/live'
    assert client.post(base + '/hold', data={'csrf':'test-admin-csrf-token'}).status_code == 302
    with app.app_context():
        assert AutomationState.query.first().hold is True
        assert AuditEvent.query.filter_by(action='automation_held').count() == 1
    assert client.post(base + '/resume', data={'csrf':'test-admin-csrf-token'}).status_code == 302
    with app.app_context():
        assert AutomationState.query.first().hold is False
        assert AuditEvent.query.filter_by(action='automation_resumed').count() == 1


def test_manual_request_idempotency_station_scope_and_limit(app, monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda self, slug, key: '/safe')
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        user = AdminUser.query.first()
        token = str(uuid.uuid4())
        identifier = Track.query.first().uuid
        first = queue_playable(station, user, 'track', identifier, token)
        assert queue_playable(station, user, 'track', identifier, token).id == first.id
        assert first.selection_method == 'manual_track' and first.status == 'selected'
        assert first.track_id and first.admin_user_id == user.id
        with pytest.raises(ValueError):
            queue_playable(station, user, 'track', 'wrong', token)
        other = Station.query.filter_by(slug='second-station').first()
        with pytest.raises(ValueError):
            queue_playable(other, user, 'track', identifier, str(uuid.uuid4()))
        with pytest.raises(ValueError):
            queue_playable(station, user, 'track', identifier, 'bad-token')


def test_skip_intent_is_bound_to_current_decision(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        user = AdminUser.query.first()
        current = SelectionDecision.query.filter_by(status='started').first()
        token = str(uuid.uuid4())
        row = request_skip(station, user, current.id, token)
        assert row.status == 'pending'
        assert request_skip(station, user, current.id, token).id == row.id
        with pytest.raises(ValueError):
            request_skip(station, user, 99999, str(uuid.uuid4()))


def test_socket_adapter_rejects_generic_control():
    for command in ('freo_queue.flush_and_skip', 'freo_queue.push /etc/passwd',
                    'system.shutdown', 'freo_queue.skip\nrequest.on_air'):
        with pytest.raises(ValueError):
            _command('test-station', command)


def test_live_page_and_status_use_sanitized_worker_snapshot(app, monkeypatch):
    monkeypatch.setattr('app.services.playout_queue._command', lambda *args: (_ for _ in ()).throw(AssertionError('web socket access')))
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        decision = SelectionDecision.query.filter_by(status='started').first()
        db.session.add(LiveQueueSnapshot(station_id=station.id, current_decision_id=decision.id,
            queued_decision_ids=[], unknown_count=0, observed_at=decision.started_at))
        # Refresh observed time to avoid stale state.
        from datetime import datetime, timezone
        db.session.get(LiveQueueSnapshot, station.id).observed_at = datetime.now(timezone.utc)
        db.session.commit()
    client = admin_client(app)
    page = client.get('/admin/stations/test-station/live')
    assert page.status_code == 200
    assert b'Live Assist' in page.data and b'Verified Test Track' in page.data
    payload = client.get('/admin/api/stations/test-station/live-status')
    assert payload.status_code == 200
    assert payload.json['current']['title'] == 'Verified Test Track'
    assert 'internal.mp3' not in payload.get_data(as_text=True)
    assert 'password' not in payload.get_data(as_text=True)


def test_worker_processes_manual_while_held_and_observes_real_order(app, monkeypatch):
    from app.automation_worker import EventReader, process_manual, observe_queue
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda self, slug, key: '/safe')
    monkeypatch.setattr('app.automation_worker.socket_identity', lambda slug: 'socket-1')
    monkeypatch.setattr('app.automation_worker.queued_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.active_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.queue_depth', lambda slug: 0)
    monkeypatch.setattr('app.automation_worker.push_decision', lambda decision: 37)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        user = AdminUser.query.first()
        station.automation.hold = True
        db.session.commit()
        row = queue_playable(station, user, 'track', Track.query.first().uuid, str(uuid.uuid4()))
        monkeypatch.setattr('app.automation_worker.reconcile_requests', lambda slug: 0)
        process_manual(station, EventReader())
        assert row.status == 'queued' and row.liquidsoap_request_id == 37
        monkeypatch.setattr('app.automation_worker.queued_order', lambda slug: [37])
        observe_queue(station)
        snapshot = db.session.get(LiveQueueSnapshot, station.id)
        assert snapshot.queued_decision_ids == [row.id]
        assert snapshot.current_decision_id is None


def test_manual_queue_limit(app, monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda self, slug, key: '/safe')
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        user = AdminUser.query.first()
        track = Track.query.first()
        for index in range(20):
            db.session.add(SelectionDecision(station_id=station.id, track_id=track.id, status='queued',
                selection_method='manual_track', admin_user_id=user.id, idempotency_key=str(uuid.uuid4())))
        db.session.commit()
        with pytest.raises(ValueError, match='full'):
            queue_playable(station, user, 'track', track.uuid, str(uuid.uuid4()))


def test_worker_skip_requires_same_observed_request(app, monkeypatch):
    from app.automation_worker import EventReader, process_manual
    from app.models import LiveControlCommand
    calls = []
    monkeypatch.setattr('app.automation_worker.socket_identity', lambda slug: 'socket-1')
    monkeypatch.setattr('app.automation_worker.queued_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.active_ids', lambda slug: {45})
    monkeypatch.setattr('app.automation_worker.reconcile_requests', lambda slug: 0)
    monkeypatch.setattr('app.automation_worker.skip_current', lambda slug: calls.append(slug))
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        user = AdminUser.query.first()
        current = SelectionDecision.query.filter_by(status='started').first()
        current.socket_identity = 'socket-1'
        current.liquidsoap_request_id = 45
        db.session.commit()
        command = request_skip(station, user, current.id, str(uuid.uuid4()))
        process_manual(station, EventReader())
        assert command.status == 'sent' and calls == ['test-station']
        current.liquidsoap_request_id = 46
        db.session.commit()
        stale = request_skip(station, user, current.id, str(uuid.uuid4()))
        process_manual(station, EventReader())
        assert stale.status == 'failed' and stale.error_code == 'current_changed'
        assert calls == ['test-station']


def test_confirmed_manual_music_start_affects_automation_separation():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services.automation import _choose
    now = datetime.now(timezone.utc)
    manual = SimpleNamespace(id=1, artist='Manual Artist')
    same_artist = SimpleNamespace(id=2, artist='Manual Artist')
    other = SimpleNamespace(id=3, artist='Other Artist')
    history = [SimpleNamespace(track=manual, track_id=manual.id, status='started',
        selection_method='manual_track', started_at=now, selected_at=now)]
    chosen, relaxation, _ = _choose([manual, same_artist, other], history, now, 300, 300)
    assert chosen is other and relaxation == 'none'
