"""Shared IANA choices; location labels do not assume fixed UTC offsets."""
from functools import lru_cache
from zoneinfo import available_timezones

@lru_cache(maxsize=1)
def choices():
    examples = {'UTC': 'Universal time', 'Australia/Perth': 'Perth',
        'Australia/Sydney': 'Sydney, Canberra', 'America/New_York': 'New York, Miami',
        'America/Chicago': 'Chicago, Dallas', 'America/Denver': 'Denver',
        'America/Los_Angeles': 'Los Angeles, Seattle', 'Europe/London': 'London',
        'Europe/Paris': 'Paris', 'Asia/Tokyo': 'Tokyo', 'Pacific/Auckland': 'Auckland'}
    zones = sorted(z for z in available_timezones() if '/' in z and not z.startswith(('posix/', 'right/')))
    return [('UTC', 'UTC — Universal time')] + [(z, z + ' — ' + examples.get(z, z.rsplit('/', 1)[-1].replace('_', ' '))) for z in zones]
