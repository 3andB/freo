"""Station-local event definitions, durable occurrences and playback snapshots."""
import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.extensions import db
from app.models import (EventBlock, ImagingAsset, Playlist, SelectionDecision, Station,
                        TimedEvent, TimedEventOccurrence, Track, EventQueueCancellation)
from app.services.availability import available, tracks_for
from app.services.media_storage import LocalMediaStorage
from app.services.schedule import _wall_to_utc, utc_instant, validate_timezone
from app.services.stations import get_station

MODES = ('SOFT', 'HARD', 'NON_INTERRUPTING')
RECURRENCES = ('ONE_TIME', 'QUARTER_HOUR', 'HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY')
CONTENTS = ('PLAYLIST', 'TRACK', 'EVENT_BLOCK', 'IMAGING_ASSET')
MISSED = ('SKIP', 'PLAY_LATE')
INTERRUPTS = ('NEVER', 'MUSIC_ONLY')


def aware(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def _clean(value, limit, required=False):
    value = ''.join(ch for ch in (value or '').strip() if ch.isprintable())
    if len(value) > limit or required and not value:
        raise ValueError(f'Enter a value of at most {limit} characters')
    return value


def event_for(slug, identifier):
    station = get_station(slug)
    row = TimedEvent.query.filter_by(station_id=station.id, uuid=identifier).first() if station else None
    if row is None: raise ValueError('Event not found')
    return row


def _target(station, kind, identifier):
    if kind == 'TRACK': row = tracks_for(station.id).filter_by(uuid=identifier).first()
    elif kind == 'PLAYLIST':
        from app.services.playlists import get_playlist
        row = get_playlist(station.id, identifier)
    elif kind == 'EVENT_BLOCK': row = EventBlock.query.filter_by(station_id=station.id, slug=identifier).first()
    elif kind == 'IMAGING_ASSET': row = ImagingAsset.query.filter_by(station_id=station.id, uuid=identifier).first()
    else: raise ValueError('Unsupported event content type')
    if row is None: raise ValueError('Event content belongs to another station or does not exist')
    return row


def _integer(value, low, high, label):
    try:
        if isinstance(value, bool): raise ValueError()
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'{label} is invalid') from error
    if not low <= result <= high: raise ValueError(f'{label} must be between {low} and {high}')
    return result


def parse_event_time(value):
    try: return datetime.strptime(value, '%H:%M:%S' if len(value or '') == 8 else '%H:%M').time()
    except (TypeError, ValueError) as error: raise ValueError('Time must be HH:MM or HH:MM:SS') from error


def _date(value):
    try: return date.fromisoformat(value) if value else None
    except (TypeError, ValueError) as error: raise ValueError('Enter a valid local date') from error


def cancel_occurrence(occurrence, *, user=False):
    if occurrence.state in ('STARTED', 'COMPLETED', 'MISSED', 'FAILED'):
        return
    decisions = [occurrence.selection_decision] if occurrence.selection_decision else []
    execution = occurrence.block_execution
    if execution:
        if execution.state == 'STARTED': return
        decisions += [item.selection_decision for item in execution.items if item.selection_decision]
        execution.state = 'CANCELLED'
        # Keep the old execution and its snapshot in history; release the unique occurrence link.
        execution.timed_event_occurrence = None
    for decision in decisions:
        if decision.status in ('queued', 'submitting'):
            if not db.session.get(EventQueueCancellation, decision.id):
                db.session.add(EventQueueCancellation(decision_id=decision.id, station_id=occurrence.station_id, processed=False))
        elif decision.status == 'selected':
            decision.status, decision.reason = 'failed', 'event_cancelled'
    occurrence.selection_decision = None
    occurrence.state = 'CANCELLED'
    occurrence.cancelled_by_user = user
    occurrence.boundary_reserved = False
    occurrence.runtime = {}
    occurrence.failure_reason = 'cancelled_by_user' if user else 'definition_changed'


def invalidate(event):
    for occurrence in event.occurrences: cancel_occurrence(occurrence)
    event.generated_until = None
    event.revision = (event.revision or 1) + 1


def save_event(slug, *, identifier=None, name, description='', timing_mode='SOFT', recurrence_type,
               content_type, content_identifier, local_date=None, local_time=None, weekday=None, weekdays=None,
               early_tolerance_seconds=0, late_tolerance_seconds=300, missed_policy='SKIP',
               interrupt_policy='NEVER', priority=100, repeat_hours=None, starts_on=None, ends_on=None,
               interrupt_dj=False, playlist_playback=None, month_day=None, month_nth=None,
               month_weekday=None, revision=None):
    station = get_station(slug)
    if station is None: raise ValueError('Station not found')
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    if timing_mode not in MODES or recurrence_type not in RECURRENCES or missed_policy not in MISSED or interrupt_policy not in INTERRUPTS:
        raise ValueError('Unsupported event option')
    if timing_mode != 'HARD' and interrupt_policy != 'NEVER': raise ValueError('Only HARD events may interrupt music')
    if not isinstance(interrupt_dj, bool): raise ValueError('Choose Yes or No for INTERRUPT DJ')
    row = event_for(slug, identifier) if identifier else TimedEvent(uuid=str(uuid.uuid4()), station_id=station.id, station=station)
    if identifier and commercial_log(row): raise ValueError('Finalized commercial events are managed through Commercials')
    if revision is not None and _integer(revision,1,2147483647,'Revision') != row.revision:
        raise ValueError('This event changed elsewhere. Reload before saving')
    target = _target(station, content_type, content_identifier)
    at = parse_event_time(local_time)
    local_day = _date(local_date)
    first, last = _date(starts_on), _date(ends_on)
    if first and last and last < first: raise ValueError('End date is before start date')
    selected_days = sorted({_integer(v,0,6,'Weekday') for v in weekdays}) if weekdays is not None else ([_integer(weekday,0,6,'Weekday')] if weekday is not None else list(range(7)))
    if recurrence_type != 'ONE_TIME' and not selected_days: raise ValueError('Choose at least one repeat day')
    hours = sorted({_integer(h,0,23,'Hour') for h in repeat_hours}) if repeat_hours is not None else None
    if hours == []: raise ValueError('Choose at least one hour')
    if recurrence_type == 'ONE_TIME' and local_day is None: raise ValueError('Enter a valid station-local date and time')
    day = _integer(month_day or (local_day.day if local_day else 1), 1, 31, 'Day of month')
    nth = _integer(month_nth or 0,-2,5,'Week of month')
    dow = _integer(month_weekday or 0,0,6,'Weekday')
    playback = playlist_playback or ('ALL' if content_type == 'PLAYLIST' and target.purpose == 'COMMERCIALS' else 'ONE')
    if playback not in ('ONE','ALL'): raise ValueError('Choose one next item or the entire playlist')
    if content_type == 'PLAYLIST' and playback == 'ALL' and len(target.items)>500 or content_type == 'EVENT_BLOCK' and len(target.items)>500:
        raise ValueError('An event sequence supports at most 500 items')
    early = _integer(early_tolerance_seconds,0,3600,'Early tolerance')
    late = _integer(late_tolerance_seconds,1,86400,'Late tolerance')
    rank = _integer(priority,0,1000,'Priority')
    clean_name, clean_description = _clean(name,120,True), _clean(description,500)
    if identifier: invalidate(row)
    if row.playlist_id != (target.id if content_type == 'PLAYLIST' else None): row.playlist_state = {}
    row.name, row.description = clean_name, clean_description
    row.timing_mode, row.recurrence_type, row.content_type = timing_mode, recurrence_type, content_type
    row.track = target if content_type == 'TRACK' else None
    row.imaging_asset = target if content_type == 'IMAGING_ASSET' else None
    row.event_block = target if content_type == 'EVENT_BLOCK' else None
    row.playlist = target if content_type == 'PLAYLIST' else None
    row.playlist_playback, row.interrupt_dj = playback, interrupt_dj
    row.local_date = local_day
    row.scheduled_at_utc = _wall_to_utc(datetime.combine(local_day, at), ZoneInfo(validate_timezone(station.timezone))) if recurrence_type == 'ONE_TIME' else None
    row.local_time = at
    row.weekday = None if recurrence_type == 'ONE_TIME' else selected_days[0]
    row.weekdays = None if recurrence_type == 'ONE_TIME' else ','.join(map(str,selected_days))
    row.repeat_hours = hours if recurrence_type in ('WEEKLY','HOURLY','QUARTER_HOUR') else None
    row.starts_on, row.ends_on = first, last
    row.month_day, row.month_nth, row.month_weekday = day, nth, dow
    row.early_tolerance_seconds, row.late_tolerance_seconds = early, late
    row.missed_policy, row.interrupt_policy, row.priority = missed_policy, interrupt_policy, rank
    db.session.add(row)
    db.session.flush()
    if row.playlist and not any(item.track.enabled and item.track.ingest_status == 'accepted' and available(item.track,station.id) and not item.track.decommissioned_at for item in row.playlist.items):
        raise ValueError('Choose a playlist with playable audio')
    db.session.commit()
    generate_occurrences(station)
    return row


def set_enabled(row, enabled):
    if commercial_log(row): raise ValueError('Finalized commercial events are managed through Commercials')
    db.session.query(Station.id).filter_by(id=row.station_id).with_for_update().first()
    invalidate(row)
    row.enabled = bool(enabled)
    db.session.commit()
    if enabled: generate_occurrences(row.station)


def timezone_changed(station, previous):
    for event in TimedEvent.query.filter_by(station_id=station.id).all():
        if event.recurrence_type == 'ONE_TIME':
            local = datetime.combine(event.local_date,event.local_time) if event.local_date and event.local_time else aware(event.scheduled_at_utc).astimezone(ZoneInfo(previous)).replace(tzinfo=None)
            event.local_date = local.date()
            if aware(event.scheduled_at_utc) > datetime.now(timezone.utc):
                event.scheduled_at_utc = _wall_to_utc(local, ZoneInfo(station.timezone))
        invalidate(event)


def _instants(event, start, end):
    if event.recurrence_type == 'ONE_TIME':
        value = aware(event.scheduled_at_utc)
        return [value] if start <= value <= end else []
    zone = ZoneInfo(validate_timezone(event.station.timezone))
    local_start = start.astimezone(zone).date()
    output = set()
    for offset in range(-1, (end-start).days+3):
        day = local_start + timedelta(days=offset)
        if event.starts_on and day < event.starts_on or event.ends_on and day > event.ends_on: continue
        kind = event.recurrence_type
        if kind in ('WEEKLY','HOURLY','QUARTER_HOUR') and day.weekday() not in event.repeat_days: continue
        if kind == 'MONTHLY':
            nth = event.month_nth or 0
            if nth == -2:
                if day.day != calendar.monthrange(day.year,day.month)[1]: continue
            elif nth:
                if day.weekday() != event.month_weekday: continue
                if nth == -1:
                    if day.day+7 <= calendar.monthrange(day.year,day.month)[1]: continue
                elif (day.day-1)//7+1 != nth: continue
            elif day.day != (event.month_day or 1): continue
        hours = event.repeat_hours if event.repeat_hours is not None else range(24) if kind in ('HOURLY','QUARTER_HOUR') else [event.local_time.hour]
        minutes = range(event.local_time.minute % 15,60,15) if kind == 'QUARTER_HOUR' else [event.local_time.minute]
        for hour in hours:
            for minute in minutes:
                value = _wall_to_utc(datetime.combine(day,event.local_time.replace(hour=hour,minute=minute)),zone)
                if start <= value <= end: output.add(value)
    return sorted(output)


def generate_occurrences(station, now=None, horizon_hours=192):
    now = utc_instant(now)
    end = now+timedelta(hours=horizon_hours)
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    created = 0
    for event in TimedEvent.query.filter_by(station_id=station.id, enabled=True).all():
        if event.generated_until and aware(event.generated_until) >= end-timedelta(hours=12): continue
        existing = {aware(o.scheduled_for_utc):o for o in TimedEventOccurrence.query.filter_by(timed_event_id=event.id).filter(TimedEventOccurrence.scheduled_for_utc >= now-timedelta(days=1), TimedEventOccurrence.scheduled_for_utc <= end)}
        for scheduled in _instants(event,now-timedelta(days=1),end):
            occurrence = existing.get(scheduled)
            if occurrence and (occurrence.state != 'CANCELLED' or occurrence.cancelled_by_user): continue
            if occurrence is None:
                occurrence = TimedEventOccurrence(timed_event_id=event.id,station_id=station.id,scheduled_for_utc=scheduled)
                db.session.add(occurrence); created += 1
            occurrence.state, occurrence.failure_reason = 'PENDING', None
            occurrence.revision = event.revision
            occurrence.eligible_at_utc = scheduled-timedelta(seconds=event.early_tolerance_seconds)
            occurrence.deadline_at_utc = scheduled+timedelta(seconds=event.late_tolerance_seconds)
        event.generated_until = end
    db.session.commit()
    return created


def validate_content(event, storage=None):
    storage = storage or LocalMediaStorage()
    if event.playlist:
        from app.services.playlists import playable_tracks
        if not playable_tracks(event.playlist,event.station_id,storage): raise ValueError('Playlist has no playable audio')
        return event.playlist
    if event.event_block:
        from app.services.event_blocks import validate_block
        if not event.event_block.enabled or validate_block(event.event_block,storage): raise ValueError('Event block is disabled or invalid')
        return event.event_block
    playable = event.track or event.imaging_asset
    if playable is None or (not available(playable,event.station_id) if event.track else playable.station_id != event.station_id) or not playable.enabled or playable.ingest_status != 'accepted' or playable.decommissioned_at:
        raise ValueError('Event content is disabled or unavailable')
    (storage.regular_file if event.track else storage.imaging_file)(playable.station.slug,playable.storage_key)
    return playable


def prepare_decision(occurrence, now=None):
    now = utc_instant(now)
    playable = validate_content(occurrence.event)
    if occurrence.event.event_block or occurrence.event.playlist:
        occurrence.state = 'READY'; db.session.commit(); return playable
    decision = SelectionDecision(station_id=occurrence.station_id,track_id=playable.id if occurrence.event.track else None,
        imaging_asset_id=playable.id if occurrence.event.imaging_asset else None,selection_method='timed_event',status='selected',selected_at=now,reason=f'timed_event:{occurrence.id}')
    db.session.add(decision); db.session.flush()
    occurrence.selection_decision = decision; occurrence.state = 'READY'
    db.session.commit(); return decision


def upcoming(station, now=None, limit=20):
    return TimedEventOccurrence.query.join(TimedEventOccurrence.event).filter(
        TimedEventOccurrence.station_id == station.id,TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED')),TimedEvent.enabled.is_(True)).order_by(
        TimedEventOccurrence.scheduled_for_utc,TimedEvent.priority.desc(),TimedEventOccurrence.id).limit(limit).all()


def recurrence_summary(event):
    if event.recurrence_type == 'ONE_TIME': return 'Once'
    labels = dict(QUARTER_HOUR='Every 15 minutes',HOURLY='Hourly',DAILY='Daily',WEEKLY='Weekly',MONTHLY='Monthly')
    text = labels[event.recurrence_type]
    if event.recurrence_type in ('WEEKLY','HOURLY','QUARTER_HOUR'):
        text += ' · '+', '.join(['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][d] for d in event.repeat_days)
    if event.recurrence_type == 'MONTHLY':
        text += ' · last day' if event.month_nth == -2 else f' · day {event.month_day}' if not event.month_nth else f" · {dict([(-1,'last'),(1,'first'),(2,'second'),(3,'third'),(4,'fourth'),(5,'fifth')])[event.month_nth]} {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][event.month_weekday]}"
    text += ' · '+event.local_time.strftime('%H:%M:%S')
    if event.repeat_hours is not None: text += ' · hours '+', '.join(f'{h:02}' for h in event.repeat_hours)
    return text


def estimated_duration(event):
    if event.playlist:
        durations=[i.track.duration_ms for i in event.playlist.items if i.track.enabled and i.track.ingest_status=='accepted' and available(i.track,event.station_id) and not i.track.decommissioned_at]
        return (sum(durations) if event.playlist_playback=='ALL' else max(durations,default=0))/1000
    target=event.track or event.imaging_asset or event.event_block
    return target.duration_ms/1000 if target else 0


def conflict_warnings(event):
    from bisect import bisect_left
    now=datetime.now(timezone.utc); end=now+timedelta(days=62)
    instants=_instants(event,now,end); duration=timedelta(seconds=max(1,estimated_duration(event))); warnings=[]
    if any(b-a < duration for a,b in zip(instants,instants[1:])):
        warnings.append('Audio is longer than the repeat interval. Repeats may be skipped while this event finishes.')
    for other in TimedEvent.query.filter(TimedEvent.station_id==event.station_id,TimedEvent.id!=event.id,TimedEvent.enabled.is_(True)):
        other_duration=timedelta(seconds=max(1,estimated_duration(other)))
        other_times=_instants(other,now-other_duration,end+duration)
        for instant in instants:
            index=bisect_left(other_times,instant)
            if any(instant < value+other_duration and value < instant+duration for value in other_times[max(0,index-1):index+1]):
                warnings.append(f'Overlaps {other.name}; events run in target-time order, then priority. Song boundaries can delay them further.')
                break
    return warnings


def commercial_log(event):
    if not event.event_block_id: return None
    from app.services.event_blocks import commercial_log_for_block
    return commercial_log_for_block(event.event_block)


def projected_occurrences(station, start, end):
    """Read-only forecast merged with execution results, including distant weeks."""
    from types import SimpleNamespace
    start, end = utc_instant(start), utc_instant(end)
    recorded = TimedEventOccurrence.query.filter(
        TimedEventOccurrence.station_id == station.id,
        TimedEventOccurrence.scheduled_for_utc >= start,
        TimedEventOccurrence.scheduled_for_utc < end).all()
    def aware(value):
        return value.replace(tzinfo=value.tzinfo or timezone.utc)
    by_key = {(row.timed_event_id, aware(row.scheduled_for_utc)): row for row in recorded}
    output = []
    for event in TimedEvent.query.filter_by(station_id=station.id, enabled=True).all():
        for instant in _instants(event, start, end):
            if not start <= instant < end:
                continue
            row = by_key.pop((event.id, instant), None)
            output.append(SimpleNamespace(event=event, scheduled_for_utc=instant,
                state=row.state if row else 'PROJECTED', started_at=row.started_at if row else None,
                failure_reason=row.failure_reason if row else None,
                timing_offset_seconds=row.timing_offset_seconds if row else None,
                commercial_log=commercial_log(event)))
    # Keep historical outcomes visible even when a definition is disabled or edited.
    for row in by_key.values():
        if row.state not in ('PENDING', 'READY', 'CANCELLED'):
            output.append(SimpleNamespace(event=row.event, scheduled_for_utc=aware(row.scheduled_for_utc),
                state=row.state, started_at=row.started_at, failure_reason=row.failure_reason,
                timing_offset_seconds=row.timing_offset_seconds, commercial_log=commercial_log(row.event)))
    return sorted(output, key=lambda row: (row.scheduled_for_utc, -row.event.priority, row.event.id))
