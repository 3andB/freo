from datetime import datetime, timedelta, timezone
import uuid

import pytest
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.extensions import db
from app.models import Clock, ClockSlot, ClockState, ScheduleAssignment, SelectionDecision, Track
from app.services import automation
from app.services.clocks import add_clock_slot, assign, create_clock, current, move_clock_slot, preview_clock, set_default_clock, set_timezone
from app.services.media_storage import LocalMediaStorage
from app.services.schedule import parse_local_time, resolve, validate_timezone
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


def track(slug, category, artist, storage):
    station = automation.require_station(slug)
    key = uuid.uuid4().hex + '.mp3'
    folder = storage.station_dir(slug) / 'originals'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / key).write_bytes(b'fixture')
    row = Track(station_id=station.id, uuid=str(uuid.uuid4()), title=key[:8], artist=artist,
        album='', original_filename='fixture.mp3', storage_key=key, media_type='mp3',
        duration_ms=1000, sample_rate_hz=44100, channels=1, file_size_bytes=7,
        checksum_sha256=uuid.uuid4().hex * 2, enabled=True, ingest_status='accepted')
    db.session.add(row)
    db.session.commit()
    automation.assign_track(slug, row.uuid, category)
    return row


def make_clock(storage):
    automation.category_create('one', 'Power', 'power')
    automation.category_create('one', 'Medium', 'medium')
    track('one', 'power', 'Artist A', storage)
    track('one', 'power', 'Artist B', storage)
    track('one', 'medium', 'Artist C', storage)
    automation.rotation_create('one', 'Main', 'main')
    automation.add_slot('one', 'main', 'power')
    automation.add_slot('one', 'main', 'medium')
    automation.activate('one', 'main')
    automation.set_automation('one', True, 3600, 3600)
    create_clock('one', 'Morning', 'morning')
    add_clock_slot('one', 'morning', 'category', 'power')
    add_clock_slot('one', 'morning', 'rotation', 'main')
    set_timezone('one', 'America/Denver')


def test_timezone_time_and_target_validation(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        for name in ('', 'MST', 'Not/AZone', '../../etc/passwd', '+02:00'):
            with pytest.raises(ValueError):
                validate_timezone(name)
        assert validate_timezone('America/Denver') == 'America/Denver'
        for bad in ('24:00', '1:00', '12:60', '12:00:00', '../..'):
            with pytest.raises(ValueError):
                parse_local_time(bad)
        with pytest.raises(ValueError):
            add_clock_slot('one', 'morning', 'script', 'arbitrary')
        with pytest.raises(ValueError):
            add_clock_slot('one', 'morning', 'category', 'other-station')
        with pytest.raises(ValueError):
            assign('one', 7, '06:00', 'morning')
        with pytest.raises(ValueError):
            assign('two', 0, '06:00', 'morning')
        clock = Clock.query.filter_by(slug='morning').one()
        db.session.add(ClockSlot(clock_id=clock.id, position=3, slot_type='SCRIPT', category_id=None, rotation_id=None))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_week_wrap_next_transition_and_fallback(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        station = automation.require_station('one')
        assert current('one', datetime(2026, 9, 14, 8, tzinfo=timezone.utc))['source'] == 'rotation'
        set_default_clock('one', 'morning')
        assert current('one', datetime(2026, 9, 14, 8, tzinfo=timezone.utc))['source'] == 'default'
        sunday = assign('one', 6, '22:00', 'morning')
        monday = assign('one', 0, '06:00', 'morning')
        with pytest.raises(ValueError):
            assign('one', 0, '06:00', 'morning')
        monday_early = resolve(station, datetime(2026, 9, 14, 7, tzinfo=timezone.utc))
        assert monday_early.assignment.id == sunday.id
        assert monday_early.occurrence_key.endswith('2026-09-13')
        assert monday_early.next_transition == datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        monday_late = resolve(station, datetime(2026, 9, 14, 13, tzinfo=timezone.utc))
        assert monday_late.assignment.id == monday.id
        assert monday_late.next_transition == datetime(2026, 9, 21, 4, tzinfo=timezone.utc)


def test_previous_day_carry_disabled_assignment_and_clock(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        station = automation.require_station('one')
        monday = assign('one', 0, '06:00', 'morning')
        tuesday = assign('one', 1, '10:00', 'morning')
        early_tuesday = resolve(station, datetime(2026, 9, 15, 8, tzinfo=timezone.utc))
        assert early_tuesday.assignment.id == monday.id
        assert early_tuesday.next_transition == datetime(2026, 9, 15, 16, tzinfo=timezone.utc)
        tuesday.enabled = False
        db.session.commit()
        assert resolve(station, datetime(2026, 9, 15, 17, tzinfo=timezone.utc)).assignment.id == monday.id
        monday.clock.enabled = False
        db.session.commit()
        assert resolve(station, datetime(2026, 9, 15, 17, tzinfo=timezone.utc)).assignment is None
        assert app.test_client().get('/api/stations/two/schedule').json['assignments'] == []


def test_clock_reorder_is_unique_and_cursor_stays_valid(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        clock = move_clock_slot('one', 'morning', 1, 2)
        assert [(slot.position, slot.slot_type) for slot in clock.slots] == [(1, 'ROTATION'), (2, 'CATEGORY')]
        with pytest.raises(ValueError):
            move_clock_slot('one', 'morning', 1, 3)


def test_dst_and_non_dst_resolution(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        station = automation.require_station('one')
        assign('one', 6, '02:00', 'morning')
        before = resolve(station, datetime(2026, 3, 8, 8, 59, tzinfo=timezone.utc))
        after = resolve(station, datetime(2026, 3, 8, 9, 0, tzinfo=timezone.utc))
        assert before.assignment is not None
        assert after.assignment is not None and after.local_time.hour == 3
        assert after.occurrence_key.endswith('2026-03-08')
        assert before.next_transition == datetime(2026, 3, 8, 9, tzinfo=timezone.utc)
        # Two UTC instants share the repeated fall-back wall hour.
        first = resolve(station, datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc))
        second = resolve(station, datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc))
        assert first.local_time.hour == second.local_time.hour == 1
        assert first.local_time.fold == 0 and second.local_time.fold == 1
        assert first.next_transition is not None and first.next_transition > datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc)
        set_timezone('one', 'UTC')
        utc = resolve(station, datetime(2026, 9, 14, 1, tzinfo=timezone.utc))
        assert utc.local_time.utcoffset() == timedelta(0)


def test_fall_back_assignment_does_not_activate_twice(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        station = automation.require_station('one')
        assign('one', 6, '00:00', 'morning')
        repeated = assign('one', 6, '01:30', 'morning')
        first = resolve(station, datetime(2026, 11, 1, 7, 45, tzinfo=timezone.utc))
        second = resolve(station, datetime(2026, 11, 1, 8, 15, tzinfo=timezone.utc))
        assert first.assignment.id == second.assignment.id == repeated.id
        assert first.occurrence_key == second.occurrence_key
        assert second.next_transition == datetime(2026, 11, 8, 7, tzinfo=timezone.utc)


def test_clock_cursor_attribution_recovery_and_next_occurrence(setup):
    app, storage = setup
    with app.app_context():
        make_clock(storage)
        set_default_clock('one', 'morning')
        before = (db.session.query(SelectionDecision).count(), db.session.get(ClockState, automation.require_station('one').id))
        assert [part['clock_slot'] for part in preview_clock('one', 'morning', 3, storage)] == [1, 2, 1]
        assert db.session.query(SelectionDecision).count() == before[0]
        start = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
        first = automation.select_next('one', storage, start)
        assert first.clock.slug == 'morning' and first.clock_slot.position == 1 and first.category.slug == 'power'
        db.session.expire_all()
        second = automation.select_next('one', storage, start + timedelta(seconds=1))
        assert second.clock_slot.position == 2 and second.rotation_id is not None
        state = db.session.get(ClockState, automation.require_station('one').id)
        assert state.next_slot_index == 0
        assert db.session.query(SelectionDecision).filter_by(status='started').count() == 0
        assert automation.playback_started(first.id, 'one', start + timedelta(seconds=2))
        assert first.started_at is not None
        assign('one', 0, '06:00', 'morning')
        monday = automation.select_next('one', storage, start + timedelta(seconds=3))
        assert monday.clock_slot.position == 1
        assign('one', 1, '06:00', 'morning')
        tuesday = automation.select_next('one', storage, start + timedelta(days=1))
        assert tuesday.clock_slot.position == 1
        assert tuesday.schedule_occurrence != monday.schedule_occurrence
        next_week = automation.select_next('one', storage, start + timedelta(days=7))
        assert next_week.clock_slot.position == 1
        assert next_week.schedule_occurrence != monday.schedule_occurrence
        assert app.test_client().post('/api/stations/one/schedule', json={}).status_code in (404, 405)
        assert '/var/lib/freo' not in app.test_client().get('/api/stations/one/clocks/morning').get_data(as_text=True)
        assert app.test_client().post('/api/stations/one/clocks', json={}).status_code in (404, 405)
