"""Read-only calendar coverage and simple station default configuration."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import uuid

from app.extensions import db
from app.models import AutomationState, Clock, ClockSlot, MediaCategory, Rotation, Station
from app.services.schedule import resolve, usable_clock, utc_instant
from app.services.timed_events import projected_occurrences


def coverage(station, start, end):
    """Resolve complete intervals, including weekly assignments and station fallback."""
    point, end = utc_instant(start), utc_instant(end)
    output = []
    state = station.automation
    while point < end:
        resolved = resolve(station, point)
        clock = resolved.clock or (state.default_clock if state and usable_clock(state.default_clock, station.id) else None)
        rotation = state.active_rotation if state and not clock else None
        if rotation and (not rotation.enabled or not any(slot.enabled for slot in rotation.slots)):
            rotation = None
        source = 'Weekly baseline' if resolved.program and resolved.program.baseline_assignment_id else 'Dated program' if resolved.program and resolved.program.on_date else 'Weekly program' if resolved.program else 'Weekly baseline' if resolved.assignment else 'Station default' if clock or rotation else 'Engine fallback'
        name = resolved.program.name if resolved.program else clock.name if clock else rotation.name if rotation else 'No playable programming configured'
        finish = min(end, resolved.next_transition) if resolved.next_transition else end
        if finish <= point:
            raise ValueError('Schedule transition did not advance')
        item = dict(start=point, end=finish, source=source, name=name, clock=clock,
                    rotation=rotation, program=resolved.program, assignment=resolved.assignment,
                    occurrence_key=resolved.occurrence_key)
        if output and all(output[-1][key] == item[key] for key in ('source','name','clock','rotation','occurrence_key')):
            output[-1]['end'] = finish
        else:
            output.append(item)
        point = finish
    return output


def preview_days(station, first, days):
    zone = ZoneInfo(station.timezone)
    start = datetime.combine(first, time(), zone)
    end = datetime.combine(first + timedelta(days=days), time(), zone)
    events = projected_occurrences(station, start, end)
    output = []
    for offset in range(days):
        day = first + timedelta(days=offset)
        begin = datetime.combine(day, time(), zone)
        finish = datetime.combine(day + timedelta(days=1), time(), zone)
        intervals = coverage(station, begin, finish)
        for interval in intervals:
            interval['start'] = interval['start'].astimezone(zone)
            interval['end'] = interval['end'].astimezone(zone)
        daily = [row for row in events if row.scheduled_for_utc.astimezone(zone).date() == day]
        warnings = []
        busy_until = None
        from app.services.programming import candidate_warnings
        from app.services.timed_events import validate_content
        for interval in intervals:
            if interval['source'] == 'Engine fallback':
                warnings.append('No music programming covers part of this day.')
            resource = interval['clock'] or interval['rotation']
            if resource:
                warnings.extend(candidate_warnings(resource))
        for row in daily:
            try:
                playable = validate_content(row.event)
            except (ValueError, OSError):
                warnings.append(f'{row.event.name}: audio is unavailable or the sequence is invalid.')
            target = row.scheduled_for_utc
            if busy_until and busy_until > target:
                warnings.append(f'{row.event.name}: an earlier event may delay this start.')
                if busy_until > target + timedelta(seconds=row.event.late_tolerance_seconds):
                    warnings.append(f'{row.event.name}: preceding events may exceed its late allowance.')
            duration = (row.event.track or row.event.imaging_asset or row.event.event_block)
            seconds = duration.duration_ms / 1000 if duration else 0
            busy_until = max(target, busy_until or target) + timedelta(seconds=seconds)
        output.append(dict(date=day, coverage=intervals, events=daily, warnings=list(dict.fromkeys(warnings))))
    return output


def set_station_default(station, choice):
    """One picker using existing clocks and selection rules; caller commits."""
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    try:
        kind, slug = choice.split(':', 1)
    except (ValueError, AttributeError):
        raise ValueError('Choose a station default')
    state = station.automation
    if state is None:
        state = AutomationState(station_id=station.id, enabled=False)
        db.session.add(state)
    if kind == 'clock':
        clock = Clock.query.filter_by(station_id=station.id, slug=slug).first()
        if not usable_clock(clock, station.id):
            raise ValueError('Choose an enabled show template with usable slots')
    elif kind in ('category','rotation'):
        model = MediaCategory if kind == 'category' else Rotation
        target = model.query.filter_by(station_id=station.id, slug=slug, enabled=True).first()
        if target is None:
            raise ValueError('The selected default is unavailable')
        if kind == 'category' and not any(track.enabled and track.ingest_status == 'accepted' and not track.decommissioned_at for track in target.tracks):
            raise ValueError('Add an enabled song to this category first')
        if kind == 'rotation' and not any(slot.enabled and slot.category.enabled for slot in target.slots):
            raise ValueError('Add an enabled category slot to this music pattern first')
        clock = Clock(station_id=station.id, slug='default-' + uuid.uuid4().hex[:20], name=target.name,
                      enabled=True, description='Station default')
        clock.slots.append(ClockSlot(position=1, slot_type=kind.upper(), enabled=True,
                                    **{kind: target}))
        db.session.add(clock)
    else:
        raise ValueError('Choose a category, music pattern, or show template')
    state.default_clock = clock
    db.session.flush()
    return clock


def baseline_conversion(station):
    """Bound weekly transition intervals at midnight for calendar display."""
    import hashlib
    from app.models import ScheduleAssignment, ScheduleProgram
    assignments = ScheduleAssignment.query.filter_by(station_id=station.id, enabled=True).order_by(
        ScheduleAssignment.weekday, ScheduleAssignment.start_time, ScheduleAssignment.id).all()
    if any(not usable_clock(row.clock, station.id) for row in assignments):
        raise ValueError('Repair unavailable baseline templates before conversion')
    rows = []
    for index, assignment in enumerate(assignments):
        begin = assignment.weekday * 1440 + assignment.start_time.hour * 60 + assignment.start_time.minute
        following = assignments[(index + 1) % len(assignments)]
        finish = following.weekday * 1440 + following.start_time.hour * 60 + following.start_time.minute
        if finish <= begin:
            finish += 7 * 1440
        point = begin
        while point < finish:
            boundary = min(finish, (point // 1440 + 1) * 1440)
            rows.append(dict(assignment=assignment, weekday=(point // 1440) % 7,
                             start=point % 1440, end=(boundary - (point // 1440) * 1440)))
            point = boundary
    signature = station.timezone + repr([(r.id,r.weekday,r.start_time.isoformat(),r.clock_id) for r in assignments])
    signature += repr([(r.id,r.clock_id,r.weekday,r.on_date,r.start_minute,r.end_minute,r.enabled) for r in ScheduleProgram.query.filter_by(station_id=station.id).order_by(ScheduleProgram.id).all()])
    return rows, hashlib.sha256(signature.encode()).hexdigest()


def convert_baseline(station, token):
    """Caller commits conversion and audit together; source assignments remain reversible."""
    from datetime import date
    from app.models import ScheduleProgram
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    rows, current_token = baseline_conversion(station)
    if token != current_token or not rows:
        raise ValueError('The baseline changed. Preview the conversion again.')
    # Validate an entire year so DST and dated overrides participate in comparison.
    start = datetime.combine(date.today(), time(), ZoneInfo(station.timezone))
    end = start + timedelta(days=370)
    before = coverage(station, start, end)
    for row in rows:
        assignment = row['assignment']
        db.session.add(ScheduleProgram(station_id=station.id, name=assignment.clock.name,
            weekday=row['weekday'], start_minute=row['start'], end_minute=row['end'],
            clock_id=assignment.clock_id, baseline_assignment_id=assignment.id, enabled=True))
        assignment.enabled = False
    db.session.flush()
    after = coverage(station, start, end)
    def normalize(intervals):
        merged = []
        for row in intervals:
            key = (row['clock'].id if row['clock'] else None, row['rotation'].id if row['rotation'] else None,
                   row['occurrence_key'])
            if merged and merged[-1][2] == key:
                merged[-1] = (merged[-1][0],row['end'],key)
            else:
                merged.append((row['start'],row['end'],key))
        return merged
    if normalize(before) != normalize(after):
        raise ValueError('Conversion would change coverage or clock progress. Existing assignments were kept; review timezone transitions.')
    return len(rows)


def restore_baseline(station):
    from app.models import ScheduleAssignment, ScheduleProgram
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    rows = ScheduleProgram.query.filter(ScheduleProgram.station_id == station.id,
        ScheduleProgram.baseline_assignment_id.isnot(None), ScheduleProgram.enabled.is_(True)).all()
    for row in rows:
        assignment = row.baseline_assignment
        conflicting = ScheduleAssignment.query.filter(ScheduleAssignment.station_id == station.id,
            ScheduleAssignment.weekday == assignment.weekday, ScheduleAssignment.start_time == assignment.start_time,
            ScheduleAssignment.id != assignment.id, ScheduleAssignment.enabled.is_(True)).first()
        if conflicting:
            raise ValueError('A newer assignment conflicts with restoration')
        assignment.enabled = True
        row.enabled = False
    return len(rows)
