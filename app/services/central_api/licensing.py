"""Local expansion checks only; broadcast/start/recovery never calls the API."""
import time
from app.extensions import db
from app.models import CentralInstallation, Station
from .client import timestamp

_anchors = {}


def effective_time(cache, now=None):
    now = time.time() if now is None else now
    received = cache['received_at']
    key = (cache['entitlement']['installation_id'], received)
    if key not in _anchors:
        _anchors.clear()  # One installation/cache per process, bounded across refreshes.
        _anchors[key] = (time.monotonic(), now)
    anchor = _anchors[key]
    # Persisted checkpoint catches wall-clock rollback across reporter restarts.
    if cache.get('clock_uncertain') or now < cache.get('checked_at', received) - 5:
        return None
    elapsed = max(now - received, anchor[1] - received + time.monotonic() - anchor[0], 0)
    return max(timestamp(cache['entitlement']['server_time']) + elapsed, cache.get('server_floor', 0))


def check_expansion():
    installation = db.session.get(CentralInstallation, 1)
    # Optional/unconfigured open-source installations retain their existing rules.
    if not installation or not installation.installation_id:
        return
    cache = installation.license_cache
    if not cache:
        raise ValueError('Verify the installation license before enabling another station')
    current = effective_time(cache)
    entitlement = cache['entitlement']
    if current is None or current > timestamp(entitlement['grace_until']) or entitlement['status'] != 'active':
        raise ValueError('License verification is needed before enabling another station; existing broadcasts remain available')
    enabled = Station.query.filter(Station.enabled.is_(True), Station.deleted_at.is_(None)).count()
    if enabled >= entitlement['channel_limit']:
        raise ValueError('The installation license allows no additional enabled stations')


def checkpoint(installation, now):
    if not installation.license_cache:
        return
    cache = dict(installation.license_cache)
    current = effective_time(cache, now)
    if current is None:
        cache['clock_uncertain'] = True
    else:
        cache['server_floor'] = current
    cache['checked_at'] = max(now, cache.get('checked_at', now))
    installation.license_cache = cache
