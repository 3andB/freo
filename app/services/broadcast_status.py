"""Bounded worker-only Icecast polling; UI requests never wait on Icecast."""
import json
import time
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlsplit

_opener=build_opener(ProxyHandler({}))
_checked=0.0
_sources=None


def observation(slug):
    global _checked,_sources
    now=time.monotonic()
    if not _checked or now-_checked>=5:
        _checked=now
        try:
            with _opener.open('http://127.0.0.1:8001/status-json.xsl',timeout=1) as response:
                sources=json.load(response)['icestats'].get('source',[])
            if isinstance(sources,dict):sources=[sources]
            _sources={urlsplit(row.get('listenurl','')).path:row for row in sources}
        except (OSError,ValueError,KeyError,TypeError):
            _sources=None
    if _sources is None:return None,None
    source=_sources.get('/'+slug)
    if source is None:return False,0
    try:
        listeners=int(source['listeners'])
        return True,listeners if listeners>=0 else None
    except (KeyError,ValueError,TypeError):return True,None


def cached_status(stations, now=None):
    """One freshness policy for Station Control, the banner and operations."""
    from datetime import timezone
    from app.models import LiveQueueSnapshot, StatsState
    now = time.time() if now is None else now
    ids = [station.id for station in stations]
    samples = {row.scope: row.data for row in StatsState.query.filter(StatsState.scope.in_(ids))}
    snapshots = {row.station_id: row for row in LiveQueueSnapshot.query.filter(LiveQueueSnapshot.station_id.in_(ids))}

    def timestamp(at):
        return at.replace(tzinfo=at.tzinfo or timezone.utc).timestamp() if at else 0

    result = {}
    for station in stations:
        snapshot = snapshots.get(station.id)
        sample = samples.get(station.id, {})
        candidates = []
        if 0 <= now - sample.get('at', 0) <= 45:
            candidates.append((sample['at'], sample.get('online'), sample.get('listeners')))
        at = timestamp(snapshot.broadcast_observed_at) if snapshot else 0
        if 0 <= now - at <= 15:
            candidates.append((at, snapshot.broadcast_online, snapshot.listeners))
        at, online, listeners = max(candidates, key=lambda row: row[0]) if candidates else (None, None, None)
        tone = ((snapshot.mixer or {}).get('tone') if snapshot and not snapshot.error_code
                and 0 <= now - timestamp(snapshot.observed_at) <= 10 and online is True else None)
        result[station.slug] = dict(online=online, listeners=listeners, observed_at=at, tone=tone,
            name=station.name, lifecycle=station.lifecycle_state,
            ready=bool(station.enabled and station.lifecycle_state == 'ready'
                       and station.stream and station.stream.enabled),
            stream=station.stream.public_path if station.enabled and station.stream and station.stream.enabled
                   and station.lifecycle_state == 'ready' else '',
            enabled=station.desired_state == 'running', revision=station.broadcast_revision,
            status=station.broadcast_status, error=station.broadcast_error)
    return result
