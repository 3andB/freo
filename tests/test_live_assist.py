"""Live Assist intent and socket boundary regressions."""
import uuid

import pytest

from app.extensions import db
from app.models import AdminUser, AuditEvent, AutomationState, ImagingAsset,LiveCartSlot,LiveQueueSnapshot, SelectionDecision, Station, Track
from app.services.live_assist import (assign_cart, cue_track, queue_playable,
    request_fade, request_skip, request_takeover, set_hold, set_mode)
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
    assert anonymous.get('/admin/api/stations/test-station/song-search?q=test').status_code == 302
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


def test_three_booth_modes_have_explicit_hold_semantics(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();user=AdminUser.query.first()
        set_mode(station,user,'DJ_BOOTH');assert station.automation.operator_mode=='DJ_BOOTH' and station.automation.hold
        set_mode(station,user,'AUTO');assert station.automation.operator_mode=='AUTO' and not station.automation.hold
        with pytest.raises(ValueError):set_mode(station,user,'ENGINEERING')


def test_cue_deck_and_fade_are_durable_worker_intents(app, monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();user=AdminUser.query.first()
        track=Track.query.first();current=SelectionDecision.query.filter_by(status='started').first()
        cue_track(station,user,track.uuid)
        assert station.automation.cued_track_id == track.id
        assert SelectionDecision.query.filter_by(station_id=station.id, status='selected').count() == 0
        from app.services.live_assist import clear_cue
        clear_cue(station,user)
        assert station.automation.cued_track_id is None
        assert SelectionDecision.query.filter_by(station_id=station.id, status='selected').count() == 0
        command=request_fade(station,user,current.id,str(uuid.uuid4()))
        assert command.action == 'FADE' and command.status == 'pending'


def test_takeover_intent_and_cart_assignment_are_station_scoped(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.imaging_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();user=AdminUser.query.first();current=SelectionDecision.query.filter_by(status='started').first();track=Track.query.first()
        command=request_takeover(station,user,track.uuid,current.id,str(uuid.uuid4()))
        assert command.action=='TAKEOVER' and command.target_decision.track_id==track.id and command.target_decision.status=='selected'
        asset=ImagingAsset(station_id=station.id,uuid=str(uuid.uuid4()),name='Legal ID',cart_code='ID-1',asset_type='STATION_ID',original_filename='id.mp3',storage_key='c'*32+'.mp3',media_type='mp3',duration_ms=3000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='c'*64,enabled=True,ingest_status='accepted');db.session.add(asset);db.session.commit()
        slot=assign_cart(station,user,'ID',1,asset.uuid,'Legal');assert slot.imaging_asset_id==asset.id
    client=admin_client(app);base='/admin/stations/test-station/live'
    assert client.post(base+'/mode',data={'csrf':'test-admin-csrf-token','mode':'DJ_BOOTH'}).status_code==302
    assert client.post(base+'/assign-cart',data={'csrf':'test-admin-csrf-token','role':'HOT','position':'1','identifier':'foreign'}).status_code==302
    with app.app_context():assert LiveCartSlot.query.count()==1


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
    for command in ('freo_queue.push /etc/passwd',
                    'system.shutdown', 'freo_queue.skip\nrequest.on_air'):
        with pytest.raises(ValueError):
            _command('test-station', command)


def test_program_meter_parses_only_bounded_liquidsoap_rms(monkeypatch):
    from app.services.playout_queue import program_rms
    monkeypatch.setattr('app.services.playout_queue._command', lambda slug, command: '0.25')
    assert program_rms('test-station') == 0.25
    monkeypatch.setattr('app.services.playout_queue._command', lambda slug, command: '2.0')
    with pytest.raises(RuntimeError):
        program_rms('test-station')


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
    assert b'DJ Booth' in page.data and b'NOW PLAYING' in page.data and b'Verified Test Track' in page.data
    assert page.data.count(b'data-role="HOT"') == 8
    assert page.data.count(b'data-role="ID"') == 4
    assert page.data.count(b'data-assign') >= 12
    assert b'DECK B' in page.data and b'NOTHING LOADED' in page.data
    assert b'PROGRAM / LIVE' in page.data and b'>MONITOR<' in page.data
    assert b'STATUS / ENGINEERING' in page.data
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
    monkeypatch.setattr('app.services.playout_queue.fade_current', lambda slug, expected: calls.append(slug))
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
        # A second click with a new token cannot repeat a sent skip.
        assert request_skip(station,user,current.id,str(uuid.uuid4())).id == command.id
        current = SelectionDecision(station_id=station.id,track_id=current.track_id,status='started',
            started_at=current.started_at,socket_identity='socket-1',liquidsoap_request_id=46)
        db.session.add(current)
        db.session.commit()
        stale = request_skip(station, user, current.id, str(uuid.uuid4()))
        process_manual(station, EventReader())
        assert stale.status == 'failed' and stale.error_code == 'current_changed'
        assert calls == ['test-station']


def test_worker_takeover_is_one_shot_and_queues_approved_target(app, monkeypatch):
    from app.automation_worker import EventReader, process_manual
    calls = []
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: '/safe')
    monkeypatch.setattr('app.automation_worker.socket_identity', lambda slug: 'socket-1')
    monkeypatch.setattr('app.automation_worker.queued_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.active_ids', lambda slug: {45})
    monkeypatch.setattr('app.automation_worker.reconcile_requests', lambda slug: 0)
    monkeypatch.setattr('app.automation_worker.interrupt_for_event', lambda slug: calls.append(slug))
    monkeypatch.setattr('app.automation_worker.push_decision', lambda decision: 52)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        current = SelectionDecision.query.filter_by(status='started').first()
        current.socket_identity = 'socket-1'
        current.liquidsoap_request_id = 45
        db.session.commit()
        command = request_takeover(station, AdminUser.query.first(), Track.query.first().uuid,
            current.id, str(uuid.uuid4()))
        target_id = command.target_decision_id
        process_manual(station, EventReader())
        target = db.session.get(SelectionDecision, target_id)
        assert command.status == 'sent' and target.status == 'queued'
        assert target.liquidsoap_request_id == 52 and calls == ['test-station']
        process_manual(station, EventReader())
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


def test_cue_json_reports_missing_audio_and_success(app, monkeypatch):
    client = admin_client(app)
    path = '/admin/stations/test-station/live/cue'
    data = {'csrf':'test-admin-csrf-token', 'identifier':'00000000-0000-4000-8000-000000000001'}
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: (_ for _ in ()).throw(FileNotFoundError()))
    response = client.post(path, data=data, headers={'Accept':'application/json'})
    assert response.status_code == 409
    assert response.json['message'] == 'Approved audio is unavailable'
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: '/safe')
    response = client.post(path, data=data, headers={'Accept':'application/json'})
    assert response.status_code == 200 and response.json['ok']


def test_stale_takeover_never_becomes_an_ordinary_queue_request(app, monkeypatch):
    from app.automation_worker import EventReader, process_manual
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: '/safe')
    monkeypatch.setattr('app.automation_worker.socket_identity', lambda slug: 'socket-1')
    monkeypatch.setattr('app.automation_worker.queued_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.active_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.reconcile_requests', lambda slug: 0)
    monkeypatch.setattr('app.automation_worker.push_decision', lambda *_: (_ for _ in ()).throw(AssertionError('stale takeover queued')))
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        current=SelectionDecision.query.filter_by(status='started').first()
        current.socket_identity='socket-1';current.liquidsoap_request_id=45;db.session.commit()
        nonce=str(uuid.uuid4())
        command=request_takeover(station,AdminUser.query.first(),Track.query.first().uuid,current.id,nonce)
        assert request_takeover(station,AdminUser.query.first(),Track.query.first().uuid,current.id,nonce).id == command.id
        process_manual(station,EventReader())
        assert command.status=='failed' and command.target_decision.status=='failed'
        process_manual(station,EventReader())


def test_start_cue_rejects_changed_current_and_keeps_selection(app, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: '/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        current=SelectionDecision.query.filter_by(status='started').first()
        db.session.add(LiveQueueSnapshot(station_id=station.id,current_decision_id=current.id,queued_decision_ids=[],unknown_count=0,observed_at=datetime.now(timezone.utc)))
        cue_track(station,AdminUser.query.first(),Track.query.first().uuid)
        current_id=current.id
    client=admin_client(app)
    data={'csrf':'test-admin-csrf-token','nonce':str(uuid.uuid4()),'expected_decision_id':str(current_id+100)}
    result=client.post('/admin/stations/test-station/live/start-cue',data=data,headers={'Accept':'application/json'})
    assert result.status_code==409
    with app.app_context():assert Station.query.filter_by(slug='test-station').first().automation.cued_track
    data['expected_decision_id']=str(current_id)
    result=client.post('/admin/stations/test-station/live/start-cue',data=data,headers={'Accept':'application/json'})
    assert result.status_code==200


def test_idle_deck_start_rechecks_engine_and_never_skips(app, monkeypatch):
    from datetime import datetime, timezone
    from app.automation_worker import EventReader, process_manual
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *args: '/safe')
    monkeypatch.setattr('app.automation_worker.socket_identity', lambda slug: 'socket-1')
    monkeypatch.setattr('app.automation_worker.queued_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.active_ids', lambda slug: set())
    monkeypatch.setattr('app.automation_worker.reconcile_requests', lambda slug: 0)
    monkeypatch.setattr('app.automation_worker.push_decision', lambda decision: 55)
    monkeypatch.setattr('app.automation_worker.interrupt_for_event', lambda *_: pytest.fail('Idle start must never skip'))
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        db.session.add(LiveQueueSnapshot(station_id=station.id, observed_at=datetime.now(timezone.utc), queued_decision_ids=[], unknown_count=0))
        db.session.commit()
        command = request_takeover(station, AdminUser.query.first(), Track.query.first().uuid, None, str(uuid.uuid4()))
        process_manual(station, EventReader())
        assert command.status == 'sent' and command.target_decision.liquidsoap_request_id == 55
        command = request_takeover(station, AdminUser.query.first(), Track.query.first().uuid, None, str(uuid.uuid4()))
        monkeypatch.setattr('app.automation_worker.active_ids', lambda slug: {56})
        process_manual(station, EventReader())
        assert command.status == 'failed' and command.target_decision.status == 'failed'


def test_delayed_observation_keeps_last_identity_without_claiming_live(app):
    from datetime import datetime, timedelta, timezone
    from app.services.live_assist import status
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        current = SelectionDecision.query.filter_by(status='started').first()
        db.session.add(LiveQueueSnapshot(station_id=station.id,current_decision_id=current.id,
            observed_at=datetime.now(timezone.utc)-timedelta(seconds=20), queued_decision_ids=[], unknown_count=0))
        db.session.commit()
        payload = status(station)
        assert payload['current'] is None and not payload['observation_fresh']
        assert payload['last_known_current']['title'] == 'Verified Test Track'
        with pytest.raises(ValueError, match='observation is unavailable'):
            request_takeover(station, AdminUser.query.first(), Track.query.first().uuid, None, str(uuid.uuid4()))


def test_dj_control_does_not_require_automation_enabled(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').first()
        station.automation.enabled = False
        db.session.commit()
        set_mode(station, AdminUser.query.first(), 'DJ_BOOTH')
        assert station.automation.hold and station.automation.operator_mode == 'DJ_BOOTH'


def test_pending_auto_skip_rejected_after_switch_to_dj(app,monkeypatch):
    from app.automation_worker import EventReader,process_manual
    monkeypatch.setattr('app.automation_worker.socket_identity',lambda slug:'socket-1')
    monkeypatch.setattr('app.automation_worker.queued_ids',lambda slug:set())
    monkeypatch.setattr('app.automation_worker.active_ids',lambda slug:{45})
    monkeypatch.setattr('app.automation_worker.reconcile_requests',lambda slug:0)
    monkeypatch.setattr('app.services.playout_queue.fade_current',lambda *args:pytest.fail('Auto skip must not affect a DJ deck'))
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();user=AdminUser.query.first()
        current=SelectionDecision.query.filter_by(status='started').one()
        current.socket_identity='socket-1';current.liquidsoap_request_id=45;db.session.commit()
        command=request_skip(station,user,current.id,str(uuid.uuid4()))
        station.automation.operator_mode='DJ_BOOTH';db.session.commit()
        process_manual(station,EventReader())
        assert command.status=='failed' and command.error_code=='current_changed'
