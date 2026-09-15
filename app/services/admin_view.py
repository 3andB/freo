"""Read-only presentation data for the authenticated operations pages."""
from app.services.availability import tracks_for
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.extensions import db
from app.models import (AutomationHeartbeat, Clock, ClockState, MediaCategory,
                        Rotation, RotationCursor, ScheduleAssignment,
                        SelectionDecision, Station, Track)
from app.routes.stations import observed_status
from app.services.clocks import current


DAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')


def aware(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc) if value else None


def iso(value):
    value = aware(value)
    return value.isoformat() if value else None


def format_station_time(value, zone, short=False):
    if not value:
        return '—'
    return aware(value).astimezone(ZoneInfo(zone)).strftime('%H:%M' if short else '%d %b %Y · %H:%M:%S')


def worker_health(station):
    now = datetime.now(timezone.utc)
    global_beat = db.session.get(AutomationHeartbeat, 1)
    station_beat = station.automation.worker_heartbeat_at if station.automation else None
    global_ok = bool(global_beat and (now - aware(global_beat.seen_at)).total_seconds() <= 15)
    station_ok = bool(station_beat and (now - aware(station_beat)).total_seconds() <= 15)
    return {'global': 'healthy' if global_ok else 'unavailable',
            'station': 'healthy' if station_ok else 'unavailable',
            'last_seen': station_beat}


def latest_rows(station, limit=30):
    return (SelectionDecision.query.filter_by(station_id=station.id, status='started')
            .order_by(SelectionDecision.started_at.desc(), SelectionDecision.id.desc())
            .limit(limit).all())


def pending_rows(station, limit=5):
    return (SelectionDecision.query.filter_by(station_id=station.id, status='queued')
            .order_by(SelectionDecision.selected_at.asc(), SelectionDecision.id.asc())
            .limit(limit).all())


def library_counts(station):
    accepted = tracks_for(station.id).filter_by(ingest_status='accepted').count()
    enabled = tracks_for(station.id).filter_by(ingest_status='accepted', enabled=True).count()
    categories = db.session.query(func.count(MediaCategory.id)).filter_by(station_id=station.id).scalar() or 0
    return {'accepted': accepted, 'enabled': enabled, 'categories': categories}


def context(station, *, history_limit=30, with_status=True):
    programming = current(station.slug)
    history = latest_rows(station, history_limit)
    rotation_names = {row.id: row.name for row in Rotation.query.filter_by(station_id=station.id).all()}
    state = station.automation
    clock = Clock.query.filter_by(station_id=station.id, slug=programming['clock']).first() if programming['clock'] else None
    clock_state = db.session.get(ClockState, station.id)
    active_slots = [slot for slot in clock.slots if slot.enabled] if clock else []
    next_slot = None
    if clock_state and active_slots and clock_state.occurrence_key == programming['occurrence']:
        next_slot = active_slots[clock_state.next_slot_index % len(active_slots)]
    local_today = datetime.fromisoformat(programming['local_time']).weekday()
    today = (ScheduleAssignment.query.filter_by(station_id=station.id, weekday=local_today)
             .order_by(ScheduleAssignment.start_time).all())
    observed = observed_status(station) if with_status else None
    from app.services.live_assist import status as live_status
    return {'live': live_status(station), 'station': station, 'observed': observed, 'programming': programming,
            'automation': state, 'worker': worker_health(station),
            'history': history, 'rotation_names': rotation_names,
            'now_playing': history[0] if history else None,
            'pending': pending_rows(station), 'counts': library_counts(station),
            'clock': clock, 'next_slot': next_slot, 'today': today}


def section_data(station, section):
    if section == 'media':
        return {'tracks': tracks_for(station.id).order_by(Track.title).limit(100).all(),
                'count': library_counts(station)}
    if section == 'categories':
        rows = MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name).all()
        return {'categories': rows}
    if section == 'rotations':
        return {'rotations': Rotation.query.filter_by(station_id=station.id).order_by(Rotation.name).all(),
                'cursors': {row.rotation_id: row.next_slot_index for row in RotationCursor.query.filter_by(station_id=station.id)}}
    if section == 'clocks':
        return {'clocks': Clock.query.filter_by(station_id=station.id).order_by(Clock.name).all()}
    if section == 'schedule':
        rows = (ScheduleAssignment.query.filter_by(station_id=station.id)
                .order_by(ScheduleAssignment.weekday, ScheduleAssignment.start_time).all())
        return {'days': [(name, [row for row in rows if row.weekday == index]) for index, name in enumerate(DAY_NAMES)]}
    if section == 'history':
        return {'history': latest_rows(station, 100)}
    return {}
