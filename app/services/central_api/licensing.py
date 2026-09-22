"""Local expansion checks only; broadcast/start/recovery never calls the API."""
import time
from app.models import Station
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
    # Distribution entitlements are local and perpetual. Registration and
    # remote cache/grace expiry must not gate the free three-station allowance.
    from app.services.software_license import unlimited
    if unlimited():
        return
    enabled = Station.query.filter(Station.enabled.is_(True), Station.deleted_at.is_(None)).count()
    if enabled >= 3:
        raise ValueError('Free use covers three stations total per owner. Contact info@3andB.com for the US$99 unlimited license.')
    return


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
