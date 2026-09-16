"""Station-scoped category rotations and explainable track selection."""
from app.services.availability import playable
from app.services.availability import tracks_for
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import (AutomationState, ClockState, MediaCategory, Rotation, RotationCursor, RotationSlot,
                        SelectionDecision, Track)
from app.services.media_storage import LocalMediaStorage
from app.services.stations import get_station, validate_slug


def require_station(slug):
    station = get_station(validate_slug(slug))
    if station is None:
        raise ValueError('Station not found')
    return station


def category_create(slug, name, category_slug):
    station = require_station(slug)
    validate_slug(category_slug)
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError('Invalid category name')
    if MediaCategory.query.filter_by(station_id=station.id, slug=category_slug).first():
        raise ValueError('Category already exists')
    category = MediaCategory(station_id=station.id, name=name, slug=category_slug)
    db.session.add(category)
    db.session.commit()
    return category


def category_for(slug, category_slug):
    station = require_station(slug)
    category = MediaCategory.query.filter_by(station_id=station.id, slug=validate_slug(category_slug)).first()
    if category is None:
        raise ValueError('Category not found')
    return category


def assign_track(slug, track_uuid, category_slug, assigned=True, *, commit=True):
    category = category_for(slug, category_slug)
    track = tracks_for(category.station_id).filter_by(uuid=track_uuid).first()
    if track is None:
        raise ValueError('Track not found in station')
    if assigned and track not in category.tracks:
        category.tracks.append(track)
    elif not assigned and track in category.tracks:
        category.tracks.remove(track)
    if commit:
        db.session.commit()
    return track


def rotation_create(slug, name, rotation_slug):
    station = require_station(slug)
    validate_slug(rotation_slug)
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError('Invalid rotation name')
    if Rotation.query.filter_by(station_id=station.id, slug=rotation_slug).first():
        raise ValueError('Rotation already exists')
    rotation = Rotation(station_id=station.id, name=name, slug=rotation_slug)
    db.session.add(rotation)
    db.session.commit()
    return rotation


def rotation_for(slug, rotation_slug):
    station = require_station(slug)
    rotation = Rotation.query.filter_by(station_id=station.id, slug=validate_slug(rotation_slug)).first()
    if rotation is None:
        raise ValueError('Rotation not found')
    return rotation


def add_slot(slug, rotation_slug, category_slug):
    rotation = rotation_for(slug, rotation_slug)
    category = category_for(slug, category_slug)
    if category.station_id != rotation.station_id:
        raise ValueError('Cross-station slot')
    if not category.enabled:
        raise ValueError('Category is disabled')
    position = max((slot.position for slot in rotation.slots), default=0) + 1
    slot = RotationSlot(rotation_id=rotation.id, category_id=category.id, position=position)
    db.session.add(slot)
    db.session.commit()
    return slot


def move_rotation_slot(slug, rotation_slug, from_position, to_position):
    rotation = rotation_for(slug, rotation_slug)
    slots = list(rotation.slots)
    if min(from_position, to_position) < 1 or max(from_position, to_position) > len(slots):
        raise ValueError('Position is outside this rotation')
    moving = slots.pop(from_position - 1)
    slots.insert(to_position - 1, moving)
    temporary_base = max(slot.position for slot in slots) + len(slots) + 1
    for index, slot in enumerate(slots):
        slot.position = temporary_base + index
    db.session.flush()
    for index, slot in enumerate(slots):
        slot.position = index + 1
    db.session.commit()
    db.session.expire(rotation, ['slots'])
    return rotation


def remove_rotation_slot(slug, rotation_slug, position):
    rotation = rotation_for(slug, rotation_slug)
    slots = list(rotation.slots)
    if not 1 <= position <= len(slots):
        raise ValueError('Slot not found')
    if len([slot for slot in slots if slot.enabled]) <= 1 and slots[position - 1].enabled:
        raise ValueError('Disable the rotation before removing its final enabled slot')
    db.session.delete(slots.pop(position - 1))
    db.session.flush()
    base = len(slots) * 2 + 2
    for index, slot in enumerate(slots):
        slot.position = base + index
    db.session.flush()
    for index, slot in enumerate(slots):
        slot.position = index + 1
    db.session.commit()
    db.session.expire(rotation, ['slots'])


def validate_rotation(rotation):
    if not rotation.enabled:
        raise ValueError('Rotation is disabled')
    slots = [slot for slot in rotation.slots if slot.enabled]
    if not slots:
        raise ValueError('Rotation has no enabled slots')
    if any(slot.category is None or slot.category.station_id != rotation.station_id or not slot.category.enabled for slot in slots):
        raise ValueError('Rotation has an unavailable or cross-station category')
    return slots


def state_for(station):
    state = AutomationState.query.filter_by(station_id=station.id).first()
    if state is None:
        state = AutomationState(station_id=station.id)
        db.session.add(state)
        db.session.flush()
    return state


def activate(slug, rotation_slug):
    station = require_station(slug)
    rotation = rotation_for(slug, rotation_slug)
    usable_slots = [slot for slot in rotation.slots if slot.enabled]
    if not rotation.enabled or not usable_slots or any(slot.category.station_id != station.id or not slot.category.enabled for slot in usable_slots):
        raise ValueError('Rotation is structurally invalid')
    state = state_for(station)
    state.active_rotation_id = rotation.id
    state.next_slot_index = 0
    db.session.commit()
    return state


def set_automation(slug, enabled, track_seconds=None, artist_seconds=None):
    station = require_station(slug)
    state = state_for(station)
    if enabled:
        from app.services.schedule import resolve, usable_clock
        has_rotation = bool(state.active_rotation and state.active_rotation.enabled
                            and any(slot.enabled and slot.category.enabled for slot in state.active_rotation.slots))
        has_clock = bool(usable_clock(state.default_clock, station.id) or resolve(station).clock)
        if not has_rotation and not has_clock:
            raise ValueError('Activate a valid rotation or configure a clock first')
    for value in (track_seconds, artist_seconds):
        if value is not None and (value < 0 or value > 86400):
            raise ValueError('Separation must be between 0 and 86400 seconds')
    if track_seconds is not None:
        state.track_separation_seconds = track_seconds
    if artist_seconds is not None:
        state.artist_separation_seconds = artist_seconds
    state.enabled = bool(enabled)
    db.session.commit()
    return state


def artist_key(value):
    return ' '.join((value or '').casefold().split())


def _choose(tracks, history, now, track_seconds, artist_seconds):
    """Deterministic least-recently-started choice, relaxing artist before track."""
    last_track = {}
    last_artist = {}
    for item in history:
        if getattr(item, 'track', None) is None:
            continue
        occurred = item.started_at if item.status == 'started' else item.selected_at
        if occurred is None:
            continue
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if item.status not in ('started', 'selected', 'queued'):
            continue
        last_track[item.track_id] = max(last_track.get(item.track_id, occurred), occurred)
        key = artist_key(item.track.artist)
        last_artist[key] = max(last_artist.get(key, occurred), occurred)
    for relaxation, artist_window, track_window in (
        ('none', artist_seconds, track_seconds),
        ('artist', 0, track_seconds),
        ('track', 0, 0),
    ):
        eligible = [track for track in tracks
                    if (not track_window or track.id not in last_track or now - last_track[track.id] >= timedelta(seconds=track_window))
                    and (not artist_window or artist_key(track.artist) not in last_artist or now - last_artist[artist_key(track.artist)] >= timedelta(seconds=artist_window))]
        if eligible:
            eligible.sort(key=lambda track: (last_track.get(track.id, datetime.min.replace(tzinfo=timezone.utc)), track.id))
            return eligible[0], relaxation, len(eligible)
    return None, 'none', 0


def select_next(slug, storage=None, now=None, programming_signature=None):
    """Lock one station cursor, select one playable object, and commit its decision."""
    station = require_station(slug)
    state = AutomationState.query.filter_by(station_id=station.id).with_for_update().first()
    if state is None or not state.enabled:
        raise ValueError('Automation is not enabled')
    from app.services.programming_refresh import signature,checkpoint
    selected_signature=programming_signature or signature(station,now)
    selected_checkpoint=checkpoint(station)
    now = now or datetime.now(timezone.utc)
    storage = storage or LocalMediaStorage()
    from app.services.schedule import resolve, usable_clock
    programming = resolve(station, now)
    clock = programming.clock or (state.default_clock if usable_clock(state.default_clock, station.id) else None)
    playlist_fallback = False
    if clock:
        slots = [slot for slot in clock.slots if slot.enabled]
        if slots and all(slot.slot_type == 'PLAYLIST' for slot in slots):
            from app.services.playlists import playable_tracks
            if not any(playable_tracks(slot.playlist, station.id, storage) for slot in slots):
                playlist_fallback = True
                for slot in slots:
                    db.session.add(SelectionDecision(station_id=station.id, selected_at=now, status='failed',
                        selection_method='playlist', reason='empty_or_unavailable_playlist', clock_id=clock.id,
                        clock_slot_id=slot.id, schedule_occurrence=programming.occurrence_key))
                fallback = state.default_clock
                clock = fallback if fallback and fallback.id != clock.id and usable_clock(fallback, station.id) else None
    if clock:
        clock_state = ClockState.query.filter_by(station_id=station.id).with_for_update().first()
        if clock_state is None:
            clock_state = ClockState(station_id=station.id)
            db.session.add(clock_state)
            db.session.flush()
        occurrence = (f'fallback:{programming.occurrence_key}:{clock.id}' if playlist_fallback else
                      programming.occurrence_key if programming.clock else f'default:{clock.id}')
        if clock_state.clock_id != clock.id or clock_state.occurrence_key != occurrence:
            clock_state.clock_id = clock.id
            clock_state.occurrence_key = occurrence
            clock_state.next_slot_index = 0
        clock_slots = [slot for slot in clock.slots if slot.enabled]
        if not clock_slots:
            raise ValueError('Active clock has no enabled slots')
        start_clock_index = clock_state.next_slot_index % len(clock_slots)
        for offset in range(len(clock_slots)):
            index = (start_clock_index + offset) % len(clock_slots)
            clock_slot = clock_slots[index]
            clock_state.next_slot_index = (index + 1) % len(clock_slots)
            context = {'clock_id': clock.id, 'clock_slot_id': clock_slot.id,
                       'schedule_assignment_id': programming.assignment.id if programming.assignment else None,
                       'schedule_occurrence': occurrence}
            if clock_slot.slot_type == 'PLAYLIST':
                from app.services.playlists import select_playlist
                decision = select_playlist(station, clock_slot, storage, now, context)
            elif clock_slot.slot_type == 'CATEGORY' and clock_slot.category and clock_slot.category.station_id == station.id:
                decision = _select_category(station, clock_slot.category, state, storage, now, context)
            elif clock_slot.slot_type == 'ROTATION' and clock_slot.rotation and clock_slot.rotation.station_id == station.id:
                decision = _select_rotation(station, clock_slot.rotation, state, storage, now, context)
            elif clock_slot.slot_type == 'CART':
                decision = _select_imaging(station, clock_slot.imaging_asset, None, storage, now, context)
            elif clock_slot.slot_type == 'IMAGING_GROUP':
                decision = _select_imaging(station, None, clock_slot.imaging_group, storage, now, context)
            elif clock_slot.slot_type == 'EVENT_BLOCK' and clock_slot.event_block and clock_slot.event_block.station_id == station.id:
                from app.services.event_blocks import create_execution
                create_execution(clock_slot.event_block, 'CLOCK', clock_slot=clock_slot)
                decision = None
            else:
                decision = None
                db.session.add(SelectionDecision(station_id=station.id, selected_at=now, status='failed',
                                                 reason='invalid_clock_slot', **context))
            if decision:
                decision.programming_signature=selected_signature
                decision.cursor_checkpoint=selected_checkpoint
                db.session.commit()
                return decision
        db.session.commit()
        return None
    if not state.active_rotation or not state.active_rotation.enabled:
        if playlist_fallback:
            db.session.commit()
            return None
        raise ValueError('No active clock or rotation')
    decision = _select_rotation(station, state.active_rotation, state, storage, now, {})
    if decision:
        decision.programming_signature=selected_signature
        decision.cursor_checkpoint=selected_checkpoint
    db.session.commit()
    return decision


def _recent(station, state, now):
    recent_since = now - timedelta(seconds=max(state.track_separation_seconds, state.artist_separation_seconds, 3600))
    return SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.selected_at >= recent_since).order_by(SelectionDecision.id.desc()).limit(500).all()


def _select_imaging(station, asset, group, storage, now, context):
    from app.services.imaging import choose_group, eligible_asset
    if group is not None:
        asset, relaxation, count = choose_group(group, station.id, storage, now)
        reason = 'empty_or_disabled_imaging_group' if asset is None else None
        method = 'imaging_group'
    else:
        available = eligible_asset(asset, station.id, storage)
        reason = 'unavailable_cart' if not available else None
        relaxation, count, method = 'none', int(available), 'cart'
    base = dict(station_id=station.id, selected_at=now,
                imaging_asset_id=asset.id if asset else None,
                imaging_group_id=group.id if group else None,
                selection_method=method, **context)
    if reason:
        db.session.add(SelectionDecision(status='failed', reason=reason, **base))
        return None
    decision = SelectionDecision(status='selected', candidate_count=count,
                                 relaxation=relaxation, **base)
    db.session.add(decision)
    return decision


def _select_category(station, category, state, storage, now, context, rotation=None, rotation_slot=None):
    if not category.enabled or category.station_id != station.id:
        reason, tracks = 'disabled_category', []
    else:
        tracks = [track for track in category.tracks if playable(track, station.id)]
        tracks = [track for track in tracks if _exists(storage, track.station.slug, track.storage_key)]
        reason = 'empty_category' if not tracks else ''
    base = dict(station_id=station.id, rotation_id=rotation.id if rotation else None,
                slot_id=rotation_slot.id if rotation_slot else None, category_id=category.id,
                selected_at=now, **context)
    if not tracks:
        db.session.add(SelectionDecision(status='failed', reason=reason, **base))
        return None
    track, relaxation, count = _choose(tracks, _recent(station, state, now), now,
                                       state.track_separation_seconds, state.artist_separation_seconds)
    decision = SelectionDecision(track_id=track.id, status='selected', candidate_count=count,
                                 relaxation=relaxation, **base)
    db.session.add(decision)
    return decision


def _select_rotation(station, rotation, state, storage, now, context):
    if not rotation.enabled or rotation.station_id != station.id:
        return None
    slots = [slot for slot in rotation.slots if slot.enabled]
    if not slots:
        return None
    cursor = state
    if state.active_rotation_id != rotation.id:
        cursor = RotationCursor.query.filter_by(station_id=station.id, rotation_id=rotation.id).with_for_update().first()
        if cursor is None:
            cursor = RotationCursor(station_id=station.id, rotation_id=rotation.id, next_slot_index=0)
            db.session.add(cursor)
            db.session.flush()
    start_index = cursor.next_slot_index % len(slots)
    for offset in range(len(slots)):
        slot_index = (start_index + offset) % len(slots)
        slot = slots[slot_index]
        cursor.next_slot_index = (slot_index + 1) % len(slots)
        decision = _select_category(station, slot.category, state, storage, now, context, rotation, slot)
        if decision:
            return decision
    return None


def _exists(storage, slug, key):
    try:
        storage.regular_file(slug, key)
        return True
    except (OSError, ValueError):
        return False


def playback_started(decision_id, slug, now=None):
    decision = SelectionDecision.query.filter_by(id=decision_id).first()
    if decision is None or decision.station.slug != slug or decision.status not in ('selected', 'submitting', 'queued', 'failed'):
        return False
    decision.status = 'started'
    decision.started_at = now or datetime.now(timezone.utc)
    if decision.track_id and decision.station.automation and decision.station.automation.cued_track_id == decision.track_id:
        decision.station.automation.cued_track_id = None
    from app.services.event_blocks import confirm_item_started
    confirm_item_started(decision, decision.started_at)
    from app.models import TimedEventOccurrence
    occurrence = TimedEventOccurrence.query.filter_by(selection_decision_id=decision.id).first()
    if occurrence and occurrence.state != 'STARTED':
        occurrence.state = 'STARTED'
        occurrence.started_at = decision.started_at
        occurrence.failure_reason = None
    if decision.reason in ('playout_restarted', 'request_not_started'):
        decision.reason = 'late_event_confirmation'
    db.session.commit()
    return True


def preview(slug, count=10, storage=None, now=None, rotation_slug=None):
    """Simulate cursor and recent selections entirely in memory."""
    from types import SimpleNamespace
    station = require_station(slug)
    state = station.automation
    if state is None:
        raise ValueError('No automation state')
    rotation = rotation_for(slug, rotation_slug) if rotation_slug else state.active_rotation
    if rotation is None:
        raise ValueError('No active rotation')
    slots = [slot for slot in rotation.slots if slot.enabled]
    if not slots:
        raise ValueError('No enabled rotation slots')
    storage = storage or LocalMediaStorage()
    now = now or datetime.now(timezone.utc)
    history = SelectionDecision.query.filter_by(station_id=station.id).order_by(SelectionDecision.id.desc()).limit(500).all()
    output = []
    cursor = state.next_slot_index if state.active_rotation_id == rotation.id else 0
    for index in range(count):
        slot = slots[cursor % len(slots)]
        cursor += 1
        tracks = [track for track in slot.category.tracks if slot.category.enabled and playable(track, station.id) and _exists(storage, track.station.slug, track.storage_key)]
        track, relaxation, candidates = _choose(tracks, history, now, state.track_separation_seconds, state.artist_separation_seconds)
        output.append({'slot': slot.position, 'category': slot.category.slug,
                       'track': track.uuid if track else None, 'relaxation': relaxation,
                       'candidate_count': candidates})
        if track:
            history.insert(0, SimpleNamespace(track=track, track_id=track.id, status='selected', selected_at=now, started_at=None))
    return output
