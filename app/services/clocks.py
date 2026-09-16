"""Administrative clock and weekly schedule operations; never invoked from public mutations."""
from app.services.availability import playable
from datetime import datetime, timezone

from app.extensions import db
from app.models import Clock, ClockSlot, ScheduleAssignment
from app.services.automation import category_for, require_station, rotation_for, state_for, validate_rotation
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
        validate_rotation(rotation)
        target_fields = {'rotation_id': rotation.id}
    elif kind == 'CATEGORY':
        category = category_for(slug, target)
        if not category.enabled:
            raise ValueError('Category is disabled')
        target_fields = {'category_id': category.id}
    elif kind == 'CART':
        from app.services.imaging import asset_for, eligible_asset
        from app.services.media_storage import LocalMediaStorage
        asset = asset_for(slug, target)
        if not eligible_asset(asset, clock.station_id, LocalMediaStorage()):
            raise ValueError('Cart is unavailable')
        target_fields = {'imaging_asset_id': asset.id}
    elif kind == 'IMAGING_GROUP':
        from app.services.imaging import group_for, choose_group
        group = group_for(slug, target)
        asset, _, _ = choose_group(group, clock.station_id)
        if not asset:
            raise ValueError('Imaging group has no eligible assets')
        target_fields = {'imaging_group_id': group.id}
    elif kind == 'EVENT_BLOCK':
        from app.services.event_blocks import block_for, validate_block
        block = block_for(slug, target)
        if not block.enabled or validate_block(block):
            raise ValueError('Event block is disabled or invalid')
        target_fields = {'event_block_id': block.id}
    else:
        raise ValueError('Supported clock slot types: ROTATION, CATEGORY, CART, IMAGING_GROUP, EVENT_BLOCK')
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


def remove_clock_slot(slug, clock_slug, position):
    clock = clock_for(slug, clock_slug)
    slots = list(clock.slots)
    if not 1 <= position <= len(slots):
        raise ValueError('Slot not found')
    if len([slot for slot in slots if slot.enabled]) <= 1 and slots[position - 1].enabled:
        raise ValueError('Disable the clock before removing its final enabled slot')
    db.session.delete(slots.pop(position - 1))
    db.session.flush()
    base = len(slots) * 2 + 2
    for index, slot in enumerate(slots):
        slot.position = base + index
    db.session.flush()
    for index, slot in enumerate(slots):
        slot.position = index + 1
    db.session.commit()
    db.session.expire(clock, ['slots'])


def update_assignment(slug, assignment_id, weekday, local_time, clock_slug):
    station = require_station(slug)
    row = ScheduleAssignment.query.filter_by(id=assignment_id, station_id=station.id).first()
    if row is None:
        raise ValueError('Assignment not found')
    from app.models import ScheduleProgram
    if ScheduleProgram.query.filter_by(baseline_assignment_id=row.id, enabled=True).first():
        raise ValueError('Restore the weekly baseline in Defaults before editing assignments')

    if not isinstance(weekday, int) or not 0 <= weekday <= 6:
        raise ValueError('Weekday must be Monday through Sunday')
    parsed_time = parse_local_time(local_time)
    clock = clock_for(slug, clock_slug)
    validate_clock(clock)
    existing = ScheduleAssignment.query.filter_by(station_id=station.id, weekday=weekday, start_time=parsed_time).first()
    if existing and existing.id != row.id:
        raise ValueError('An assignment already exists at this station-local time')
    row.weekday, row.start_time, row.clock_id = weekday, parsed_time, clock.id
    db.session.commit()
    return row


def validate_clock(clock):
    if not clock.enabled:
        raise ValueError('Clock is disabled')
    slots = [slot for slot in clock.slots if slot.enabled]
    if not slots:
        raise ValueError('Clock has no enabled slots')
    for slot in slots:
        target = {'ROTATION': slot.rotation, 'CATEGORY': slot.category,
                  'CART': slot.imaging_asset, 'IMAGING_GROUP': slot.imaging_group,
                  'EVENT_BLOCK': slot.event_block, 'PLAYLIST': slot.playlist}.get(slot.slot_type)
        if target is None or target.station_id != clock.station_id or not target.enabled:
            raise ValueError(f'Clock slot {slot.position} has an unavailable or cross-station target')
        if slot.slot_type == 'ROTATION':
            validate_rotation(target)
        elif slot.slot_type == 'CART':
            from app.services.imaging import eligible_asset
            from app.services.media_storage import LocalMediaStorage
            if not eligible_asset(target, clock.station_id, LocalMediaStorage()):
                raise ValueError(f'Clock slot {slot.position} has an unavailable cart')
        elif slot.slot_type == 'IMAGING_GROUP':
            from app.services.imaging import choose_group
            asset, _, _ = choose_group(target, clock.station_id)
            if not asset:
                raise ValueError(f'Clock slot {slot.position} has an empty imaging group')
        elif slot.slot_type == 'EVENT_BLOCK':
            from app.services.event_blocks import validate_block
            if validate_block(target):
                raise ValueError(f'Clock slot {slot.position} has an invalid event block')
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
    from app.models import ScheduleProgram
    if ScheduleProgram.query.filter(ScheduleProgram.station_id == station.id, ScheduleProgram.baseline_assignment_id.isnot(None), ScheduleProgram.enabled.is_(True)).first():
        raise ValueError('Restore the weekly baseline in Defaults before adding assignments')
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
    from app.models import ScheduleProgram
    if ScheduleProgram.query.filter_by(baseline_assignment_id=row.id).first():
        if ScheduleProgram.query.filter_by(baseline_assignment_id=row.id, enabled=True).first():
            raise ValueError('Restore the weekly baseline in Defaults before editing assignments')
        # Inactive conversion rows are historical; keep their source identity.
        row.enabled = False
        db.session.commit()
        return

    db.session.delete(row)
    db.session.commit()


def current(slug, at=None):
    station = require_station(slug)
    resolution = resolve(station, at)
    default = station.automation.default_clock if station.automation else None
    clock = resolution.clock or (default if usable_clock(default, station.id) else None)
    return {'timezone': station.timezone, 'local_time': resolution.local_time.isoformat(),
            'clock': clock.slug if clock else None,
            'source': 'calendar' if resolution.program else 'weekly' if resolution.clock else 'default' if clock else 'rotation',
            'assignment_id': resolution.assignment.id if resolution.assignment else None,
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
    playlist_states = {}
    output = []
    for _ in range(count):
        slot = slots[clock_index % len(slots)]
        clock_index += 1
        if slot.slot_type == 'PLAYLIST':
            from app.services.playlists import playable_tracks, advance
            tracks = playable_tracks(slot.playlist, station.id, storage)
            track = None
            if tracks:
                track, playlist_states[slot.id] = advance(slot.playlist, tracks, playlist_states.get(slot.id, {}))
            output.append(dict(clock_slot=slot.position, type=slot.slot_type, track=track.uuid if track else None,
                               artist=track.artist if track else None, candidate_count=len(tracks), relaxation='none'))
            continue
        if slot.slot_type == 'EVENT_BLOCK':
            output.append({'clock_slot': slot.position, 'type': slot.slot_type,
                           'event_block': slot.event_block.slug, 'name': slot.event_block.name,
                           'duration_ms': slot.event_block.duration_ms})
            continue
        if slot.slot_type in ('CART', 'IMAGING_GROUP'):
            from app.services.imaging import choose_group, eligible_asset
            if slot.slot_type == 'CART':
                asset = slot.imaging_asset if eligible_asset(slot.imaging_asset, station.id, storage) else None
                relaxation, candidates = 'none', int(asset is not None)
            else:
                asset, relaxation, candidates = choose_group(slot.imaging_group, station.id, storage, now, history)
            output.append({'clock_slot': slot.position, 'type': slot.slot_type,
                           'imaging_asset': asset.uuid if asset else None,
                           'imaging_group': slot.imaging_group.slug if slot.imaging_group else None,
                           'cart_code': asset.cart_code if asset else None,
                           'name': asset.name if asset else None, 'relaxation': relaxation,
                           'candidate_count': candidates})
            if asset:
                history.insert(0, SimpleNamespace(imaging_asset_id=asset.id, status='selected',
                    selected_at=now, started_at=None))
            continue
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
        tracks = [track for track in category.tracks if category.enabled and playable(track, station.id) and _exists(storage, track.station.slug, track.storage_key)]
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
