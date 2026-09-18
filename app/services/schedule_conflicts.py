"""Find recurrence collisions across the supported date domain, not a preview window.

Daily/weekly rules are modular day sequences. Monthly rules enumerate only their
eligible months (at most 120,000), and finite rules enumerate their explicit dates.
"""
import calendar
from datetime import date
from math import gcd

LAST_DAY = date.max.toordinal()


def bounds(rule):
    return (date.fromisoformat(rule.get('starts_on') or rule['anchor']).toordinal(),
            date.fromisoformat(rule['until']).toordinal() if rule.get('until') else LAST_DAY)


def residues(rule):
    anchor = date.fromisoformat(rule['anchor'])
    interval = rule.get('interval', 1)
    if rule['frequency'] == 'daily':
        return interval, [anchor.toordinal() % interval]
    period = 7 * interval
    monday = anchor.toordinal() - anchor.weekday()
    return period, [(monday + day) % period for day in rule['weekdays']]


def monthly_dates(rule, low, high):
    anchor = date.fromisoformat(rule['anchor'])
    start = date.fromordinal(max(1, low))
    month = (start.year - 1) * 12 + start.month - 1
    origin = (anchor.year - 1) * 12 + anchor.month - 1
    interval = rule.get('interval', 1)
    month += (origin - month) % interval
    finish = date.fromordinal(min(LAST_DAY, high))
    last_month = (finish.year - 1) * 12 + finish.month - 1
    while month <= last_month:
        year, index = divmod(month, 12)
        year += 1; index += 1
        first_weekday, days = calendar.monthrange(year, index)
        nth = rule.get('nth', 0)
        if nth == -1:
            day = days - ((first_weekday + days - 1) % 7 - rule['weekday']) % 7
        elif nth:
            day = 1 + (rule['weekday'] - first_weekday) % 7 + 7 * (nth - 1)
        else:
            day = rule['month_day']
        if day <= days:
            ordinal = date(year, index, day).toordinal()
            if low <= ordinal <= high:
                yield ordinal
        month += interval


def first_common_day(a, b, offset, matches):
    """Return a's first day for which b occurs `offset` days later."""
    a_low, a_high = bounds(a); b_low, b_high = bounds(b)
    low, high = max(a_low, b_low - offset, 1), min(a_high, b_high - offset, LAST_DAY)
    if low > high:
        return None

    def valid(day):
        return matches(a, date.fromordinal(day)) and matches(b, date.fromordinal(day + offset))

    for rule, delta in ((a, 0), (b, offset)):
        if rule['frequency'] in ('once', 'dates'):
            days = [rule['anchor']] if rule['frequency'] == 'once' else rule.get('dates', [])
            for value in sorted(days):
                day = date.fromisoformat(value).toordinal() - delta
                if low <= day <= high and valid(day):
                    return day
            return None

    if a['frequency'] == b['frequency'] == 'monthly' and offset == 0:
        if not a.get('nth') and not b.get('nth') and a['month_day'] != b['month_day']:
            return None
        if a.get('nth') and b.get('nth'):
            if a['weekday'] != b['weekday']:
                return None
            if a['nth'] != b['nth'] and (a['nth'] > 0 and b['nth'] > 0 or min(a['nth'], b['nth']) == -1 and max(a['nth'], b['nth']) < 4):
                return None
        aa, bb = date.fromisoformat(a['anchor']), date.fromisoformat(b['anchor'])
        if ((aa.year - bb.year) * 12 + aa.month - bb.month) % gcd(a.get('interval', 1), b.get('interval', 1)):
            return None

    for rule, delta in ((a, 0), (b, offset)):
        if rule['frequency'] == 'monthly':
            for ordinal in monthly_dates(rule, low + delta, high + delta):
                day = ordinal - delta
                if valid(day):
                    return day
            return None

    m, left = residues(a); n, right = residues(b)
    divisor = gcd(m, n); period = m * n // divisor
    found = None
    for x in left:
        for y in right:
            difference = y - offset - x
            if difference % divisor:
                continue
            factor = 0 if n == divisor else (difference // divisor * pow(m // divisor, -1, n // divisor)) % (n // divisor)
            day = (x + m * factor) % period
            day += ((low - day + period - 1) // period) * period
            while day <= high and (found is None or day < found):
                if valid(day):
                    found = day
                    break
                day += period  # Only finite exceptions can exclude this solution.
    return found


def validate_overlaps(document, matches, assignments=False):
    # Sweep visible wall-time fragments first. A dense but non-overlapping day
    # needs no recurrence comparisons, rather than N² date/interval checks.
    levels={True:[],False:[]}
    for index,row in enumerate(document):
        start,end=(0,86400) if assignments else (row['start'],row['end'])
        level=levels[row['rule']['frequency'] in ('once','dates')]
        level.append((start,min(end,86400),index,0))
        if end>86400:level.append((0,end-86400,index,-1))
    for fragments in levels.values():
        active=[];checked=set()
        for start,end,index,origin in sorted(fragments):
            active=[item for item in active if item[0]>start]
            for _,other,other_origin in active:
                if index==other:continue
                offset=origin-other_origin
                pair=(other,index,offset)
                if pair in checked:continue
                checked.add(pair)
                day=first_common_day(document[other]['rule'],document[index]['rule'],offset,matches)
                if day is not None:
                    raise ValueError(f'Schedules overlap on {date.fromordinal(day-other_origin)}. Adjust the times or repeat rules.')
            active.append((end,index,origin))
