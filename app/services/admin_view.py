"""Read-only presentation data for the authenticated operations pages."""
from app.services.availability import tracks_for
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import joinedload

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


def format_station_time(value, zone, short=False, offset=False):
    if not value:
        return '—'
    pattern = '%H:%M' if short else '%d %b %Y · %H:%M:%S'
    if offset: pattern += ' %Z (%z)'
    return aware(value).astimezone(ZoneInfo(zone)).strftime(pattern)


def worker_health(station):
    now = datetime.now(timezone.utc)
    global_beat = db.session.get(AutomationHeartbeat, 1)
    station_beat = station.automation.worker_heartbeat_at if station.automation else None
    global_ok = bool(global_beat and (now - aware(global_beat.seen_at)).total_seconds() <= 15)
    station_ok = bool(station_beat and (now - aware(station_beat)).total_seconds() <= 15)
    return {'global': 'healthy' if global_ok else 'unavailable',
            'station': 'healthy' if station_ok else 'unavailable',
            'last_seen': station_beat}


def history_query(station):
    """The same confirmed-start scope and order for the screen and download."""
    from app.models import TimedEventOccurrence
    return (SelectionDecision.query.filter_by(station_id=station.id, status='started')
            .options(joinedload(SelectionDecision.track), joinedload(SelectionDecision.imaging_asset),
                     joinedload(SelectionDecision.clock), joinedload(SelectionDecision.clock_slot),
                     joinedload(SelectionDecision.timed_event_occurrence).joinedload(TimedEventOccurrence.event))
            .order_by(SelectionDecision.started_at.desc(), SelectionDecision.id.desc()))


def latest_rows(station, limit=30):
    return history_query(station).limit(limit).all()


def history_entries(station, limit=None):
    rotations = dict(db.session.query(Rotation.id, Rotation.name).filter_by(station_id=station.id).all())
    query = history_query(station)
    if limit is not None:
        query = query.limit(limit)
    for row in query.yield_per(250):
        occurrence = row.timed_event_occurrence
        event = occurrence.event if occurrence else None
        started = aware(row.started_at)
        scheduled = aware(occurrence.scheduled_for_utc) if occurrence else None
        yield dict(decision_id=row.id, station=station.name, timezone=station.timezone,
            started_at_utc=started.isoformat() if started else '',
            started_at_local=started.astimezone(ZoneInfo(station.timezone)).isoformat() if started else '',
            title=row.track.title if row.track else row.imaging_asset.name if row.imaging_asset else 'Audio unavailable',
            artist=row.track.artist if row.track else row.imaging_asset.asset_type.replace('_', ' ').title() if row.imaging_asset else '',
            source='EVENT' if occurrence else 'MANUAL' if row.admin_user_id else 'AUTO',
            event=event.name if event else '', timing_mode=event.timing_mode if event else '',
            scheduled_at_utc=scheduled.isoformat() if scheduled else '',
            scheduled_at_local=scheduled.astimezone(ZoneInfo(station.timezone)).isoformat() if scheduled else '',
            clock=row.clock.name if row.clock else '',
            slot=row.clock_slot.position if row.clock_slot else '',
            slot_type=row.clock_slot.slot_type if row.clock_slot else '',
            rotation=rotations.get(row.rotation_id, 'Rotation removed') if row.rotation_id else '',
            timing_offset_seconds=occurrence.timing_offset_seconds if occurrence else None,
            relaxation=row.relaxation if not occurrence else '')


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
        return {'history': list(history_entries(station, 100))}
    return {}
