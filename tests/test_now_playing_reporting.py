"""Latest-state sharing is independent of audio, hourly telemetry and consent sync."""
from datetime import datetime, timezone
import json
import time
from uuid import uuid4

import pytest
from app.extensions import db
from app.models import LiveQueueSnapshot, SelectionDecision, Station, Track
from app.services.central_api import Reporter, installation
from app.services.central_api.client import APIError
from app.services.central_api.now_playing import playback, batches, text
from tests.test_central_api import app, central, iso


@pytest.fixture
def sharing(central, monkeypatch):
    reporter, api = central
    clock = [float(int(time.time()))]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    api.revision = '2026-10-v1.1'
    api.sharing_revision = '2026-10-v1'
    base_factory = api.factory
    def factory(url, token=None):
        conn = base_factory(url, token)
        conn.now_playing_revision = api.sharing_revision
        original = conn.request
        def request(method, path, payload=None):
            if path != '/v1/now-playing':
                return original(method, path, payload)
            api.calls.append((method, path, payload, token))
            assert token == api.token
            if path in api.fail:
                raise api.fail[path]
            return dict(server_time=iso(clock[0]), stations_accepted=len(payload['stations']),
                        stations_updated=len(payload['stations']), next_report_seconds=60)
        conn.request = request
        return conn
    api.factory = reporter.client_factory = factory
    monkeypatch.setattr('app.services.broadcast_status.observation', lambda slug: (True, 2))
    reporter.tick()
    station = Station.query.order_by(Station.id).first()
    decision = SelectionDecision.query.filter_by(station_id=station.id, status='started').first()
    snapshot = LiveQueueSnapshot(station_id=station.id, current_decision_id=decision.id,
        observed_at=datetime.fromtimestamp(clock[0], timezone.utc), queued_decision_ids=[], mixer={})
    db.session.add(snapshot)
    db.session.commit()
    yield reporter, api, clock, station, snapshot


def reports(api):
    return [payload['stations'] for _, path, payload, _ in api.calls if path == '/v1/now-playing']


def refresh(snapshot, clock, seconds=5):
    clock[0] += seconds
    snapshot.observed_at = datetime.fromtimestamp(clock[0], timezone.utc)
    db.session.commit()


def test_changed_song_long_tracks_sampling_time_and_hourly_independence(sharing):
    reporter, api, clock, station, snapshot = sharing
    before = installation().state['last_heartbeat']
    budget = installation().state['budget']
    reporter.fast_tick()
    first = reports(api)[-1][0]
    assert first['title'] == 'Verified Test Track' and first['artist'] == 'Test Artist'
    assert first['observed_at'] == iso(clock[0])
    refresh(snapshot, clock)
    reporter.fast_tick()
    assert len(reports(api)) == 1
    track = db.session.get(SelectionDecision, snapshot.current_decision_id).track
    track.title = 'New title'
    db.session.commit()
    reporter.fast_tick()
    assert reports(api)[-1][0]['title'] == 'New title'
    refresh(snapshot, clock, 55)
    reporter.fast_tick()
    assert len(reports(api)) == 3
    assert installation().state['last_heartbeat'] == before
    assert installation().state['budget'] == budget
    assert 'New title' not in json.dumps(installation().state['now_playing'])


def test_offair_unknown_and_microphone_never_send_stale_song(sharing, monkeypatch):
    reporter, api, clock, station, snapshot = sharing
    snapshot.show_observation = dict(source='MIC', observed_at=iso(clock[0]))
    db.session.commit()
    reporter.fast_tick()
    assert reports(api)[-1][0]['title'] is None
    monkeypatch.setattr('app.services.broadcast_status.observation', lambda slug: (False, 0))
    refresh(snapshot, clock)
    reporter.fast_tick()
    assert all(not entry['on_air'] and entry['title'] is None for entry in reports(api)[-1])
    monkeypatch.setattr('app.services.broadcast_status.observation', lambda slug: (None, None))
    refresh(snapshot, clock, 60)
    reporter.fast_tick()
    assert len(reports(api)) == 2


def test_optout_syncs_promptly_retries_withdrawal_and_stays_private_on_restart(sharing):
    reporter, api, clock, station, snapshot = sharing
    reporter.fast_tick()
    station.directory_opt_in = False
    db.session.commit()
    api.fail['/v1/stations/sync'] = APIError('http_503', status=503, retry_after=20)
    refresh(snapshot, clock)
    reporter.fast_tick()
    assert len(reports(api)) == 1
    assert installation().state['directory_sync']['error'] == 'http_503'
    del api.fail['/v1/stations/sync']
    restarted = Reporter(api.factory)
    refresh(snapshot, clock, 25)
    restarted.fast_tick()
    syncs = [payload for _, path, payload, _ in api.calls if path == '/v1/stations/sync']
    withdrawn = next(s for s in syncs[-1]['stations'] if s['station_id'] == station.freo_station_id)
    assert withdrawn['directory_opt_in'] is False
    assert all(s['station_id'] != station.freo_station_id for s in reports(api)[-1])


def test_fresh_retry_and_retry_after_not_backlog(sharing):
    reporter, api, clock, station, snapshot = sharing
    api.fail['/v1/now-playing'] = APIError('http_429', status=429, retry_after=35)
    reporter.fast_tick()
    due = installation().state['now_playing']['due']
    track = db.session.get(SelectionDecision, snapshot.current_decision_id).track
    track.title = 'Latest song during outage'
    db.session.commit()
    del api.fail['/v1/now-playing']
    refresh(snapshot, clock, 30)
    reporter.fast_tick()
    assert len(reports(api)) == 1
    assert due >= clock[0] + 5
    refresh(snapshot, clock, 10)
    reporter.fast_tick()
    assert reports(api)[-1][0]['title'] == track.title
    assert reports(api)[-1][0]['observed_at'] == iso(clock[0])


@pytest.mark.parametrize('code', ['station_not_synced', 'directory_not_enabled'])
def test_conflicts_reconcile_before_reporting_again(sharing, code):
    reporter, api, clock, station, snapshot = sharing
    api.fail['/v1/now-playing'] = APIError(code, status=409)
    reporter.fast_tick()
    del api.fail['/v1/now-playing']
    refresh(snapshot, clock, 65)
    reporter.fast_tick()
    paths = [path for _, path, _, _ in api.calls]
    last_report = len(paths) - 1 - paths[::-1].index('/v1/now-playing')
    assert paths[last_report - 1] == '/v1/stations/sync'
    assert len(reports(api)) == 2


@pytest.mark.parametrize('revision', [None, 'future-unsupported'])
def test_missing_capability_keeps_sync_and_hourly_reporting(sharing, revision):
    reporter, api, clock, station, snapshot = sharing
    api.sharing_revision = revision
    restarted = Reporter(api.factory)
    restarted.fast_tick()
    assert not reports(api)
    assert installation().state['last_heartbeat']
    station.directory_opt_in = False
    db.session.commit()
    restarted.fast_tick()
    assert [p for _, path, p, _ in api.calls if path == '/v1/stations/sync'][-1]['stations'][0]['directory_opt_in'] is False


@pytest.mark.parametrize('status', [401, 404, 405])
def test_rejections_preserve_identity_credentials_and_playout(sharing, status):
    reporter, api, clock, station, snapshot = sharing
    before = reporter.store.read()
    api.fail['/v1/now-playing'] = APIError('http_' + str(status), status=status)
    reporter.fast_tick()
    assert reporter.store.read() == before
    assert station.desired_state == 'running'
    if status == 401:
        assert installation().registration_state == 'credentials_rejected'
    else:
        assert not reporter.now_playing_supported
    refresh(snapshot, clock, 5)
    reporter.fast_tick()
    assert len(reports(api)) == 1


def test_restart_resends_and_explicit_optout_stays_private(sharing):
    reporter, api, clock, station, snapshot = sharing
    second = Station.query.order_by(Station.id).all()[1]
    second.directory_opt_in = False
    db.session.commit()
    reporter.fast_tick()
    refresh(snapshot, clock)
    Reporter(api.factory).fast_tick()
    assert len(reports(api)) == 2
    assert all(len(batch) == 1 for batch in reports(api))


def test_previews_queued_tracks_and_stale_snapshots_are_not_published(sharing):
    reporter, api, clock, station, snapshot = sharing
    snapshot.current_decision_id = None
    snapshot.queued_decision_ids = [SelectionDecision.query.first().id]
    db.session.commit()
    assert playback(station, clock[0])['title'] is None
    snapshot.current_decision_id = SelectionDecision.query.first().id
    snapshot.observed_at = datetime.fromtimestamp(clock[0] - 20, timezone.utc)
    db.session.commit()
    assert playback(station, clock[0])['title'] is None


def test_batch_limits_and_metadata_normalization():
    entry = dict(station_id=str(uuid4()), on_air=True, title='😀' * 500, artist='歌' * 500,
                 observed_at=iso(time.time()))
    result = list(batches([dict(entry, station_id=str(uuid4())) for _ in range(205)]))
    assert sum(map(len, result)) == 205 and all(len(b) <= 100 for b in result)
    assert all(len(json.dumps({'stations': b}, separators=(',', ':')).encode()) <= 256 * 1024 for b in result)
    assert text(' \x00\n Artist\t ') == 'Artist'
    assert text('  ') is None and text(None) is None and len(text('x' * 501)) == 500


def test_relay_and_dj_crossfade_use_confirmed_audible_source(sharing):
    from app.models import StationRelay
    reporter, api, clock, station, snapshot = sharing
    row = SelectionDecision.query.first()
    snapshot.mixer = dict(mode='DJ_BOOTH', a_id=row.id, a_playing=False, b_id=None, crossfader=0)
    db.session.commit()
    assert playback(station, clock[0])['title'] is None  # Previewed/paused deck.
    snapshot.mixer = dict(mode='DJ_BOOTH', a_id=row.id, a_playing=True, b_id=None,
                          transition={'a_gain': 0, 'b_gain': 1})
    db.session.commit()
    assert playback(station, clock[0])['title'] is None
    station.relay = StationRelay(enabled=True, revision=1, applied_revision=1,
        observed_at=datetime.fromtimestamp(clock[0], timezone.utc),
        observation=dict(source='relay', title='Actual upstream', artist='Upstream artist'))
    db.session.commit()
    assert playback(station, clock[0])['title'] == 'Actual upstream'


def test_unrelated_legacy_settings_submission_preserves_consent(app):
    from tests.test_central_api import admin_client
    with app.app_context():
        Station.query.first().directory_opt_in = True
        db.session.commit()
    client = admin_client(app)
    # Explicit marker distinguishes an unchecked checkbox from old partial clients.
    csrf = 'test-admin-csrf-token'
    response = client.post('/admin/stations/test-station/settings', data=dict(csrf=csrf,
        name='Test Station', public_slug='test-station', timezone='UTC'))
    assert response.status_code == 302
    with app.app_context():
        assert Station.query.first().directory_opt_in


def test_optional_endpoint_rejection_does_not_defer_hourly_reporting(sharing):
    reporter, api, clock, station, snapshot = sharing
    api.fail['/v1/now-playing'] = APIError('http_404', status=404)
    reporter.fast_tick()
    row = installation()
    reporter.save_state(row, report={'due': clock[0] + 1}, license={'due': clock[0] + 1})
    refresh(snapshot, clock, 5)
    before = sum(path == '/v1/heartbeat' for _, path, _, _ in api.calls)
    outcome = reporter.tick()
    assert outcome['heartbeat']
    assert sum(path == '/v1/heartbeat' for _, path, _, _ in api.calls) == before + 1


def test_cached_rc15_full_settings_form_can_still_explicitly_opt_out(app):
    import re
    from tests.test_web import admin_client
    client = admin_client(app)
    page = client.get('/admin/stations/test-station/settings')
    token = re.search(r'name="settings_token" value="([^"]+)"', page.text)[1]
    response = client.post('/admin/stations/test-station/settings', data=dict(
        csrf='test-admin-csrf-token', combined='yes', settings_token=token,
        name='Test Station', public_slug='test-station', timezone='UTC'))
    assert response.status_code == 302
    with app.app_context():
        station = Station.query.first()
        assert not station.directory_opt_in and station.directory_consent_source == 'explicit'
