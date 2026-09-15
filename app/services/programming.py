"""Shared station-scoped programming mutations used by the browser and CLI."""
from app.extensions import db
from app.models import Clock, MediaCategory, Rotation, ScheduleAssignment, Track
from app.services.automation import category_for, rotation_for, validate_rotation, require_station
from app.services.clocks import clock_for, validate_clock


def clean_text(value, limit, required=False):
    value = ''.join(ch for ch in (value or '').strip() if ch.isprintable())
    if len(value) > limit or (required and not value):
        raise ValueError('Enter a valid value of at most %d characters' % limit)
    return value


def update_resource(slug, kind, resource_slug, *, name, description):
    item = {'category': category_for, 'rotation': rotation_for, 'clock': clock_for}[kind](slug, resource_slug)
    item.name = clean_text(name, 120, True)
    item.description = clean_text(description, 500)
    db.session.commit()
    return item


def set_resource_enabled(slug, kind, resource_slug, enabled):
    station = require_station(slug)
    item = {'category': category_for, 'rotation': rotation_for, 'clock': clock_for}[kind](slug, resource_slug)
    if not enabled:
        if kind == 'category':
            active = station.automation and station.automation.active_rotation
            default = station.automation and station.automation.default_clock
            if (active and any(s.enabled and s.category_id == item.id for s in active.slots)) or (default and any(s.enabled and s.category_id == item.id for s in default.slots)) or any(s.enabled and s.category_id == item.id for r in Rotation.query.filter_by(station_id=station.id, enabled=True) for s in r.slots) or any(s.enabled and s.category_id == item.id for c in Clock.query.filter_by(station_id=station.id, enabled=True) for s in c.slots):
                raise ValueError('This category is referenced by enabled programming')
        elif kind == 'rotation':
            if station.automation and station.automation.active_rotation_id == item.id:
                raise ValueError('This rotation is active; activate another first')
            if any(s.enabled and s.rotation_id == item.id for c in Clock.query.filter_by(station_id=station.id) for s in c.slots):
                raise ValueError('This rotation is referenced by a clock')
        elif kind == 'clock':
            if station.automation and station.automation.default_clock_id == item.id:
                raise ValueError('This clock is the station default')
            if ScheduleAssignment.query.filter_by(station_id=station.id, clock_id=item.id, enabled=True).first():
                raise ValueError('This clock has weekly assignments')
    item.enabled = bool(enabled)
    if enabled:
        try:
            if kind == 'rotation':
                validate_rotation(item)
            elif kind == 'clock':
                validate_clock(item)
        except ValueError:
            db.session.rollback()
            raise
    db.session.commit()
    return item


def set_membership(slug, category_slug, track_uuids, assigned):
    category = category_for(slug, category_slug)
    unique = list(dict.fromkeys(track_uuids))
    if not unique or len(unique) > 100:
        raise ValueError('Choose between 1 and 100 tracks')
    tracks = Track.query.filter(Track.station_id == category.station_id, Track.uuid.in_(unique)).all()
    if len(tracks) != len(unique):
        raise ValueError('A selected track does not belong to this station')
    for track in tracks:
        if track.decommissioned_at:
            raise ValueError('A selected track is decommissioned')
        if assigned and track not in category.tracks:
            category.tracks.append(track)
        elif not assigned and track in category.tracks:
            category.tracks.remove(track)
    db.session.commit()
    return tracks


def set_slot_enabled(slug, kind, resource_slug, position, enabled):
    item = rotation_for(slug, resource_slug) if kind == 'rotation' else clock_for(slug, resource_slug)
    slot = next((s for s in item.slots if s.position == position), None)
    if slot is None:
        raise ValueError('Slot not found')
    if not enabled and len([s for s in item.slots if s.enabled]) <= 1 and slot.enabled:
        raise ValueError('Disable the parent before disabling its final slot')
    slot.enabled = bool(enabled)
    target = slot.category if kind == 'rotation' or slot.slot_type == 'CATEGORY' else (
        slot.rotation if slot.slot_type == 'ROTATION' else
        slot.imaging_asset if slot.slot_type == 'CART' else slot.imaging_group if slot.slot_type == 'IMAGING_GROUP' else slot.event_block)
    if enabled and (target is None or not target.enabled):
        db.session.rollback()
        raise ValueError('Slot target is disabled')
    db.session.commit()
    return slot


def assignment_for(slug, assignment_id):
    station = require_station(slug)
    row = ScheduleAssignment.query.filter_by(station_id=station.id, id=assignment_id).first()
    if row is None:
        raise ValueError('Assignment not found')
    return row


def candidate_warnings(resource):
    """Cheap DB eligibility hints; file existence remains the selector's authority."""
    warnings = []
    for slot in resource.slots:
        if not slot.enabled:
            continue
        categories = ([slot.category] if slot.category else
                      [part.category for part in slot.rotation.slots if part.enabled] if getattr(slot, 'rotation', None) else [])
        for category in categories:
            if category is None or not category.enabled:
                warnings.append(f'Slot {slot.position}: target category is unavailable')
            elif not any(track.enabled and track.ingest_status == 'accepted' and not track.decommissioned_at
                         for track in category.tracks):
                warnings.append(f'Slot {slot.position}: {category.name} has no enabled accepted tracks')
    return warnings
