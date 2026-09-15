"""Bounded station-local programs layered over existing clocks and weekly defaults."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import uuid

from app.extensions import db
from app.models import Clock, ClockSlot, MediaCategory, Rotation, ScheduleProgram, Station
from app.services.programming import clean_text
from app.services.schedule import _wall_to_utc, parse_local_time, utc_instant, usable_clock


def minute(value):
    if value == '24:00':
        return 1440
    parsed = parse_local_time(value)
    return parsed.hour * 60 + parsed.minute


def window(program, day):
    zone = ZoneInfo(program.station.timezone)
    midnight = datetime.combine(day, time())
    return (_wall_to_utc(midnight + timedelta(minutes=program.start_minute), zone),
            _wall_to_utc(midnight + timedelta(minutes=program.end_minute), zone))


def occurrences(program, start_day, days=7):
    for offset in range(-1, days + 1):
        day = start_day + timedelta(days=offset)
        if (program.on_date == day) if program.on_date else (day.weekday() == program.weekday):
            start, end = window(program, day)
            yield day, start, end


def overlap(first, second):
    if first.on_date and second.on_date and first.on_date != second.on_date:
        # Overnight windows can overlap the following date.
        pass
    if bool(first.on_date) != bool(second.on_date):
        return False  # A dated exception intentionally takes priority over the weekly program.
    anchor = first.on_date or date(2026, 1, 5)
    for _, start, end in occurrences(first, anchor, 7):
        for _, other_start, other_end in occurrences(second, anchor, 7):
            if start < other_end and other_start < end:
                return True
    return False


def create_program(station, *, name, weekdays, start, end, category_slug=None, clock_slug=None, rotation_slug=None, on_date=None):
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    name = clean_text(name, 120, True)
    begin, finish = minute(start), minute(end)
    if begin == 1440:
        raise ValueError('A program must start before midnight')
    if finish <= begin:
        finish += 1440
    if finish - begin > 1440:
        raise ValueError('Programs can span at most one day')
    day = date.fromisoformat(on_date) if on_date else None
    selected_days = [day.weekday()] if day else sorted({int(value) for value in weekdays})
    if not selected_days or any(value not in range(7) for value in selected_days):
        raise ValueError('Choose at least one weekday')
    if sum(bool(value) for value in (category_slug, clock_slug, rotation_slug)) != 1:
        raise ValueError('Choose one category, show template, or rotation')
    clock = None
    if clock_slug:
        clock = Clock.query.filter_by(station_id=station.id, slug=clock_slug).first()
        if not usable_clock(clock, station.id):
            raise ValueError('Choose an enabled show template with playable slots')
    else:
        category = MediaCategory.query.filter_by(station_id=station.id, slug=category_slug, enabled=True).first() if category_slug else None
        rotation = Rotation.query.filter_by(station_id=station.id, slug=rotation_slug, enabled=True).first() if rotation_slug else None
        if not category and not rotation:
            raise ValueError('The selected category or rotation is unavailable')
        if category and not any(track.enabled and track.ingest_status == 'accepted' and not track.decommissioned_at for track in category.tracks):
            raise ValueError('Add an enabled song to this category before scheduling it')
        clock = Clock(station_id=station.id, slug='program-' + uuid.uuid4().hex[:20], name=name, enabled=True,
                      description='Calendar program: selection repeats until the end of its time block.')
        clock.slots.append(ClockSlot(position=1, slot_type='CATEGORY' if category else 'ROTATION', category=category, rotation=rotation, enabled=True))
    existing = ScheduleProgram.query.filter_by(station_id=station.id, enabled=True).all()
    created = []
    for weekday in selected_days:
        row = ScheduleProgram(station=station, name=name, weekday=weekday, on_date=day, start_minute=begin, end_minute=finish, clock=clock, enabled=True)
        if any(overlap(row, other) for other in existing + created):
            raise ValueError('This time overlaps another program. Move or remove that block first. Dated programs can override the recurring week.')
        created.append(row)
    db.session.add_all(created)
    db.session.flush()
    return created


def resolve_program(station, now):
    now = utc_instant(now)
    today = now.astimezone(ZoneInfo(station.timezone)).date()
    active, boundaries = [], []
    for program in ScheduleProgram.query.filter_by(station_id=station.id, enabled=True).all():
        if not usable_clock(program.clock, station.id):
            continue
        for day, start, end in occurrences(program, today, 7):
            if start <= now < end:
                active.append((bool(program.on_date), start, program.id, program, day))
            boundaries.extend(point for point in (start, end) if point > now)
    chosen = max(active, key=lambda value: value[:3]) if active else None
    return (chosen[3], chosen[4]) if chosen else (None, None), min(boundaries) if boundaries else None


def calendar_days(station, start_day, days=7):
    result = []
    programs = ScheduleProgram.query.filter_by(station_id=station.id, enabled=True).all()
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        entries = []
        for program in programs:
            for origin, start, end in occurrences(program, day, 1):
                zone = ZoneInfo(station.timezone)
                if end > _wall_to_utc(datetime.combine(day,time()),zone) and start < _wall_to_utc(datetime.combine(day+timedelta(days=1),time()),zone):
                    entries.append({'program':program,'start':start.astimezone(zone),'end':end.astimezone(zone),'origin':origin})
        result.append({'date':day,'entries':sorted(entries,key=lambda row:(row['start'],row['program'].id))})
    return result
