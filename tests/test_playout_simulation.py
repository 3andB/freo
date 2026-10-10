"""Advance scheduling time across weeks; no wall-clock waiting or live engine."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import uuid

import pytest

from app.extensions import db
from app.models import Playlist, PlaylistItem, ScheduleTransition, Station, Track
from app.services import visual_schedule as vs
from app.services.automation import select_next
from tests.test_web import app


@pytest.mark.parametrize('mode', ['SIMPLE', 'BLOCKS', 'CALENDAR'])
@pytest.mark.parametrize('zone', ['America/Denver', 'Europe/London'])
@pytest.mark.parametrize('start', ['2026-03-07', '2026-10-24'])
def test_four_weeks_of_boundaries_selection_and_session_recovery(app, monkeypatch, mode, zone, start):
    # Only media presence is simulated; use the real resolver, selector and DB.
    monkeypatch.setattr('app.services.automation._exists', lambda *args: True)
    began = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.timezone = zone
        first = Track.query.first()
        second = Track(station_id=station.id, uuid=str(uuid.uuid4()), title='Daytime fixture',
            artist='Second artist', original_filename='day.mp3', storage_key='day.mp3',
            media_type='mp3', duration_ms=180000, sample_rate_hz=44100, channels=2,
            file_size_bytes=1000, enabled=True, ingest_status='accepted')
        db.session.add(second)
        db.session.flush()
        ids = [first.id, second.id]
        playlist = Playlist(station_id=station.id, name='Simulation fallback', mode='STRAIGHT')
        playlist.items.append(PlaylistItem(track=first, position=1))
        db.session.add(playlist)
        block = vs.save_composition(station, dict(kind='BLOCK', name='Simulated day', sections=[
            dict(id='night', start=0, end=21600, source=dict(kind='song', id=ids[0])),
            dict(id='day', start=21600, end=64800, source=dict(kind='song', id=ids[1])),
            dict(id='evening', start=64800, end=86400, source=dict(kind='song', id=ids[0])),
        ]))
        db.session.flush()
        ref = vs.source(station, dict(kind='block', id=block.id), allow_block=True)
        policy = vs.policy(station, True)
        rule = dict(frequency='daily', anchor='2026-01-01')
        policy.assignments = vs.clean_document(station, [dict(id='all', pattern=[ref], rule=rule)], assignments=True)
        policy.calendar = vs.clean_document(station, [dict(id='all', start=0, end=86400, source=ref, rule=rule)])
        policy.simple = policy.live_simple = ref
        policy.default_playlist_id = playlist.id
        policy.mode = mode
        policy.activated = policy.calendar_saved = True
        command = ScheduleTransition(id=str(uuid.uuid4()), station_id=station.id, mode=mode,
            previous_mode='CALENDAR', revision=policy.revision, state='APPLIED',
            created_at=began, completed_at=began)
        db.session.add(command)
        policy.activation = command.id
        db.session.commit()
        # Sample every hour and both sides of each boundary. UTC progression
        # visits both occurrences of the repeated local hour in the autumn.
        for hour in range(28*24):
            instant = began + timedelta(hours=hour)
            for offset in (-1, 0, 1):
                at = instant + timedelta(seconds=offset)
                if at < began:
                    continue
                clock_hour = ((at-began).total_seconds() % 86400)/3600 if mode == 'SIMPLE' else at.astimezone(ZoneInfo(zone)).hour
                expected = ids[int(6 <= clock_hour < 18)]
                resolved = vs.resolve_visual(station, at)
                assert resolved['source']['id'] == expected, (mode, zone, at, resolved)
                assert resolved['next_transition'] > at, (at, resolved)
                if offset == 0 and hour % 6 == 0:
                    selected = select_next(station.slug, now=at)
                    assert selected.track_id == expected
                    assert selected.status != 'started', 'Simulation must not fabricate confirmed airplay'
                    key = resolved['key']
                    db.session.commit()
                    db.session.remove()
                    station = Station.query.filter_by(slug='test-station').one()
                    assert vs.resolve_visual(station, at)['key'] == key


def test_unavailable_scheduled_content_recovers_without_changing_saved_schedule(app, monkeypatch):
    from tests.test_visual_schedule import setup, at
    monkeypatch.setattr('app.services.automation._exists', lambda *args: True)
    with app.app_context():
        station, policy, ref = setup()
        policy.mode = 'SIMPLE'
        policy.simple = policy.live_simple = ref
        policy.activated = True
        song = db.session.get(Track, ref['id'])
        before = dict(policy.live_simple)
        for unavailable in (True, False, True, False):
            song.enabled = not unavailable
            db.session.commit()
            selection = select_next(station.slug, now=at())
            if unavailable:
                assert selection is None
            else:
                assert selection.track_id == song.id
            assert policy.live_simple == before and policy.mode == 'SIMPLE'
