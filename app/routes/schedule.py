"""Public, read-only programming metadata."""
from datetime import datetime, timezone

from flask import Blueprint, jsonify

from app.models import Clock, ScheduleAssignment
from app.services.clocks import current
from app.services.stations import get_station

schedule_blueprint = Blueprint('schedule', __name__)


def station_or_none(slug):
    try:
        return get_station(slug)
    except ValueError:
        return None


@schedule_blueprint.get('/api/stations/<slug>/clocks')
def clocks(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    rows = Clock.query.filter_by(station_id=station.id).order_by(Clock.name).all()
    return jsonify(clocks=[{'slug': row.slug, 'name': row.name, 'enabled': row.enabled,
                            'slots': len(row.slots)} for row in rows])


@schedule_blueprint.get('/api/stations/<slug>/clocks/<clock_slug>')
def clock(slug, clock_slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    row = Clock.query.filter_by(station_id=station.id, slug=clock_slug).first()
    if row is None:
        return jsonify(status='not_found'), 404
    return jsonify(slug=row.slug, name=row.name, enabled=row.enabled,
                   slots=[{'position': slot.position, 'type': slot.slot_type.lower(),
                           'target': slot.rotation.slug if slot.rotation else slot.category.slug if slot.category else None,
                           'enabled': slot.enabled} for slot in row.slots])


@schedule_blueprint.get('/api/stations/<slug>/schedule')
def schedule(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    from app.services.visual_schedule import policy
    configured = policy(station)
    if configured and configured.activated:
        return jsonify(timezone=station.timezone, mode=configured.mode,
                       calendar=configured.calendar if configured.mode == 'CALENDAR' else [],
                       blocks=configured.assignments if configured.mode == 'BLOCKS' else [],
                       simple=configured.live_simple if configured.mode == 'SIMPLE' else None)
    rows = ScheduleAssignment.query.filter_by(station_id=station.id).order_by(ScheduleAssignment.weekday, ScheduleAssignment.start_time).all()
    return jsonify(timezone=station.timezone,
                   assignments=[{'weekday': row.weekday, 'time': row.start_time.strftime('%H:%M'),
                                 'clock': row.clock.slug, 'enabled': row.enabled} for row in rows])


@schedule_blueprint.get('/api/stations/<slug>/schedule/current')
def schedule_current(slug):
    if station_or_none(slug) is None:
        return jsonify(status='not_found'), 404
    return jsonify(current(slug, datetime.now(timezone.utc)))
