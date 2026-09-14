"""Station-scoped category rotations and explainable track selection."""
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import (AutomationState, MediaCategory, Rotation, RotationSlot,
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


def assign_track(slug, track_uuid, category_slug, assigned=True):
    category = category_for(slug, category_slug)
    track = Track.query.filter_by(station_id=category.station_id, uuid=track_uuid).first()
    if track is None:
        raise ValueError('Track not found in station')
    if assigned and track not in category.tracks:
        category.tracks.append(track)
    elif not assigned and track in category.tracks:
        category.tracks.remove(track)
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
    position = max((slot.position for slot in rotation.slots), default=0) + 1
    slot = RotationSlot(rotation_id=rotation.id, category_id=category.id, position=position)
    db.session.add(slot)
    db.session.commit()
    return slot


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
    if enabled and (not state.active_rotation or not state.active_rotation.enabled or not any(slot.enabled and slot.category.enabled for slot in state.active_rotation.slots)):
        raise ValueError('Activate a valid rotation first')
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
        if item.track is None:
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


def select_next(slug, storage=None, now=None):
    """Lock one station cursor, select at most one track, and commit its audit row."""
    station = require_station(slug)
    state = AutomationState.query.filter_by(station_id=station.id).with_for_update().first()
    if state is None or not state.enabled or not state.active_rotation or not state.active_rotation.enabled:
        raise ValueError('Automation is not enabled')
    slots = [slot for slot in state.active_rotation.slots if slot.enabled]
    if not slots:
        raise ValueError('Active rotation has no enabled slots')
    now = now or datetime.now(timezone.utc)
    storage = storage or LocalMediaStorage()
    recent_since = now - timedelta(seconds=max(state.track_separation_seconds, state.artist_separation_seconds, 3600))
    history = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.selected_at >= recent_since).order_by(SelectionDecision.id.desc()).limit(500).all()
    start_index = state.next_slot_index % len(slots)
    for offset in range(len(slots)):
        slot_index = (start_index + offset) % len(slots)
        slot = slots[slot_index]
        state.next_slot_index = (slot_index + 1) % len(slots)
        if slot.category.station_id != station.id or not slot.category.enabled:
            reason = 'disabled_category'
            tracks = []
        else:
            tracks = [track for track in slot.category.tracks if track.station_id == station.id and track.enabled and track.ingest_status == 'accepted']
            tracks = [track for track in tracks if _exists(storage, slug, track.storage_key)]
            reason = 'empty_category' if not tracks else ''
        if not tracks:
            db.session.add(SelectionDecision(station_id=station.id, rotation_id=state.active_rotation_id,
                slot_id=slot.id, category_id=slot.category_id, status='failed', reason=reason, selected_at=now))
            continue
        track, relaxation, count = _choose(tracks, history, now, state.track_separation_seconds, state.artist_separation_seconds)
        decision = SelectionDecision(station_id=station.id, rotation_id=state.active_rotation_id,
            slot_id=slot.id, category_id=slot.category_id, track_id=track.id,
            status='selected', candidate_count=count, relaxation=relaxation, selected_at=now)
        db.session.add(decision)
        db.session.commit()
        return decision
    db.session.commit()
    return None


def _exists(storage, slug, key):
    try:
        storage.regular_file(slug, key)
        return True
    except (OSError, ValueError):
        return False


def playback_started(decision_id, slug, now=None):
    decision = SelectionDecision.query.filter_by(id=decision_id).first()
    if decision is None or decision.station.slug != slug or decision.status not in ('selected', 'queued', 'failed'):
        return False
    decision.status = 'started'
    decision.started_at = now or datetime.now(timezone.utc)
    if decision.reason in ('playout_restarted', 'request_not_started'):
        decision.reason = 'late_event_confirmation'
    db.session.commit()
    return True


def preview(slug, count=10, storage=None, now=None):
    """Simulate cursor and recent selections entirely in memory."""
    from types import SimpleNamespace
    station = require_station(slug)
    state = station.automation
    if state is None or state.active_rotation is None:
        raise ValueError('No active rotation')
    slots = [slot for slot in state.active_rotation.slots if slot.enabled]
    if not slots:
        raise ValueError('No enabled rotation slots')
    storage = storage or LocalMediaStorage()
    now = now or datetime.now(timezone.utc)
    history = SelectionDecision.query.filter_by(station_id=station.id).order_by(SelectionDecision.id.desc()).limit(500).all()
    output = []
    cursor = state.next_slot_index
    for index in range(count):
        slot = slots[cursor % len(slots)]
        cursor += 1
        tracks = [track for track in slot.category.tracks if slot.category.enabled and track.station_id == station.id
                  and track.enabled and track.ingest_status == 'accepted' and _exists(storage, slug, track.storage_key)]
        track, relaxation, candidates = _choose(tracks, history, now, state.track_separation_seconds, state.artist_separation_seconds)
        output.append({'slot': slot.position, 'category': slot.category.slug,
                       'track': track.uuid if track else None, 'relaxation': relaxation,
                       'candidate_count': candidates})
        if track:
            history.insert(0, SimpleNamespace(track=track, track_id=track.id, status='selected', selected_at=now, started_at=None))
    return output
