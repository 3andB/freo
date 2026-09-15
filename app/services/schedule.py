"""Resolve recurring station-local programming against absolute UTC instants."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.models import ScheduleAssignment


def validate_timezone(name):
    if not isinstance(name, str) or name not in available_timezones() or '/' not in name and name != 'UTC':
        raise ValueError('Use a canonical IANA timezone, such as America/Denver or UTC')
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ValueError('Timezone is unavailable') from error
    return name


def parse_local_time(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':' or not (value[:2] + value[3:]).isascii() or not (value[:2] + value[3:]).isdecimal():
        raise ValueError('Time must be HH:MM')
    hour, minute = int(value[:2]), int(value[3:])
    if hour > 23 or minute > 59:
        raise ValueError('Time must be HH:MM')
    return time(hour, minute)


def utc_instant(value):
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('An absolute timezone-aware instant is required')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Resolution:
    local_time: datetime
    assignment: ScheduleAssignment | None
    clock: object | None
    occurrence_key: str | None
    next_transition: datetime | None
    program: object | None = None


def _assignments(station):
    return [row for row in ScheduleAssignment.query.filter_by(station_id=station.id, enabled=True).all()
            if usable_clock(row.clock, station.id)]


def usable_clock(clock, station_id):
    if clock is None or not clock.enabled or clock.station_id != station_id:
        return False
    slots = [slot for slot in clock.slots if slot.enabled]
    return bool(slots) and all(
        (slot.slot_type == 'CATEGORY' and slot.category and slot.category.enabled and slot.category.station_id == station_id)
        or (slot.slot_type == 'ROTATION' and slot.rotation and slot.rotation.enabled and slot.rotation.station_id == station_id
            and any(part.enabled for part in slot.rotation.slots))
        or (slot.slot_type == 'CART' and slot.imaging_asset and slot.imaging_asset.station_id == station_id)
        or (slot.slot_type == 'IMAGING_GROUP' and slot.imaging_group and slot.imaging_group.station_id == station_id)
        or (slot.slot_type == 'EVENT_BLOCK' and slot.event_block and slot.event_block.enabled and slot.event_block.station_id == station_id)
        for slot in slots)


def _wall_to_utc(local_naive, zone):
    """First occurrence on fall-back; first valid instant after a spring gap."""
    aware = local_naive.replace(tzinfo=zone, fold=0)
    candidate = aware.astimezone(timezone.utc)
    roundtrip = candidate.astimezone(zone).replace(tzinfo=None)
    if roundtrip < local_naive:
        candidate = local_naive.replace(tzinfo=zone, fold=1).astimezone(timezone.utc)
        roundtrip = candidate.astimezone(zone).replace(tzinfo=None)
    return candidate


def resolve(station, at=None):
    now = utc_instant(at)
    zone = ZoneInfo(validate_timezone(station.timezone))
    local = now.astimezone(zone)
    rows = _assignments(station)
    past, upcoming = [], []
    for row in rows:
        day = local.date() - timedelta(days=(local.weekday() - row.weekday) % 7)
        candidate = _wall_to_utc(datetime.combine(day, row.start_time), zone)
        if candidate <= now:
            past.append((candidate, row.id, row, day))
            next_day = day + timedelta(days=7)
            upcoming.append(_wall_to_utc(datetime.combine(next_day, row.start_time), zone))
        else:
            upcoming.append(candidate)
            previous_day = day - timedelta(days=7)
            past.append((_wall_to_utc(datetime.combine(previous_day, row.start_time), zone), row.id, row, previous_day))
    active = max(past, key=lambda item: (item[0], item[1])) if past else None
    assignment = active[2] if active else None
    key = f'{assignment.id}:{active[3].isoformat()}' if active else None
    next_transition = min(upcoming) if upcoming else None
    from app.services.calendar import resolve_program
    (program, day), boundary = resolve_program(station, now)
    if boundary:
        next_transition = min(point for point in (next_transition, boundary) if point)
    if program:
        return Resolution(local, None, program.clock, f'program:{program.id}:{day.isoformat()}', next_transition, program)
    return Resolution(local, assignment, assignment.clock if assignment else None, key, next_transition)


def preview_transitions(station, start, hours):
    """Read-only station-local transitions within an absolute UTC window."""
    from datetime import timedelta
    if not 1 <= hours <= 168:
        raise ValueError('Preview must be 1 to 168 hours')
    point = utc_instant(start)
    end = point + timedelta(hours=hours)
    output = []
    while point <= end:
        row = resolve(station, point)
        output.append({'local_time': row.local_time.isoformat(),
                       'clock': row.clock.name if row.clock else None,
                       'assignment_id': row.assignment.id if row.assignment else None})
        if not row.next_transition or row.next_transition <= point or row.next_transition > end:
            break
        point = row.next_transition
    return output
