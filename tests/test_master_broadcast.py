"""Master intent, privileged application, and shared observed status."""
import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from app.extensions import db
from app.models import Station, LiveQueueSnapshot, StatsState, LiveControlCommand, ScheduleTransition, AdminUser, AutomationState
from app.services import station_runtime as runtime
from app.services.master_broadcast import process_broadcast
from app.services.broadcast_status import cached_status
from tests.test_web import app, admin_client

BASE = '/admin/stations/test-station/schedule-studio/api/'


def change(client, enabled, revision=1):
    return client.post(BASE + 'broadcast', data={'csrf': 'test-admin-csrf-token',
        'payload': json.dumps(dict(enabled=enabled, revision=revision))})


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(runtime, 'require_root', lambda: None)
    monkeypatch.setattr(runtime, 'operation_lock', nullcontext)
    service = Mock(return_value=False)
    monkeypatch.setattr(runtime, 'service_action', service)
    monkeypatch.setattr(runtime, 'wait_audio_online', Mock())
    return service


def test_master_is_durable_scoped_and_worker_applied(app, worker):
    client = admin_client(app)
    result = change(client, False)
    assert result.status_code == 200
    assert result.json['broadcast']['status'] == 'pending'
    assert result.json['broadcast']['enabled'] is False
    worker.assert_not_called()
    assert change(client, True).status_code == 400  # Stale tab cannot undo OFF.
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        process_broadcast(station)
        assert station.desired_state == 'stopped' and station.broadcast_status == 'ready'
        assert Station.query.filter_by(slug='second-station').one().desired_state == 'stopped'
        worker.assert_any_call('test-station', 'stop')
    assert change(client, True, 2).status_code == 200
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        process_broadcast(station)
        assert station.desired_state == 'running' and station.broadcast_status == 'ready'
        runtime.wait_audio_online.assert_called_once_with(station)
    assert {call.args[0] for call in worker.call_args_list} == {'test-station'}


def test_master_auth_csrf_validation_and_playout_permission(app, monkeypatch):
    assert change(app.test_client(), False).status_code == 302
    client = admin_client(app)
    assert client.post(BASE + 'broadcast').status_code == 400
    assert change(client, 'false').status_code == 400
    assert change(client, False, True).status_code == 400
    monkeypatch.setattr('app.routes.schedule_studio.can_control_playout', lambda *args: False)
    assert change(client, False).status_code == 403


def test_master_start_failure_and_retry(app, worker):
    client = admin_client(app)
    change(client, True)
    worker.side_effect = RuntimeError('secret runtime detail')
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        process_broadcast(station)
        assert station.broadcast_status == 'failed'
        assert 'secret' not in station.broadcast_error
    worker.side_effect = None
    assert change(client, True, 2).status_code == 200
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        process_broadcast(station)
        assert station.broadcast_status == 'ready'


def test_off_cancels_commands_and_blocks_live_controls(app):
    from uuid import uuid4
    client = admin_client(app)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        db.session.add(LiveControlCommand(station_id=station.id, idempotency_key=str(uuid4()), action='DECK_PLAY'))
        db.session.add(ScheduleTransition(id=str(uuid4()), station_id=station.id,
            mode='SIMPLE', previous_mode='CALENDAR', revision=1))
        db.session.commit()
    assert change(client, False).status_code == 200
    with app.app_context():
        assert LiveControlCommand.query.one().status == 'failed'
        assert ScheduleTransition.query.one().state == 'FAILED'
        from app.services.live_assist import set_mode
        with pytest.raises(ValueError, match='unavailable'):
            set_mode(Station.query.filter_by(slug='test-station').one(), AdminUser.query.first(), 'DJ_BOOTH')
    response = client.post('/admin/api/stations/test-station/live-mic/go', data={'csrf': 'test-admin-csrf-token'})
    assert response.status_code == 409


def test_empty_station_can_start_and_get_worker_observations(app):
    client = admin_client(app)
    with app.app_context():
        AutomationState.query.delete()
        db.session.commit()
    assert change(client, True).status_code == 200
    with app.app_context():
        state = AutomationState.query.one()
        assert state.station.slug == 'test-station'
        assert not state.enabled  # No saved programming was invented.


def test_new_off_request_survives_inflight_start(app, worker, monkeypatch):
    client = admin_client(app)
    change(client, True)
    def newer_request(station):
        station.desired_state = 'stopped'
        station.broadcast_revision += 1
        station.broadcast_status = 'pending'
        db.session.commit()
    monkeypatch.setattr(runtime, 'wait_audio_online', newer_request)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        process_broadcast(station)
        assert station.broadcast_status == 'pending' and station.desired_state == 'stopped'
        process_broadcast(station)
        worker.assert_any_call(station.slug, 'stop')
        assert station.broadcast_status == 'ready'


def test_status_uses_newest_observation_and_expires(app):
    now = datetime.now(timezone.utc)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        # Desired OFF must not hide an actually online stream while stopping.
        station.desired_state = 'stopped'
        db.session.add(StatsState(scope=station.id, data=dict(at=now.timestamp()-5, online=False)))
        db.session.add(LiveQueueSnapshot(station_id=station.id, observed_at=now,
            broadcast_observed_at=now, broadcast_online=True, mixer={'tone': True}))
        db.session.commit()
        data = cached_status([station], now.timestamp())[station.slug]
        assert data['online'] and data['tone'] and not data['enabled']
        assert cached_status([station], (now+timedelta(seconds=60)).timestamp())[station.slug]['online'] is None
    client = admin_client(app)
    shared = client.get('/admin/api/broadcast-status')
    assert shared.headers['Cache-Control'] == 'private, no-store'
    assert shared.json['stations']['test-station']['online'] is True
    assert client.get(BASE+'state').json['broadcast']['tone'] is True
    assert client.get('/admin/api/operations').json['stations']['test-station']['status'] == 'On air'


def test_all_admin_pages_have_each_station_monitor(app):
    client = admin_client(app)
    for path in ('/admin', '/admin/stations/test-station/schedule-studio/control'):
        html = client.get(path).text
        assert html.count('data-station-monitor-toggle') == 2
        assert 'data-monitor-station="test-station"' in html
        assert 'data-monitor-station="second-station"' in html
    html = client.get('/admin').text
    assert html.count('data-broadcast-station="test-station"') == 2


def test_master_migration_roundtrip(app):
    runner = app.test_cli_runner()
    # The fixture already has the current schema. Round-trip this migration
    # alone instead of reapplying later Cue/audio tables that still exist.
    for args in [('db', 'stamp', 'f19a73b206ce'), ('db', 'downgrade', 'e92b740a613f'), ('db', 'upgrade', 'f19a73b206ce')]:
        result = runner.invoke(args=args)
        assert result.exit_code == 0, result.output
    with app.app_context():
        db.session.remove()
        station = Station.query.filter_by(slug='test-station').one()
        assert station.desired_state == 'running'
        assert station.broadcast_status == 'ready' and station.broadcast_revision == 1
