"""Administrative clock and weekly schedule operations; never invoked from public mutations."""
from datetime import datetime, timezone

from app.extensions import db
from app.models import Clock, ClockSlot, ScheduleAssignment
from app.services.automation import category_for, require_station, rotation_for, state_for
from app.services.schedule import parse_local_time, resolve, usable_clock, validate_timezone
from app.services.stations import validate_slug


def set_timezone(slug, timezone_name):
    station = require_station(slug)
    station.timezone = validate_timezone(timezone_name)
    db.session.commit()
    return station


def clock_for(slug, clock_slug):
    station = require_station(slug)
    clock = Clock.query.filter_by(station_id=station.id, slug=validate_slug(clock_slug)).first()
    if clock is None:
        raise ValueError('Clock not found')
    return clock


def create_clock(slug, name, clock_slug):
    station = require_station(slug)
    validate_slug(clock_slug)
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError('Invalid clock name')
    if Clock.query.filter_by(station_id=station.id, slug=clock_slug).first():
        raise ValueError('Clock already exists')
    clock = Clock(station_id=station.id, name=name, slug=clock_slug)
    db.session.add(clock)
    db.session.commit()
    return clock


def add_clock_slot(slug, clock_slug, slot_type, target):
    clock = clock_for(slug, clock_slug)
    kind = slot_type.upper()
    if kind == 'ROTATION':
        rotation = rotation_for(slug, target)
        target_fields = {'rotation_id': rotation.id}
    elif kind == 'CATEGORY':
        category = category_for(slug, target)
        target_fields = {'category_id': category.id}
    else:
        raise ValueError('Supported clock slot types: ROTATION, CATEGORY')
    position = max((slot.position for slot in clock.slots), default=0) + 1
    slot = ClockSlot(clock_id=clock.id, position=position, slot_type=kind, **target_fields)
    db.session.add(slot)
    db.session.commit()
    return slot


def move_clock_slot(slug, clock_slug, from_position, to_position):
    clock = clock_for(slug, clock_slug)
    slots = list(clock.slots)
    if min(from_position, to_position) < 1 or max(from_position, to_position) > len(slots):
        raise ValueError('Position is outside this clock')
    moving = slots.pop(from_position - 1)
    slots.insert(to_position - 1, moving)
    temporary_base = max(slot.position for slot in slots) + len(slots) + 1
    for index, slot in enumerate(slots):
        slot.position = temporary_base + index
    db.session.flush()
    for index, slot in enumerate(slots):
        slot.position = index + 1
    db.session.commit()
    db.session.expire(clock, ['slots'])
    return clock


def validate_clock(clock):
    if not clock.enabled:
        raise ValueError('Clock is disabled')
    slots = [slot for slot in clock.slots if slot.enabled]
    if not slots:
        raise ValueError('Clock has no enabled slots')
    for slot in slots:
        target = slot.rotation if slot.slot_type == 'ROTATION' else slot.category if slot.slot_type == 'CATEGORY' else None
        if target is None or target.station_id != clock.station_id or not target.enabled:
            raise ValueError(f'Clock slot {slot.position} has an unavailable or cross-station target')
        if slot.slot_type == 'ROTATION' and not any(item.enabled for item in target.slots):
            raise ValueError(f'Rotation in clock slot {slot.position} has no enabled slots')
    return slots


def set_default_clock(slug, clock_slug=None):
    station = require_station(slug)
    clock = clock_for(slug, clock_slug) if clock_slug else None
    if clock:
        validate_clock(clock)
    state = state_for(station)
    state.default_clock_id = clock.id if clock else None
    db.session.commit()
    return state


def assign(slug, weekday, local_time, clock_slug):
    station = require_station(slug)
    if not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise ValueError('Weekday must be 0 (Monday) through 6 (Sunday)')
    parsed_time = parse_local_time(local_time)
    clock = clock_for(slug, clock_slug)
    validate_clock(clock)
    if ScheduleAssignment.query.filter_by(station_id=station.id, weekday=weekday, start_time=parsed_time).first():
        raise ValueError('An assignment already exists at this station-local time')
    row = ScheduleAssignment(station_id=station.id, weekday=weekday, start_time=parsed_time, clock_id=clock.id)
    db.session.add(row)
    db.session.commit()
    return row


def remove_assignment(slug, assignment_id):
    station = require_station(slug)
    row = ScheduleAssignment.query.filter_by(id=assignment_id, station_id=station.id).first()
    if row is None:
        raise ValueError('Assignment not found')
    db.session.delete(row)
    db.session.commit()


def current(slug, at=None):
    station = require_station(slug)
    resolution = resolve(station, at)
    default = station.automation.default_clock if station.automation else None
    clock = resolution.clock or (default if usable_clock(default, station.id) else None)
    return {'timezone': station.timezone, 'local_time': resolution.local_time.isoformat(),
            'clock': clock.slug if clock else None,
            'source': 'weekly' if resolution.clock else 'default' if clock else 'rotation',
            'assignment_id': resolution.assignment.id if resolution.clock else None,
            'occurrence': resolution.occurrence_key if resolution.clock else f'default:{clock.id}' if clock else None,
            'next_transition': resolution.next_transition.isoformat() if resolution.next_transition else None}


def preview_clock(slug, clock_slug, count=10, storage=None, at=None):
    """Simulate selections without advancing either durable cursor or history."""
    from types import SimpleNamespace
    from app.models import ClockState, RotationCursor, SelectionDecision
    from app.services.automation import _choose, _exists
    from app.services.media_storage import LocalMediaStorage
    station = require_station(slug)
    clock = clock_for(slug, clock_slug)
    slots = validate_clock(clock)
    state = station.automation
    if state is None:
        raise ValueError('Automation state is not configured')
    storage = storage or LocalMediaStorage()
    now = at or datetime.now(timezone.utc)
    history = SelectionDecision.query.filter_by(station_id=station.id).order_by(SelectionDecision.id.desc()).limit(500).all()
    live_cursor = db.session.get(ClockState, station.id)
    clock_index = live_cursor.next_slot_index if live_cursor and live_cursor.clock_id == clock.id else 0
    rotation_indexes = {}
    output = []
    for _ in range(count):
        slot = slots[clock_index % len(slots)]
        clock_index += 1
        if slot.slot_type == 'ROTATION':
            rotation = slot.rotation
            rotation_slots = [part for part in rotation.slots if part.enabled]
            if not rotation_slots:
                raise ValueError('Referenced rotation is empty')
            if rotation.id not in rotation_indexes:
                if state.active_rotation_id == rotation.id:
                    rotation_indexes[rotation.id] = state.next_slot_index
                else:
                    cursor = RotationCursor.query.filter_by(station_id=station.id, rotation_id=rotation.id).first()
                    rotation_indexes[rotation.id] = cursor.next_slot_index if cursor else 0
            part = rotation_slots[rotation_indexes[rotation.id] % len(rotation_slots)]
            rotation_indexes[rotation.id] += 1
            category = part.category
        else:
            category = slot.category
        tracks = [track for track in category.tracks if category.enabled and track.station_id == station.id
                  and track.enabled and track.ingest_status == 'accepted' and _exists(storage, slug, track.storage_key)]
        track, relaxation, candidates = _choose(tracks, history, now, state.track_separation_seconds,
                                                state.artist_separation_seconds) if tracks else (None, 'none', 0)
        output.append({'clock_slot': slot.position, 'type': slot.slot_type,
                       'category': category.slug, 'track': track.uuid if track else None,
                       'artist': track.artist if track else None, 'relaxation': relaxation,
                       'candidate_count': candidates})
        if track:
            history.insert(0, SimpleNamespace(track=track, track_id=track.id, status='selected',
                                              selected_at=now, started_at=None))
    return output
