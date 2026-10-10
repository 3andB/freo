"""Listener requests use normal selection, confirmed history and scoped access."""
from datetime import datetime, timedelta, timezone
import importlib.util
import uuid
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.extensions import db
from app import models as m
from app.services import listener_requests as r
from app.services.automation import select_next, playback_started
from app.services.media_storage import LocalMediaStorage
from app.services import playlists
from app.services.visual_schedule import select_visual
from tests.test_web import app, admin_client
from tests.test_playlists import setup_playlist, program
from tests.test_phase3_dj import dj_client

AT = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)
API = '/api/stations/test-station/requests'
ADMIN = '/admin/stations/test-station/requests'


@pytest.fixture(autouse=True)
def audio(monkeypatch):
    monkeypatch.setattr(LocalMediaStorage, 'regular_file', lambda *args: '/safe')


def setup(**settings):
    station, playlist, tracks = setup_playlist()
    m.SelectionDecision.query.delete()
    station.request_settings = dict(r.DEFAULTS, enabled=True, cooldown_minutes=0, **settings)
    station.automation.track_separation_seconds = station.automation.artist_separation_seconds = 0
    db.session.commit()
    return station, playlist, tracks


def submit(station, track, key='listener', at=AT):
    row = r.submit(station, track.uuid, key, str(uuid.uuid4()), at)
    db.session.commit()
    return row


def start(station, track, at, **kwargs):
    row = m.SelectionDecision(station_id=station.id, track=track, status='started', started_at=at, selected_at=at, **kwargs)
    db.session.add(row); db.session.flush()
    return row


def test_delay_counts_only_confirmed_music_after_submission(app):
    with app.app_context():
        station, playlist, tracks = setup()
        start(station, tracks[0], AT - timedelta(seconds=1))
        req = submit(station, tracks[0])
        pending = m.SelectionDecision(station_id=station.id, track=tracks[1], status='queued', selected_at=AT)
        db.session.add(pending); db.session.flush()
        assert '3 more' in r.reason(req, station, tracks, AT + timedelta(seconds=1))
        start(station, tracks[1], AT + timedelta(seconds=1), playback_bus='CART')
        assert '3 more' in r.reason(req, station, tracks, AT + timedelta(seconds=2))
        pending.status = 'failed'
        for i in range(3): start(station, tracks[1], AT + timedelta(seconds=i+1))
        assert r.reason(req, station, tracks, AT + timedelta(seconds=5)) == 'Waiting for track separation'
        for i in range(7): start(station, tracks[2], AT + timedelta(seconds=i+6))
        assert r.reason(req, station, tracks, AT + timedelta(seconds=15)) == ''


@pytest.mark.parametrize('path', ['playlist', 'visual', 'category'])
def test_priority_binding_cursor_preservation_and_confirmed_start(app, path):
    with app.app_context():
        station, playlist, tracks = setup(delay_songs=0)
        req = submit(station, tracks[-1])
        if path == 'playlist':
            program(station, playlist, AT); db.session.commit()
            decision = select_next(station.slug, now=AT)
            assert m.PlaylistCursor.query.one().state == {}
        elif path == 'visual':
            decision = select_visual(station, dict(source=dict(kind='playlist', id=playlist.id), key='show:block:section'), LocalMediaStorage(), AT)
            db.session.commit()
            assert m.ScheduleCursor.query.one().state == {}
        else:
            station.request_settings = dict(station.request_settings, restrict_programming=False)
            db.session.commit()
            decision = select_next(station.slug, now=AT)
        assert decision.track_id == req.track_id and decision.listener_request_id == req.id
        assert req.status == 'queued' and req.played_at is None
        assert playback_started(decision.id, station.slug, AT + timedelta(seconds=1))
        assert req.status == 'played' and req.played_at is not None
        assert not playback_started(decision.id, station.slug, AT + timedelta(seconds=2))


def test_programming_restriction_waits_then_unrestricted_uses_music_slot(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0)
        req = submit(station, tracks[2])
        normal = select_next(station.slug, now=AT)
        assert normal.listener_request_id is None and req.status == 'pending'
        normal.status = 'failed'
        station.request_settings = dict(station.request_settings, restrict_programming=False)
        db.session.commit()
        assert select_next(station.slug, now=AT).listener_request_id == req.id


def test_strict_time_separation_and_current_track_never_relax(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0, track_songs=0, artist_songs=0)
        req = submit(station, tracks[0]); station.automation.track_separation_seconds = 60
        start(station, tracks[0], AT - timedelta(seconds=30)); start(station, tracks[1], AT - timedelta(seconds=1))
        assert 'automation separation' in r.reason(req, station, tracks, AT)
        assert r.reason(req, station, tracks, AT + timedelta(seconds=30)) == ''
        start(station, tracks[0], AT + timedelta(seconds=31))
        assert 'track separation' in r.reason(req, station, tracks, AT + timedelta(seconds=100))


def test_artist_normalization_pending_reservation_and_cross_station_history(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0, artist_songs=2)
        tracks[1].artist = '  TEST   ARTIST '
        req = submit(station, tracks[0])
        start(station, tracks[1], AT - timedelta(seconds=2)); start(station, tracks[2], AT - timedelta(seconds=1))
        assert 'artist separation' in r.reason(req, station, tracks, AT)
        start(station, tracks[2], AT)
        assert not r.reason(req, station, tracks, AT)
        db.session.add(m.SelectionDecision(station_id=station.id, track=tracks[1], status='queued', selected_at=AT)); db.session.flush()
        assert 'queued song' in r.reason(req, station, tracks, AT)


@pytest.mark.parametrize('fixed', ['insert', 'song', 'leader', 'live'])
def test_fixed_programming_and_live_show_do_not_select_requests(app, fixed):
    with app.app_context():
        station, playlist, tracks = setup(delay_songs=0, restrict_programming=False)
        req = submit(station, tracks[2])
        resolved = dict(source=dict(kind='playlist', id=playlist.id), key='fixed')
        if fixed == 'insert': resolved['insert'] = True
        if fixed == 'song': resolved['source'] = dict(kind='song', id=tracks[0].id)
        if fixed == 'leader': playlist.leader_track = tracks[0]
        if fixed == 'live': station.automation.operator_mode = 'DJ_BOOTH'
        db.session.commit()
        decision = select_visual(station, resolved, LocalMediaStorage(), AT)
        assert decision.listener_request_id is None and req.status == 'pending'


def test_disabled_and_empty_requests_preserve_selection(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0)
        req = submit(station, tracks[0]); station.request_settings = dict(station.request_settings, enabled=False); db.session.commit()
        decision = select_next(station.slug, now=AT)
        assert decision.track_id == tracks[0].id and decision.listener_request_id is None
        assert req.status == 'pending'


def test_expiry_retry_and_uncertain_attempt_not_retried(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0)
        req = submit(station, tracks[0]); decision = select_next(station.slug, now=AT)
        decision.status, decision.reason = 'failed', 'queue_failed'; db.session.commit()
        r.maintain(station, AT + timedelta(seconds=1)); assert req.status == 'queued'
        decision.reason = 'request_not_started'; db.session.commit()
        r.maintain(station, AT + timedelta(seconds=1)); assert req.status == 'pending'
        r.maintain(station, AT + timedelta(hours=24)); assert req.status == 'expired'
        assert req.listener_key is None
        assert playback_started(decision.id, station.slug, AT + timedelta(hours=24))
        assert req.status == 'played'


def test_limits_duplicate_and_submission_nonce(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0, listener_limit=1, station_limit=2)
        req = submit(station, tracks[0]); assert submit(station, tracks[0]).id == req.id
        with pytest.raises(ValueError, match='maximum'): submit(station, tracks[1])
        submit(station, tracks[1], 'other')
        with pytest.raises(ValueError, match='full'): submit(station, tracks[2], 'third')
        assert r.submit(station, tracks[1].uuid, 'listener', req.nonce, AT).id == req.id


def test_public_catalog_submission_metadata_origin_token_and_rate_limits(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0); target = tracks[0].uuid
    client = app.test_client()
    response = client.get(API)
    assert response.status_code == 200
    assert set(response.json['tracks'][0]) == {'uuid', 'title', 'artist'}
    assert 'storage' not in response.text and 'internal.mp3' not in response.text
    headers = {'X-Request-Token': response.json['token']}
    data = dict(track=target, nonce=str(uuid.uuid4()))
    assert client.post(API, json=data).status_code == 400
    assert client.post(API, json=data, headers=dict(headers, Origin='https://evil.test')).status_code == 403
    assert client.post(API, json=data, headers=headers).status_code == 202
    assert client.post(API, json=data, headers=headers).status_code == 202
    with app.app_context(): assert m.ListenerRequest.query.count() == 1
    for _ in range(26): client.post(API, json=data, headers=headers)
    limited = client.post(API, json=data, headers=headers)
    assert limited.status_code == 429 and limited.headers['Retry-After'] == '60'
    assert "frame-ancestors *" in client.get('/requests/test-station').headers['Content-Security-Policy']


def test_admin_dj_scope_reject_and_disabled_public(app, dj_client):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0)
        req = submit(station, tracks[0], at=datetime.now(timezone.utc)); identifier = req.id
    client = admin_client(app)
    assert client.get(ADMIN).status_code == 200
    assert dj_client.get(ADMIN).status_code == 200
    assert dj_client.get('/admin/stations/second-station/requests').status_code == 403
    assert dj_client.post(f'{ADMIN}/{identifier}/reject', data={'csrf': 'dj-csrf'}).status_code == 403
    assert client.post(f'{ADMIN}/{identifier}/reject', data={'csrf': 'test-admin-csrf-token'}).status_code == 303
    with app.app_context():
        assert db.session.get(m.ListenerRequest, identifier).status == 'rejected'
        station = m.Station.query.first(); station.request_settings = {}; db.session.commit()
    assert app.test_client().get(API).status_code == 403
    assert 'currently disabled' in app.test_client().get('/requests/test-station').text


def test_settings_validation_and_stale_token(app):
    from app.routes.station_settings import settings_token
    with app.app_context():
        station, _, _ = setup(); before = settings_token(station)
        form = dict(requests_present='yes', request_enabled='yes', request_restrict_programming='yes', **{'request_'+key: str(r.DEFAULTS[key]) for key, *_ in r.FIELDS})
        form['request_delay_songs'] = '1001'
        with pytest.raises(ValueError): r.save_settings(station, form)
        form['request_delay_songs'] = '4'; r.save_settings(station, form)
        assert settings_token(station) != before
    assert admin_client(app).get('/admin/stations/test-station/settings').status_code == 200


def test_migration_roundtrip_preserves_station_and_history(tmp_path):
    engine = sa.create_engine(f'sqlite:///{tmp_path}/migration.sqlite')
    spec = importlib.util.spec_from_file_location('requests_migration', 'migrations/versions/f506a1b2c3d4_listener_requests.py')
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    with engine.begin() as conn:
        for statement in ('CREATE TABLE stations (id INTEGER PRIMARY KEY, name TEXT)', 'CREATE TABLE tracks (id INTEGER PRIMARY KEY)', 'CREATE TABLE selection_decisions (id INTEGER PRIMARY KEY, status TEXT)', "INSERT INTO stations VALUES (1,'Preserved')", "INSERT INTO selection_decisions VALUES (1,'started')"):
            conn.execute(sa.text(statement))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(sa.text('SELECT request_settings FROM stations')).scalar() == '{}'
            migration.downgrade(); migration.upgrade()
            assert conn.execute(sa.text('SELECT status FROM selection_decisions')).scalar() == 'started'
            assert conn.execute(sa.text('SELECT name FROM stations')).scalar() == 'Preserved'


def test_smart_playlist_recomputes_rules_and_missing_audio_waits(app, monkeypatch):
    with app.app_context():
        station, playlist, tracks = setup(delay_songs=0)
        playlist.smart_enabled = True; playlist.smart_rules = {'genre': 'Jazz'}
        tracks[0].genre = 'Jazz'; tracks[1].genre = 'Rock'; db.session.commit()
        req = submit(station, tracks[1])
        ref = dict(source=dict(kind='playlist', id=playlist.id), key='smart')
        normal = select_visual(station, ref, LocalMediaStorage(), AT); db.session.commit()
        assert normal.listener_request_id is None
        normal.status = 'failed'; tracks[1].genre = 'Jazz'; db.session.commit()
        decision = select_visual(station, ref, LocalMediaStorage(), AT)
        assert decision.listener_request_id == req.id
        decision.status, decision.reason = 'failed', 'request_not_started'; db.session.commit()
        def missing(storage, slug, key):
            if key == tracks[1].storage_key: raise OSError('missing')
            return '/safe'
        monkeypatch.setattr(LocalMediaStorage, 'regular_file', missing)
        normal = select_visual(station, ref, LocalMediaStorage(), AT)
        assert normal.listener_request_id is None


def test_recovery_waits_for_complete_inventory_then_recovers_uncertain_push(app, monkeypatch):
    from app.services import playout_queue as q
    with app.app_context():
        station, _, tracks = setup(delay_songs=0)
        req = submit(station, tracks[0], at=datetime.now(timezone.utc))
        decision = select_next(station.slug)
        decision.status, decision.reason = 'failed', 'queue_failed'; db.session.commit()
        monkeypatch.setattr(q, 'request_decision_id', lambda *args: decision.id)
        monkeypatch.setattr(q, 'queued_order', lambda *args: [42])
        r.reconcile_engine(station, 'engine', set(), False)
        assert req.status == 'queued' and decision.status == 'failed'
        r.reconcile_engine(station, 'engine', {42}, True)
        assert decision.status == 'queued' and decision.liquidsoap_request_id == 42
        assert req.status == 'queued'


@pytest.mark.parametrize('requested_successor', [False, True])
def test_rejected_future_request_uses_programming_refresh_and_keeps_current(app, monkeypatch, requested_successor):
    from app.services import playout_queue as q
    from app.services.programming_refresh import refresh, signature
    from types import SimpleNamespace
    with app.app_context():
        station, _, tracks = setup(delay_songs=0)
        req = submit(station, tracks[0], at=datetime.now(timezone.utc))
        decision = select_next(station.slug); decision.status = 'queued'; decision.liquidsoap_request_id = 42; decision.socket_identity = 'engine'; db.session.commit()
        req.status = 'rejected'; db.session.commit()
        successor = m.SelectionDecision(station_id=station.id, track=tracks[1], status='queued',
            liquidsoap_request_id=43, socket_identity='engine', programming_signature=decision.programming_signature)
        if requested_successor:
            following = submit(station, tracks[1], key='second-listener', at=datetime.now(timezone.utc))
            successor.listener_request_id = following.id
            following.status = 'queued'
        db.session.add(successor); db.session.commit()
        future = {42, 43}; removed = []
        monkeypatch.setattr(q, 'request_decision_id', lambda slug, rid: {42: decision.id, 43: successor.id}.get(rid, 999))
        monkeypatch.setattr(q, 'socket_identity', lambda *args: 'engine')
        monkeypatch.setattr(q, 'queued_ids', lambda *args: set(future))
        monkeypatch.setattr(q, 'queued_order', lambda *args: sorted(future))
        monkeypatch.setattr(q, 'active_ids', lambda *args: {99})
        monkeypatch.setattr(q, 'remove_future', lambda slug, ids: (removed.extend(ids), future.difference_update(ids)))
        r.reconcile_engine(station, 'engine', future | {99}, True)
        reader = SimpleNamespace(collect=lambda *args: None, starved_until={})
        assert refresh(station, reader, signature(station))
        assert removed == [42, 43] and successor.reason == 'programming_changed' and decision.reason == 'programming_changed' and req.status == 'rejected'


@pytest.mark.parametrize('position', ['after', 'before', 'other_bus', 'confirmed'])
def test_queued_request_separation_uses_engine_order(app,monkeypatch,position):
    from app.services import playout_queue as q
    now=datetime.now(timezone.utc)
    with app.app_context():
        station,_,tracks=setup(delay_songs=0,restrict_programming=False)
        station.automation.track_separation_seconds=300
        req=submit(station,tracks[0],at=now)
        decision=select_next(station.slug)
        decision.status='queued';decision.liquidsoap_request_id=42;decision.socket_identity='engine'
        successor=m.SelectionDecision(station_id=station.id,track=tracks[0],status='queued',
            selected_at=now,liquidsoap_request_id=43,socket_identity='engine',
            programming_signature=decision.programming_signature,playback_bus='B' if position=='other_bus' else 'A')
        if position=='confirmed':successor.status='started';successor.started_at=now
        db.session.add(successor);db.session.commit()
        original=decision.programming_signature
        monkeypatch.setattr(q,'request_decision_id',lambda slug,rid:{42:decision.id,43:successor.id}[rid])
        monkeypatch.setattr(q,'queued_order',lambda slug:[43,42] if position=='before' else [42] if position=='other_bus' else [42,43])
        r.reconcile_engine(station,'engine',{42,43},True)
        if position=='after':
            assert decision.programming_signature==original
            assert decision.reason!='programming_refresh_pending'
            assert req.status=='queued' and req.played_at is None
            assert playback_started(decision.id,station.slug,now+timedelta(seconds=1))
            assert req.status=='played'
        else:
            assert decision.reason=='programming_refresh_pending'


def test_dj_load_is_durable_and_never_play_on_load(app, monkeypatch):
    now = datetime.now(timezone.utc)
    with app.app_context():
        station, _, tracks = setup(delay_songs=0, restrict_programming=False)
        station.automation.operator_mode = 'DJ_BOOTH'
        db.session.add(m.LiveQueueSnapshot(station_id=station.id, observed_at=now, queued_decision_ids=[],
            mixer=dict(mode='DJ_BOOTH', a_id=None, b_id=None, a_playing=False, b_playing=False)))
        req = submit(station, tracks[1], at=now); identifier = req.id
    response = admin_client(app).post(f'{ADMIN}/{identifier}/load', data={'csrf': 'test-admin-csrf-token', 'deck': 'B', 'nonce': str(uuid.uuid4())})
    assert response.status_code == 303
    with app.app_context():
        command = m.LiveControlCommand.query.one()
        assert command.action == 'DECK_LOAD' and command.deck == 'B' and not command.play_on_load
        assert command.target_decision.listener_request_id == identifier
        assert db.session.get(m.ListenerRequest, identifier).status == 'queued'


def test_prepared_request_rechecked_before_deck_take(app, monkeypatch):
    from app.automation_worker import process_deck_command
    from app.services import playout_queue as q
    now = datetime.now(timezone.utc)
    with app.app_context():
        station, _, tracks = setup(delay_songs=0, restrict_programming=False)
        req = submit(station, tracks[1], at=now)
        decision = m.SelectionDecision(station_id=station.id, track=tracks[1], playback_bus='B',
            admin_user_id=m.AdminUser.query.first().id, selected_at=now, status='queued', listener_request_id=req.id)
        db.session.add(decision); db.session.flush()
        req.status = 'rejected'; station.automation.operator_mode = 'DJ_BOOTH'; db.session.commit()
        command = m.LiveControlCommand(station_id=station.id, deck='B', action='DECK_PLAY', expected_decision_id=decision.id)
        monkeypatch.setattr(q, 'mixer_state', lambda slug: dict(mode='DJ_BOOTH', b_id=decision.id, b_playing=False))
        monkeypatch.setattr(q, 'channel_queue', lambda *args: [])
        monkeypatch.setattr(q, 'deck_control', lambda *args: pytest.fail('Rejected request reached deck control'))
        with pytest.raises(r.RequestIneligible): process_deck_command(station, command, 'engine')


def test_current_overlapping_deck_protected_even_with_zero_extra_separation(app):
    with app.app_context():
        station, _, tracks = setup(delay_songs=0, track_songs=0, artist_songs=0)
        req = submit(station, tracks[0])
        playing = start(station, tracks[0], AT - timedelta(seconds=2))
        start(station, tracks[1], AT - timedelta(seconds=1))
        db.session.add(m.LiveQueueSnapshot(station_id=station.id, observed_at=AT,
            mixer=dict(a_id=playing.id, a_playing=True, b_playing=True)))
        db.session.flush()
        assert r.reason(req, station, tracks, AT) == 'Waiting for track separation'


def test_mode_switch_preparation_never_consumes_listener_request(app):
    with app.app_context():
        station, playlist, tracks = setup(delay_songs=0, restrict_programming=False)
        req = submit(station, tracks[1])
        db.session.add(m.ScheduleTransition(id='switch', station_id=station.id, state='PENDING', mode='SIMPLE', previous_mode='CALENDAR', revision=0, simple={}))
        db.session.commit()
        decision = select_visual(station, dict(source=dict(kind='playlist', id=playlist.id), key='switch'), LocalMediaStorage(), AT)
        assert decision.listener_request_id is None and req.status == 'pending'


def test_stopped_station_housekeeping_expires_and_prunes_without_engine(app, monkeypatch):
    with app.app_context():
        station, _, tracks = setup()
        station.desired_state = 'stopped'; db.session.commit()
        req = submit(station, tracks[0], at=datetime.now(timezone.utc)-timedelta(hours=25))
        db.session.add(m.RequestRateBucket(station_id=station.id, key='x', kind='submit', minute=1, count=1)); db.session.commit()
        r.housekeeping()
        assert req.status == 'expired' and req.listener_key is None
        assert m.RequestRateBucket.query.count() == 0


def test_public_cooldown_station_token_and_unavailable_music(app):
    with app.app_context():
        station, _, tracks = setup()
        station.request_settings = dict(station.request_settings, cooldown_minutes=5)
        tracks[2].enabled = False; tracks[3].audio_kind = 'COMMERCIALS'; db.session.commit()
        first, second = tracks[0].uuid, tracks[1].uuid
    client = app.test_client(); result = client.get(API).json
    assert len(result['tracks']) == 2
    headers = {'X-Request-Token': result['token']}
    assert client.post(API, headers=headers, json=dict(track=first, nonce=str(uuid.uuid4()))).status_code == 202
    denied = client.post(API, headers=headers, json=dict(track=second, nonce=str(uuid.uuid4())))
    assert denied.status_code == 400 and 'cooldown' in denied.json['error']
    with app.app_context():
        station = m.Station.query.filter_by(slug='second-station').one(); station.request_settings = dict(r.DEFAULTS, enabled=True); db.session.commit()
    assert client.post('/api/stations/second-station/requests', headers=headers,
        json=dict(track=first, nonce=str(uuid.uuid4()))).status_code == 400
