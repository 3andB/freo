"""Public read-only automation metadata and heartbeat."""
from datetime import datetime, timezone

from flask import Blueprint, jsonify
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import AutomationHeartbeat, MediaCategory, SelectionDecision
from app.services.stations import get_station
from app.services.clocks import current
from app.models import ClockState

automation_blueprint = Blueprint('automation', __name__)


def station_or_none(slug):
    try:
        return get_station(slug)
    except ValueError:
        return None


def iso(value):
    if value is None:
        return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()


@automation_blueprint.get('/health/automation')
def automation_health():
    try:
        heartbeat = db.session.get(AutomationHeartbeat, 1)
    except SQLAlchemyError:
        return jsonify(status='unavailable'), 503
    if heartbeat is None:
        return jsonify(status='unavailable'), 503
    seen = heartbeat.seen_at.replace(tzinfo=heartbeat.seen_at.tzinfo or timezone.utc)
    if (datetime.now(timezone.utc) - seen).total_seconds() > 15:
        return jsonify(status='unavailable'), 503
    return jsonify(status='ok')


@automation_blueprint.get('/api/stations/<slug>/categories')
def categories(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    rows = MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name).all()
    return jsonify(categories=[{'slug': row.slug, 'name': row.name, 'description': row.description,
                                'enabled': row.enabled, 'track_count': len(row.tracks)} for row in rows])


@automation_blueprint.get('/api/stations/<slug>/rotation')
def rotation(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    state = station.automation
    active = state.active_rotation if state else None
    return jsonify(rotation=None if active is None else {
        'slug': active.slug, 'name': active.name,
        'slots': [{'position': slot.position, 'category': slot.category.slug, 'enabled': slot.enabled} for slot in active.slots]})


@automation_blueprint.get('/api/stations/<slug>/automation/status')
def status(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    state = station.automation
    latest = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.track_id.isnot(None)).order_by(SelectionDecision.id.desc()).first()
    last_started = SelectionDecision.query.filter_by(station_id=station.id, status='started').order_by(SelectionDecision.started_at.desc()).first()
    programming = current(slug)
    cursor = db.session.get(ClockState, station.id)
    return jsonify(enabled=bool(state and state.enabled), active_rotation=state.active_rotation.slug if state and state.active_rotation else None,
                   timezone=programming['timezone'], local_time=programming['local_time'],
                   active_clock=programming['clock'], programming_source=programming['source'],
                   schedule_assignment=programming['assignment_id'], next_transition=programming['next_transition'],
                   next_clock_slot_index=cursor.next_slot_index if cursor and cursor.occurrence_key == programming['occurrence'] else 0,
                   queue_depth=state.observed_queue_depth if state else None, worker_heartbeat=iso(state.worker_heartbeat_at) if state else None,
                   last_selected=iso(latest.selected_at) if latest else None,
                   last_started=iso(last_started.started_at) if last_started else None)


@automation_blueprint.get('/api/stations/<slug>/history')
def history(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    rows = SelectionDecision.query.filter_by(station_id=station.id, status='started').order_by(SelectionDecision.started_at.desc()).limit(100).all()
    return jsonify(history=[{'started_at': iso(row.started_at), 'track': row.track.uuid if row.track else None,
                             'category': row.category.slug if row.category else None,
                             'rotation': row.rotation_id, 'slot': row.slot.position if row.slot else None,
                             'clock': row.clock.slug if row.clock else None,
                             'clock_slot': row.clock_slot.position if row.clock_slot else None,
                             'schedule_assignment': row.schedule_assignment_id,
                             'schedule_occurrence': row.schedule_occurrence,
                             'relaxation': row.relaxation, 'note': row.reason or None} for row in rows])
