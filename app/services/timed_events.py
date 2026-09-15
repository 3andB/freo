"""Exact-time event definitions, bounded occurrence generation, and execution state."""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import ImagingAsset, SelectionDecision, TimedEvent, TimedEventOccurrence, Track
from app.services.media_storage import LocalMediaStorage
from app.services.schedule import _wall_to_utc, utc_instant, validate_timezone
from app.services.stations import get_station

MODES = ('SOFT', 'HARD', 'NON_INTERRUPTING')
RECURRENCES = ('ONE_TIME', 'WEEKLY')
CONTENTS = ('TRACK', 'IMAGING_ASSET')
MISSED = ('SKIP', 'PLAY_LATE')
INTERRUPTS = ('NEVER', 'MUSIC_ONLY')


def _clean(value, limit, required=False):
    value = ''.join(ch for ch in (value or '').strip() if ch.isprintable())
    if len(value) > limit or required and not value:
        raise ValueError(f'Enter a value of at most {limit} characters')
    return value


def event_for(slug, identifier):
    station = get_station(slug)
    if station is None:
        raise ValueError('Station not found')
    row = TimedEvent.query.filter_by(station_id=station.id, uuid=identifier).first()
    if row is None:
        raise ValueError('Event not found')
    return row


def _target(station, content_type, identifier):
    if content_type == 'TRACK':
        row = Track.query.filter_by(station_id=station.id, uuid=identifier).first()
    elif content_type == 'IMAGING_ASSET':
        row = ImagingAsset.query.filter_by(station_id=station.id, uuid=identifier).first()
    else:
        raise ValueError('Unsupported event content type')
    if row is None:
        raise ValueError('Event content belongs to another station or does not exist')
    return row


def _integer(value, low, high, label):
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} is invalid') from error
    if not low <= result <= high:
        raise ValueError(f'{label} must be between {low} and {high}')
    return result


def parse_event_time(value):
    try:
        parsed = datetime.strptime(value, '%H:%M:%S' if len(value or '') == 8 else '%H:%M').time()
    except (TypeError, ValueError) as error:
        raise ValueError('Time must be HH:MM or HH:MM:SS') from error
    return parsed


def save_event(slug, *, identifier=None, name, description='', timing_mode, recurrence_type,
               content_type, content_identifier, local_date=None, local_time=None, weekday=None,
               early_tolerance_seconds=0, late_tolerance_seconds=10, missed_policy='SKIP',
               interrupt_policy='NEVER', priority=100):
    station = get_station(slug)
    if station is None:
        raise ValueError('Station not found')
    if timing_mode not in MODES or recurrence_type not in RECURRENCES or missed_policy not in MISSED or interrupt_policy not in INTERRUPTS:
        raise ValueError('Unsupported event option')
    if timing_mode != 'HARD' and interrupt_policy != 'NEVER':
        raise ValueError('Only HARD events may interrupt music')
    target = _target(station, content_type, content_identifier)
    early = _integer(early_tolerance_seconds, 0, 3600, 'Early tolerance')
    late = _integer(late_tolerance_seconds, 1, 86400, 'Late tolerance')
    priority = _integer(priority, 0, 1000, 'Priority')
    scheduled, day, at = None, None, None
    if recurrence_type == 'ONE_TIME':
        try:
            local = datetime.fromisoformat(f'{local_date}T{local_time}')
        except (TypeError, ValueError) as error:
            raise ValueError('Enter a valid station-local date and time') from error
        scheduled = _wall_to_utc(local, ZoneInfo(validate_timezone(station.timezone)))
    else:
        day = _integer(weekday, 0, 6, 'Weekday')
        at = parse_event_time(local_time)
    row = event_for(slug, identifier) if identifier else TimedEvent(uuid=str(uuid.uuid4()), station_id=station.id)
    if identifier:
        for occurrence in row.occurrences:
            if occurrence.state in ('PENDING', 'READY'):
                occurrence.state = 'CANCELLED'
    row.name, row.description = _clean(name, 120, True), _clean(description, 500)
    row.timing_mode, row.recurrence_type, row.content_type = timing_mode, recurrence_type, content_type
    row.track_id = target.id if content_type == 'TRACK' else None
    row.imaging_asset_id = target.id if content_type == 'IMAGING_ASSET' else None
    row.scheduled_at_utc, row.weekday, row.local_time = scheduled, day, at
    row.early_tolerance_seconds, row.late_tolerance_seconds = early, late
    row.missed_policy, row.interrupt_policy, row.priority = missed_policy, interrupt_policy, priority
    db.session.add(row)
    db.session.commit()
    generate_occurrences(station)
    return row


def set_enabled(row, enabled):
    row.enabled = bool(enabled)
    if not enabled:
        for occurrence in row.occurrences:
            if occurrence.state in ('PENDING', 'READY'):
                occurrence.state = 'CANCELLED'
    db.session.commit()
    if enabled:
        generate_occurrences(row.station)


def _instants(event, start, end):
    if event.recurrence_type == 'ONE_TIME':
        value = event.scheduled_at_utc.replace(tzinfo=event.scheduled_at_utc.tzinfo or timezone.utc)
        return [value] if start - timedelta(days=1) <= value <= end else []
    zone = ZoneInfo(validate_timezone(event.station.timezone))
    local_start = start.astimezone(zone).date()
    output = []
    for offset in range(-1, (end - start).days + 3):
        day = local_start + timedelta(days=offset)
        if day.weekday() == event.weekday:
            value = _wall_to_utc(datetime.combine(day, event.local_time), zone)
            if start - timedelta(days=1) <= value <= end:
                output.append(value)
    return output


def generate_occurrences(station, now=None, horizon_hours=192):
    now = utc_instant(now)
    end = now + timedelta(hours=horizon_hours)
    created = 0
    for event in TimedEvent.query.filter_by(station_id=station.id, enabled=True).all():
        for scheduled in _instants(event, now, end):
            exists = TimedEventOccurrence.query.filter_by(timed_event_id=event.id, scheduled_for_utc=scheduled).first()
            if exists:
                if exists.state == 'CANCELLED':
                    exists.state = 'PENDING'
                    exists.eligible_at_utc = scheduled - timedelta(seconds=event.early_tolerance_seconds)
                    exists.deadline_at_utc = scheduled + timedelta(seconds=event.late_tolerance_seconds)
                    exists.failure_reason = None
                    db.session.commit()
                continue
            db.session.add(TimedEventOccurrence(timed_event_id=event.id, station_id=station.id,
                scheduled_for_utc=scheduled, eligible_at_utc=scheduled-timedelta(seconds=event.early_tolerance_seconds),
                deadline_at_utc=scheduled+timedelta(seconds=event.late_tolerance_seconds), state='PENDING'))
            try:
                db.session.commit(); created += 1
            except IntegrityError:
                db.session.rollback()
    return created


def validate_content(event, storage=None):
    playable = event.track or event.imaging_asset
    if playable is None or playable.station_id != event.station_id or not playable.enabled or playable.ingest_status != 'accepted' or playable.decommissioned_at:
        raise ValueError('Event content is disabled or unavailable')
    storage = storage or LocalMediaStorage()
    if event.track:
        storage.regular_file(event.station.slug, playable.storage_key)
    else:
        storage.imaging_file(event.station.slug, playable.storage_key)
    return playable


def prepare_decision(occurrence, now=None):
    now = utc_instant(now)
    playable = validate_content(occurrence.event)
    decision = SelectionDecision(station_id=occurrence.station_id,
        track_id=playable.id if occurrence.event.track else None,
        imaging_asset_id=playable.id if occurrence.event.imaging_asset else None,
        selection_method='timed_event', status='selected', selected_at=now,
        reason=f'timed_event:{occurrence.id}')
    db.session.add(decision); db.session.flush()
    occurrence.selection_decision_id = decision.id
    occurrence.state = 'READY'
    db.session.commit()
    return decision


def upcoming(station, now=None, limit=20):
    now = utc_instant(now)
    return TimedEventOccurrence.query.join(TimedEventOccurrence.event).filter(
        TimedEventOccurrence.station_id == station.id,
        TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED')),
        TimedEvent.enabled.is_(True)).order_by(TimedEventOccurrence.scheduled_for_utc,
        TimedEvent.priority.desc(), TimedEventOccurrence.id).limit(limit).all()


def conflict_warnings(event):
    duration = (event.track or event.imaging_asset).duration_ms / 1000
    warnings = []
    if duration > event.late_tolerance_seconds:
        warnings.append('Content duration exceeds the late tolerance window.')
    for other in TimedEvent.query.filter(TimedEvent.station_id == event.station_id, TimedEvent.id != event.id, TimedEvent.enabled.is_(True)).all():
        if event.recurrence_type == other.recurrence_type == 'WEEKLY' and event.weekday == other.weekday and event.local_time == other.local_time:
            warnings.append(f'Collides with {other.name}; higher priority executes first.')
        elif event.recurrence_type == other.recurrence_type == 'ONE_TIME' and event.scheduled_at_utc == other.scheduled_at_utc:
            warnings.append(f'Collides with {other.name}; higher priority executes first.')
    return warnings
