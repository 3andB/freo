"""Transactional samples, coverage-aware integrals and durable geographic reach."""
import hashlib
from datetime import datetime, timezone
from sqlalchemy import text
from app.extensions import db
from app.models import (Station, StatsState, AudienceSample, StatsBucket, AudiencePresence,
                        GeoBucket, GeoReach, BroadcastIncident, LiveQueueSnapshot)
from . import geo


def lock(scope):
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 714500000 + scope})


def state(scope):
    row = db.session.get(StatsState, scope)
    if row is None:
        row = StatsState(scope=scope, data={})
        db.session.add(row)
        db.session.flush()
    return row


def month(at):
    return int(datetime.fromtimestamp(at, timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())


def bounds(at, resolution):
    if resolution == 'lifetime':
        return 0, 32503680000
    if resolution == 'month':
        start = month(at)
        dt = datetime.fromtimestamp(start, timezone.utc)
        end = dt.replace(year=dt.year + 1, month=1) if dt.month == 12 else dt.replace(month=dt.month + 1)
        return start, int(end.timestamp())
    step = {'minute': 60, 'hour': 3600}[resolution]
    return int(at // step) * step, (int(at // step) + 1) * step


def accumulate(scope, start, end, listeners=None, online=None, transfer=None, transfer_complete=True):
    duration = end - start
    if duration <= 0:
        return
    for resolution in ('minute', 'hour', 'month', 'lifetime'):
        point, assigned = start, 0
        while point < end:
            at, boundary = bounds(point, resolution)
            finish = min(end, boundary)
            row = db.session.get(StatsBucket, (scope, resolution, at))
            if row is None:
                row = StatsBucket(scope=scope, resolution=resolution, at=at, observed_seconds=0,
                    listener_seconds=0, online_seconds=0, peak=0, bytes_sent=0, transfer_seconds=0)
                db.session.add(row)
            seconds = finish - point
            if listeners is not None:
                row.observed_seconds += seconds
                row.listener_seconds += listeners * seconds
                row.online_seconds += seconds * bool(online)
                row.peak = max(row.peak, listeners)
            if transfer is not None:
                # Integer allocation preserves each counter delta exactly across buckets.
                portion = int(transfer * (finish - start) / duration) - assigned
                assigned += portion
                row.bytes_sent += portion
                row.transfer_seconds += seconds if transfer_complete else 0
            point = finish


def presence(scope, source, key, location, now):
    row = db.session.get(AudiencePresence, (scope, source, key))
    new = row is None or (source == 'website' and now - row.last_seen > 90)
    arrival = new or row.geo.get('place') != location.get('place')
    previous = row.last_seen if row else now
    if row and now <= previous:
        return
    if row is None:
        row = AudiencePresence(scope=scope, source=source, key=key, first_seen=now, last_seen=now, geo=location)
        db.session.add(row)
    if new:
        row.first_seen = now
    row.last_seen = now
    row.geo = location
    place = location.get('place', 'unknown')
    reach = db.session.get(GeoReach, (scope, source, place))
    if reach is None:
        reach = GeoReach(scope=scope, source=source, place=place, geo=location,
            first_seen=now, last_seen=now, sessions=0, observed_seconds=0)
        db.session.add(reach)
    reach.last_seen = now
    reach.sessions += int(arrival)
    gap = now - previous
    seconds = gap if not new and 0 < gap <= (90 if source == 'website' else 45) else 0
    reach.observed_seconds += seconds
    # Split observed duration at UTC hour boundaries; sessions start at observation.
    segments = [(now // 3600 * 3600, 0)] if not seconds else []
    point = now - seconds
    while point < now:
        at = point // 3600 * 3600
        finish = min(now, at + 3600)
        segments.append((at, finish - point))
        point = finish
    if not any(at == now // 3600 * 3600 for at, _ in segments):
        segments.append((now // 3600 * 3600, 0))
    for at, observed in segments:
        bucket = db.session.get(GeoBucket, (scope, source, place, at))
        if bucket is None:
            bucket = GeoBucket(scope=scope, source=source, place=place, at=at, geo=location, sessions=0, observed_seconds=0)
            db.session.add(bucket)
        # A session continuing into another hour must remain visible on that map.
        # Historical counts are session-hours, not deduplicated people.
        bucket.sessions += int((arrival and at == now // 3600 * 3600) or (not new and previous < at))
        bucket.observed_seconds += observed


def incident(scope, kind, active, now, detail):
    row = BroadcastIncident.query.filter_by(scope=scope, kind=kind, ended_at=None).first()
    if active and not row:
        db.session.add(BroadcastIncident(scope=scope, kind=kind, started_at=now, detail=detail))
    elif not active and row:
        row.ended_at = now


def tick(observations, now):
    """Observations are fetched before acquiring DB locks; one commit includes checkpoints."""
    lock(0)
    overall = state(0)
    if now <= overall.data.get('at', 0):
        return
    stations = Station.query.filter_by(deleted_at=None).order_by(Station.id).all()
    current = {}
    for station in stations:
        lock(station.id)
        stored = state(station.id)
        old = stored.data
        item = dict(observations.get(station.id) or dict(online=None, listeners=None, clients=None))
        clients = item.pop('clients', None)
        item['at'] = now
        item['since'] = old.get('since', now)
        item['clients_at'] = now if clients is not None else old.get('clients_at', 0)
        elapsed = now - old.get('at', now)
        if 0 < elapsed <= 45:
            listeners = old.get('listeners') if item.get('listeners') is not None else None
            same_epoch = (item.get('epoch') and item.get('source_epoch') and
                (item['epoch'], item['source_epoch']) == (old.get('epoch'), old.get('source_epoch')))
            transfer = None
            if same_epoch and item.get('bytes') is not None and old.get('bytes') is not None and item['bytes'] >= old['bytes']:
                transfer = item['bytes'] - old['bytes']
            elif item.get('online') is False and old.get('online') is False:
                transfer = 0
            accumulate(station.id, old['at'], now, listeners, old.get('online'), transfer)
            item['transfer_delta'] = transfer
        else:
            item['transfer_delta'] = None
        if clients is not None:
            for client in clients:
                if not client.get('id'):
                    continue
                key = hashlib.sha256(f"{item.get('epoch')}:{station.id}:{client['id']}".encode()).hexdigest()
                saved = db.session.get(AudiencePresence, (station.id, 'stream', key))
                location = saved.geo if saved and saved.geo.get('place') != 'unknown' else geo.lookup(client.get('ip', ''))
                presence(station.id, 'stream', key, location, now)
        incident(station.id, 'observation_gap', item.get('online') is None, now, 'Icecast observation unavailable')
        if item.get('online') is not None:
            incident(station.id, 'stream_offline', station.desired_state == 'running' and not item['online'], now, 'Expected stream mount is offline')
        snapshot = db.session.get(LiveQueueSnapshot, station.id)
        seen = int(snapshot.observed_at.replace(tzinfo=timezone.utc).timestamp()) if snapshot else 0
        fresh = now - seen < 30
        incident(station.id, 'playout_unobserved', station.desired_state == 'running' and not fresh, now, 'Playout worker observation is stale')
        silent = bool(fresh and item.get('online') and snapshot.program_rms is not None and snapshot.program_rms < .001)
        silence_since = old.get('silence_since') if silent else None
        if silent and silence_since is None:
            silence_since = now
        item['silence_since'] = silence_since
        incident(station.id, 'silence', bool(silent and now - silence_since >= 30), now, 'Program RMS below -60 dBFS for at least 30 seconds')
        stored.data = item
        current[station.id] = item
        db.session.add(AudienceSample(scope=station.id, at=now, listeners=item.get('listeners'), online=item.get('online')))
    known = all(v.get('listeners') is not None for v in current.values())
    item = dict(at=now, since=overall.data.get('since', now),
        listeners=sum(v['listeners'] for v in current.values()) if known else None,
        known_listeners=sum(v.get('listeners') or 0 for v in current.values()),
        online=all(current[s.id].get('online') for s in stations if s.desired_state == 'running') if known else None,
        channels=len(current), known_channels=sum(v.get('listeners') is not None for v in current.values()), geo=geo.status())
    previous = overall.data
    if 0 < now - previous.get('at', now) <= 45:
        complete = all(v['transfer_delta'] is not None for v in current.values())
        transfer = sum(v['transfer_delta'] or 0 for v in current.values())
        # Channel membership changes must not fabricate a simultaneous integral.
        listeners = previous.get('listeners') if known and previous.get('members') == list(current) else None
        accumulate(0, previous['at'], now, listeners, previous.get('online'), transfer, complete)
    item['members'] = list(current)
    overall.data = item
    db.session.add(AudienceSample(scope=0, at=now, listeners=item['listeners'], online=item['online']))
    # Preserve an instantaneous peak even before the first complete interval.
    for scope, value in [(0, item), *current.items()]:
        if value.get('listeners') is not None:
            for resolution in ('minute', 'hour', 'month', 'lifetime'):
                at, _ = bounds(now, resolution)
                bucket = db.session.get(StatsBucket, (scope, resolution, at))
                if bucket is None:
                    bucket = StatsBucket(scope=scope, resolution=resolution, at=at, peak=value['listeners'])
                    db.session.add(bucket)
                else:
                    bucket.peak = max(bucket.peak, value['listeners'])
    if now // 3600 != previous.get('at', 0) // 3600:
        AudienceSample.query.filter(AudienceSample.at < now - 14 * 86400).delete()
        StatsBucket.query.filter_by(resolution='minute').filter(StatsBucket.at < now - 90 * 86400).delete()
        StatsBucket.query.filter_by(resolution='hour').filter(StatsBucket.at < now - 5 * 366 * 86400).delete()
        GeoBucket.query.filter(GeoBucket.at < now - 5 * 366 * 86400).delete()
        AudiencePresence.query.filter(AudiencePresence.last_seen < now - 86400).delete()
    db.session.commit()
