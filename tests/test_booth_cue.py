import uuid
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import (Station, Track, AdminUser, BoothCue, SavedBoothCue,
                        CuePlayback, SelectionDecision, LiveQueueSnapshot)
from app.services.booth_cue import mutate, describe, completed, bind, advance
from tests.test_web import app, admin_client


def edit(station, **data):
    cue = db.session.get(BoothCue, station.id)
    return mutate(station, AdminUser.query.first(), dict(revision=str(cue.revision if cue else 0), nonce=str(uuid.uuid4()), **data))


def setup_cue():
    station = Station.query.filter_by(slug='test-station').one()
    station.automation.operator_mode = 'DJ_BOOTH'
    track = Track.query.first()
    edit(station, operation='add', identifier=track.uuid)
    edit(station, operation='add', identifier=track.uuid)
    return station, track, db.session.get(BoothCue, station.id)


def test_duplicate_entries_rotate_once_and_saved_order_is_unchanged(app):
    with app.app_context():
        station, track, cue = setup_cue()
        first, second = cue.entries
        assert first['id'] != second['id']
        edit(station, operation='save', name='Friday night')
        decision = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(decision); db.session.flush()
        bind(station, decision, first['id']); db.session.commit()
        assert completed(station, decision.id, datetime.now(timezone.utc))
        assert [row['id'] for row in cue.entries] == [second['id'], first['id']]
        assert not completed(station, decision.id, datetime.now(timezone.utc))
        assert SavedBoothCue.query.one().tracks == [track.id, track.id]


def test_mutation_retry_stale_revision_and_station_isolation(app):
    with app.app_context():
        station, track, cue = setup_cue()
        data = dict(operation='add', identifier=track.uuid, revision=str(cue.revision), nonce=str(uuid.uuid4()))
        mutate(station, AdminUser.query.first(), data)
        mutate(station, AdminUser.query.first(), data)
        assert len(cue.entries) == 3
        with pytest.raises(ValueError, match='changed'):
            mutate(station, AdminUser.query.first(), {**data, 'nonce': str(uuid.uuid4())})
        db.session.rollback()
        edit(station, operation='save', name='Private set')
        other = Station.query.filter_by(slug='second-station').one()
        with pytest.raises(ValueError, match='unavailable'):
            edit(other, operation='load', saved_id=str(cue.saved_id))


def test_new_load_and_old_completion_never_recreate_entries(app):
    with app.app_context():
        station, track, cue = setup_cue()
        decision = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(decision); db.session.flush(); bind(station, decision, cue.entries[0]['id']); db.session.commit()
        edit(station, operation='save', name='My set')
        saved_id = cue.saved_id
        edit(station, operation='new')
        assert not completed(station, decision.id, datetime.now(timezone.utc))
        assert cue.entries == [] and not cue.auto_enabled
        edit(station, operation='load', saved_id=str(saved_id))
        assert len(cue.entries) == 2 and cue.name == 'My set'
        assert not cue.auto_enabled


def test_remove_during_play_and_interrupted_completion(app):
    with app.app_context():
        station, track, cue = setup_cue()
        entry_id = cue.entries[0]['id']
        decision = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(decision); db.session.flush(); bind(station, decision, entry_id); db.session.commit()
        edit(station, operation='remove', entry_id=entry_id)
        assert completed(station, decision.id, datetime.now(timezone.utc))
        assert len(cue.entries) == 1
        db.session.get(CuePlayback, decision.id).completed_at = None
        db.session.get(CuePlayback, decision.id).interrupted = True
        db.session.commit()
        assert not completed(station, decision.id, datetime.now(timezone.utc))


def test_reorder_and_unsaved_replacement_guard(app):
    with app.app_context():
        station, track, cue = setup_cue()
        first, second = cue.entries
        edit(station, operation='move', entry_id=second['id'], before=first['id'])
        assert cue.entries == [second, first]
        with pytest.raises(ValueError, match='Discard'):
            edit(station, operation='new')
        db.session.rollback()
        edit(station, operation='new', discard='true')
        assert cue.entries == []


def test_auto_waits_for_other_deck_and_cart_then_uses_empty_deck(app, monkeypatch):
    from app.automation_worker import EventReader
    with app.app_context():
        station, track, cue = setup_cue()
        cue.auto_enabled = cue.start_pending = True
        db.session.commit()
        reader = EventReader()
        calls = []
        monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *a: '/safe')
        monkeypatch.setattr('app.services.playout_queue.socket_identity', lambda *a: 'test')
        monkeypatch.setattr('app.automation_worker.process_deck_command', lambda station, command, identity: calls.append(command.deck))
        assert advance(station, dict(mode='DJ_BOOTH', b_id=42, b_playing=True), reader)
        assert advance(station, dict(mode='DJ_BOOTH', cart_id=12), reader)
        assert calls == []
        assert advance(station, dict(mode='DJ_BOOTH', b_id=42, b_playing=False), reader)
        assert calls == ['A'] and not cue.start_pending


def test_auto_unavailable_list_disarms_without_looping(app, monkeypatch):
    from app.automation_worker import EventReader
    with app.app_context():
        station, track, cue = setup_cue()
        track.enabled = False
        cue.auto_enabled = cue.start_pending = True
        db.session.commit()
        assert not advance(station, dict(mode='DJ_BOOTH'), EventReader())
        assert not cue.auto_enabled and 'no playable' in cue.message


def test_cue_routes_require_csrf_and_retain_working_list(app):
    client = admin_client(app)
    page = client.get('/admin/stations/test-station/live')
    assert page.status_code == 200
    with client.session_transaction() as session:
        token = session['admin_csrf']
    url = '/admin/stations/test-station/live/cue-list'
    data = dict(operation='add', identifier='00000000-0000-4000-8000-000000000001', revision='0', nonce=str(uuid.uuid4()))
    assert client.post(url, data=data).status_code == 400
    response = client.post(url, data={**data, 'csrf': token}, headers={'Accept': 'application/json'})
    assert response.status_code == 200
    state = client.get('/admin/api/stations/test-station/live-status').json['cue_list']
    assert len(state['entries']) == 1 and state['entries'][0]['title'] == 'Verified Test Track'


def test_single_entry_repeats_and_search_playback_does_not_rotate(app):
    with app.app_context():
        station, track, cue = setup_cue()
        edit(station, operation='remove', entry_id=cue.entries[1]['id'])
        cue.auto_enabled = True
        decision = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='B', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(decision); db.session.flush(); bind(station, decision, cue.entries[0]['id']); db.session.commit()
        entry = dict(cue.entries[0])
        assert completed(station, decision.id, datetime.now(timezone.utc))
        assert cue.entries == [entry] and cue.start_pending and cue.last_deck == 'B'
        cue.start_pending = False
        other = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(other); db.session.flush(); bind(station, other); db.session.commit()
        assert completed(station, other.id, datetime.now(timezone.utc))
        assert cue.entries == [entry] and cue.start_pending


def test_old_engine_eof_does_not_start_or_rotate_and_repeat_owns_rotation(app):
    with app.app_context():
        station, track, cue = setup_cue()
        first = dict(cue.entries[0])
        decision = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='started', started_at=datetime.now(timezone.utc), socket_identity='old-engine')
        db.session.add(decision); db.session.flush(); bind(station, decision, first['id']); db.session.commit()
        assert not completed(station, decision.id, datetime.now(timezone.utc), 'new-engine')
        assert cue.entries[0] == first
        db.session.get(CuePlayback, decision.id).completed_at = None
        repeat = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(repeat); db.session.flush(); bind(station, repeat, previous=decision); db.session.commit()
        assert not db.session.get(CuePlayback, decision.id).interrupted
        from app.services.booth_cue import interrupt
        interrupt(station, decision.id); db.session.commit()
        assert not completed(station, decision.id, datetime.now(timezone.utc))
        assert completed(station, repeat.id, datetime.now(timezone.utc))
        assert cue.entries[-1] == first


@pytest.mark.parametrize('change', ['reorder', 'disable', 'new'])
def test_pending_auto_start_is_revalidated_before_touching_engine(app, monkeypatch, change):
    from app.models import LiveControlCommand
    from app.automation_worker import process_deck_command
    from app.services.booth_cue import CueChanged
    with app.app_context():
        station, track, cue = setup_cue()
        cue.auto_enabled = True
        decision = SelectionDecision(station_id=station.id, track_id=track.id, playback_bus='A', status='selected', selection_method='cue_auto', reason='deck_load')
        db.session.add(decision); db.session.flush(); bind(station, decision, cue.entries[0]['id'])
        command = LiveControlCommand(station_id=station.id, target_decision_id=decision.id, action='DECK_LOAD', deck='A', play_on_load=True, idempotency_key=str(uuid.uuid4()))
        db.session.add(command); db.session.commit()
        if change == 'reorder':
            edit(station, operation='move', entry_id=cue.entries[1]['id'], before=cue.entries[0]['id'])
        elif change == 'disable':
            edit(station, operation='auto', enabled='false')
        else:
            edit(station, operation='new', discard='true')
        monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file', lambda *a: '/safe')
        monkeypatch.setattr('app.services.playout_queue.mixer_state', lambda *a: pytest.fail('Cancelled request reached the engine'))
        with pytest.raises(CueChanged):
            process_deck_command(station, command, 'engine')
