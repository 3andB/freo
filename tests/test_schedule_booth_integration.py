"""Cross-feature scheduling regressions from the September 19 audit."""
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import Station, Track, LiveQueueSnapshot
from app.services import visual_schedule as vs
from app.services.live_assist import status
from app.services.programming_refresh import signature, refresh
from app.automation_worker import EventReader
from tests.test_web import app
from tests.test_programming_refresh import fake_engine, queue_row


def simple_station(kind='song'):
    station = Station.query.filter_by(slug='test-station').one()
    track = Track.query.first()
    track.categories = []
    source_id = track.id
    if kind in ('artist', 'album'):
        from app.models import Artist, Album
        artist = Artist(station_id=station.id, name='Scheduled artist', normalized_name='scheduled artist')
        album = Album(station_id=station.id, artist=artist, title='Scheduled album', normalized_title='scheduled album')
        db.session.add_all([artist, album])
        track.catalog_artist = artist
        track.catalog_album = album
        db.session.flush()
        source_id = artist.id if kind == 'artist' else album.id
    policy = vs.policy(station, True)
    policy.activated = True
    policy.mode = 'SIMPLE'
    policy.simple = policy.live_simple = vs.source(station, dict(kind=kind, id=source_id))
    db.session.commit()
    return station, track, policy


@pytest.mark.parametrize('change', ['disable', 'storage', 'duration'])
@pytest.mark.parametrize('kind', ['song', 'artist', 'album'])
def test_direct_scheduled_song_changes_refresh_queued_audio(app, monkeypatch, change, kind):
    queued = {11}
    fake_engine(monkeypatch, queued)
    with app.app_context():
        station, track, policy = simple_station(kind)
        row = queue_row(station, 11)
        before = signature(station)
        if change == 'disable':
            track.enabled = False
        elif change == 'storage':
            track.storage_key = 'replacement.mp3'
        else:
            track.duration_ms += 1000
        db.session.commit()
        after = signature(station)
        assert after != before
        assert refresh(station, EventReader(), after)
        assert not queued and row.reason == 'programming_changed'


def test_booth_reports_active_visual_program(app):
    with app.app_context():
        station, track, policy = simple_station()
        assert status(station)['program'] == policy.live_simple['name']


def test_player_reports_active_visual_program(app):
    from app.services.player import now_playing
    with app.test_request_context('/'):
        station, track, policy = simple_station()
        db.session.add(LiveQueueSnapshot(station_id=station.id,
            observed_at=datetime.now(timezone.utc), mixer={'mode': 'AUTO'},
            queued_decision_ids=[], unknown_count=0))
        db.session.commit()
        assert now_playing(station)['program'] == policy.live_simple['name']


def test_player_reports_dj_event_instead_of_paused_deck(app):
    from app.models import SelectionDecision
    from app.services.player import now_playing
    with app.test_request_context('/'):
        station, track, policy = simple_station()
        station.automation.operator_mode = 'DJ_BOOTH'
        deck = SelectionDecision.query.filter_by(status='started').first()
        event = SelectionDecision(station_id=station.id, track=track,
            selection_method='timed_event', status='started', started_at=datetime.now(timezone.utc))
        db.session.add(event)
        db.session.flush()
        db.session.add(LiveQueueSnapshot(station_id=station.id, current_decision_id=event.id,
            observed_at=datetime.now(timezone.utc), queued_decision_ids=[], unknown_count=0,
            mixer=dict(mode='DJ_BOOTH', a_id=deck.id, a_playing=True, transition={'a_gain': 1})))
        db.session.commit()
        assert [item['decision_id'] for item in now_playing(station)['current']] == [event.id]


def test_booth_event_overrun_uses_utc_for_naive_database_timestamps(app):
    from app.models import SelectionDecision
    from app.services.timed_events import save_event
    with app.app_context():
        station, track, policy = simple_station()
        decision = SelectionDecision.query.filter_by(status='started').first()
        # SQLite returns naive datetimes even for a timezone-aware column.
        decision.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.add(LiveQueueSnapshot(station_id=station.id, current_decision_id=decision.id,
            observed_at=datetime.now(timezone.utc), queued_decision_ids=[], unknown_count=0))
        save_event(station.slug, name='Next event', recurrence_type='DAILY',
            content_type='TRACK', content_identifier=track.uuid, local_time='23:59')
        db.session.commit()
        db.session.expire_all()
        observed = status(station)
        assert observed['current']['started_at'].endswith('+00:00')
        assert observed['next_event'] is not None


@pytest.mark.parametrize('phase', ['QUEUED', 'STARTED'])
@pytest.mark.parametrize('sequence', [False, True])
def test_schedule_handoff_terminates_event_history_without_erasing_starts(app, monkeypatch, phase, sequence):
    import uuid
    from app import models as m
    from app.services import schedule_switch as switch, timed_events
    from app.services.event_blocks import confirm_finished
    from tests.test_visual_schedule import setup

    monkeypatch.setattr('app.services.automation._exists', lambda *a: True)
    monkeypatch.setattr(EventReader, 'collect', lambda *a: 0)
    monkeypatch.setattr(switch, 'queued_ids', lambda *a: set())
    monkeypatch.setattr(switch, 'active_ids', lambda *a: set())
    monkeypatch.setattr(switch, 'socket_identity', lambda *a: 'engine')
    monkeypatch.setattr(switch, 'push_decision', lambda *a: 99)
    response = ['FADING']
    monkeypatch.setattr(switch, '_command', lambda *a: response[0])
    with app.app_context():
        station, policy, ref = setup()
        track = db.session.get(Track, ref['id'])
        event = timed_events.save_event(station.slug, name='Handoff event',
            recurrence_type='DAILY', content_type='TRACK', content_identifier=track.uuid,
            local_time='12:00')
        occurrence = event.occurrences[-1]
        began = datetime.now(timezone.utc)
        decision = m.SelectionDecision(station_id=station.id, track_id=track.id,
            status=phase.lower(), selection_method='event_block' if sequence else 'timed_event',
            started_at=began if phase == 'STARTED' else None,
            liquidsoap_request_id=11, socket_identity='engine')
        db.session.add(decision)
        occurrence.state = phase
        occurrence.boundary_reserved = True
        occurrence.runtime = {'dj': True}
        if sequence:
            execution = m.EventBlockExecution(station_id=station.id, source='TIMED_EVENT',
                timed_event_occurrence=occurrence, playlist_id=policy.default_playlist_id, state=phase)
            execution.items.append(m.EventBlockItemExecution(position=1, item_type='TRACK',
                track=track, selection_decision=decision, state=phase, failure_policy='SKIP_FAILED_ITEM'))
            db.session.add(execution)
        else:
            occurrence.selection_decision = decision
        db.session.commit()
        command = vs.transition_request(station, dict(id=str(uuid.uuid4()), mode='SIMPLE',
            current=policy.mode, revision=policy.revision, simple=ref))
        db.session.commit()
        reader = EventReader()
        assert switch.process_transition(station, reader)
        response[0] = 'APPLIED'
        command.decision.status = 'started'
        command.decision.started_at = datetime.now(timezone.utc)
        db.session.commit()
        assert switch.process_transition(station, reader)
        assert occurrence.state == 'FAILED'
        assert occurrence.failure_reason == 'interrupted_by_mode_change'
        if sequence:
            assert execution.state == 'ABORTED'
            assert execution.items[0].state == ('FAILED' if phase == 'STARTED' else 'SKIPPED')
        if phase == 'STARTED':
            assert decision.status == 'started' and decision.started_at is not None
            confirm_finished(station, decision.id, datetime.now(timezone.utc), 'engine')
            assert occurrence.state == 'FAILED'
            assert occurrence.completed_at is None
            if sequence:
                assert execution.items[0].state == 'FAILED'
        else:
            assert decision.status == 'failed' and decision.started_at is None


@pytest.mark.parametrize('finished', ['COMPLETED', 'FAILED', 'ABORTED', 'CANCELLED'])
def test_worker_reconciles_stale_event_from_finished_sequence(app, monkeypatch, finished):
    from app import automation_worker as worker, models as m
    from app.services import timed_events
    monkeypatch.setattr(worker, 'socket_identity', lambda *a: 'engine')
    monkeypatch.setattr(worker, 'queued_ids', lambda *a: set())
    monkeypatch.setattr(worker, 'active_ids', lambda *a: set())
    monkeypatch.setattr('app.services.playout_queue._command', lambda *a: '')
    monkeypatch.setattr('app.services.playout_queue.channel_queue', lambda *a: [])
    with app.app_context():
        station, track, policy = simple_station()
        event = timed_events.save_event(station.slug, name='Legacy sequence', recurrence_type='DAILY',
            content_type='TRACK', content_identifier=track.uuid, local_time='12:00')
        occurrence = event.occurrences[-1]
        occurrence.state = 'STARTED'
        completed_at = datetime(2026, 9, 15, tzinfo=timezone.utc)
        execution = m.EventBlockExecution(station_id=station.id, source='TIMED_EVENT',
            timed_event_occurrence=occurrence, state=finished, completed_at=completed_at)
        db.session.add(execution)
        db.session.commit()
        worker.reconcile_requests(station.slug)
        assert occurrence.state == ('FAILED' if finished == 'ABORTED' else finished)
        assert occurrence.completed_at.replace(tzinfo=timezone.utc) == completed_at
        # Once reconciled, later passes cannot revive or rewrite terminal history.
        occurrence.state = 'FAILED'
        occurrence.failure_reason = 'operator_review'
        db.session.commit()
        worker.reconcile_requests(station.slug)
        assert occurrence.state == 'FAILED' and occurrence.failure_reason == 'operator_review'


@pytest.mark.parametrize('action', ['SKIP', 'FADE'])
def test_operator_interrupt_does_not_complete_single_event(app, monkeypatch, action):
    import uuid
    from app import automation_worker as worker, models as m
    from app.services import timed_events
    from app.services.event_blocks import confirm_finished
    monkeypatch.setattr(EventReader, 'collect', lambda *a: 0)
    monkeypatch.setattr(worker, 'socket_identity', lambda *a: 'engine')
    monkeypatch.setattr(worker, 'queued_ids', lambda *a: set())
    monkeypatch.setattr(worker, 'active_ids', lambda *a: {99})
    monkeypatch.setattr('app.services.playout_queue._command', lambda *a: '')
    monkeypatch.setattr('app.services.playout_queue.channel_queue', lambda *a: [])
    faded = []
    monkeypatch.setattr('app.services.playout_queue.fade_current', lambda slug, identifier: faded.append(identifier))
    with app.app_context():
        station, track, policy = simple_station()
        event = timed_events.save_event(station.slug, name='Interrupted single', recurrence_type='DAILY',
            content_type='TRACK', content_identifier=track.uuid, local_time='12:00')
        occurrence = event.occurrences[-1]
        decision = m.SelectionDecision(station_id=station.id, track=track, status='started',
            started_at=datetime.now(timezone.utc), socket_identity='engine', liquidsoap_request_id=99,
            selection_method='timed_event')
        occurrence.selection_decision = decision
        occurrence.state = 'STARTED'
        command = m.LiveControlCommand(station_id=station.id, action=action,
            expected_decision=decision, status='pending', idempotency_key=str(uuid.uuid4()))
        db.session.add_all([decision, command])
        db.session.commit()
        worker.process_manual(station, EventReader())
        assert command.status == 'sent' and faded == [decision.id]
        confirm_finished(station, decision.id, datetime.now(timezone.utc), 'engine')
        assert occurrence.state == 'FAILED' and occurrence.failure_reason == 'operator_skip'
        assert occurrence.completed_at is None and decision.status == 'started'
