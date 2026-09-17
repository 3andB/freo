"""Statistics presentation services, independent of on-air operations."""
import math
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy import func, case
from app.extensions import db
from app.models import (Station, Track, SelectionDecision, ListenerVote, ListenerFeedbackEvent,
    StatsState, StatsBucket, AudiencePresence, GeoBucket, GeoReach, StorageSnapshot, BroadcastIncident,
    FeedbackTransition, TimedEventOccurrence, TrafficPlacement)
from app.services.availability import tracks_for


def stamp(value):
    return int(value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()) if value else None


def window(args, default_zone='UTC', now=None):
    now = int(time.time()) if now is None else now
    zone_name = args.get('timezone', default_zone)
    try:
        zone = ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('Choose a valid timezone') from None
    end = now
    preset = args.get('range', '24h')
    local = datetime.fromtimestamp(now, zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    rolling = {'live': 3600, '24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400, '365d': 365 * 86400}
    if preset in rolling:
        start = end - rolling[preset]
    elif preset == 'yesterday':
        start, end = int((midnight - timedelta(days=1)).timestamp()), int(midnight.timestamp())
    elif preset == 'month':
        start = int(midnight.replace(day=1).timestamp())
    elif preset == 'year':
        start = int(midnight.replace(month=1, day=1).timestamp())
    elif preset == 'custom':
        try:
            start = int(datetime.strptime(args.get('start', ''), '%Y-%m-%d').replace(tzinfo=zone).timestamp())
            end = min(now, int((datetime.strptime(args.get('end', ''), '%Y-%m-%d') + timedelta(days=1)).replace(tzinfo=zone).timestamp()))
        except (ValueError, TypeError):
            raise ValueError('Choose valid start and end dates') from None
    else:
        raise ValueError('Choose a valid date range')
    if start >= end or end - start > 5 * 366 * 86400:
        raise ValueError('Choose a date range of up to five years, ending after it starts')
    return dict(start=start, end=end, timezone=zone_name, range=preset)


def aggregate(scope, start, end, now=None):
    now = int(time.time()) if now is None else now
    resolution = 'minute' if start >= now - 89 * 86400 and end - start <= 3 * 86400 else 'hour'
    step = 60 if resolution == 'minute' else 3600
    rows = StatsBucket.query.filter_by(scope=scope, resolution=resolution).filter(
        StatsBucket.at >= start // step * step, StatsBucket.at < end).order_by(StatsBucket.at).all()
    total = dict(observed_seconds=0., listener_seconds=0., online_seconds=0., bytes_sent=0., transfer_seconds=0., peak=0)
    points = {}
    state = db.session.get(StatsState, scope)
    observed_until = min(now, state.data.get('at', now)) if state else now
    chart_step = max(step, math.ceil((end - start) / 180 / step) * step)
    for row in rows:
        bucket_end = min(row.at + step, observed_until)
        overlap = max(0, min(end, bucket_end) - max(start, row.at)) / max(1, bucket_end - row.at)
        # Edge allocation is explicitly approximate at the retained resolution.
        data = {k: getattr(row, k) * overlap for k in total if k != 'peak'}
        for k, value in data.items():
            total[k] += value
        total['peak'] = max(total['peak'], row.peak)
        at = int((row.at - start) // chart_step) * chart_step + start
        at = max(start, at)
        point = points.setdefault(at, dict(at=at, observed=0, listener_seconds=0, peak=0, bytes=0))
        point['observed'] += data['observed_seconds']
        point['listener_seconds'] += data['listener_seconds']
        point['peak'] = max(point['peak'], row.peak)
        point['bytes'] += data['bytes_sent']
    timeline = []
    for at in range(start, end, chart_step):
        point = points.get(at, dict(at=at, observed=0, listener_seconds=0, peak=0, bytes=0))
        point['average'] = point.pop('listener_seconds') / point['observed'] if point['observed'] else None
        timeline.append(point)
    total.update(average=total['listener_seconds'] / total['observed_seconds'] if total['observed_seconds'] else None,
        listener_hours=total['listener_seconds'] / 3600,
        coverage=min(100, 100 * total['observed_seconds'] / (end - start)),
        transfer_coverage=min(100, 100 * total['transfer_seconds'] / (end - start)),
        uptime=100 * total['online_seconds'] / total['observed_seconds'] if total['observed_seconds'] else None)
    return dict(total=total, timeline=timeline, resolution_seconds=step)


def ranking(scope, start, end, limit=100):
    begin, finish = (datetime.fromtimestamp(x, timezone.utc) for x in (start, end))
    query = db.session.query(Track.id, Track.uuid, Track.title, Track.artist, Track.artist_id,
        Track.station_id, func.count(SelectionDecision.id).label('plays')).join(SelectionDecision, SelectionDecision.track_id == Track.id).filter(
        SelectionDecision.status == 'started', SelectionDecision.started_at >= begin, SelectionDecision.started_at < finish)
    if scope:
        query = query.filter(SelectionDecision.station_id == scope)
    all_plays = query.group_by(Track.id, Track.uuid, Track.title, Track.artist, Track.artist_id, Track.station_id)
    songs = [dict(r._mapping) for r in all_plays.order_by(func.count(SelectionDecision.id).desc(), Track.id).limit(limit)]
    artists_query = db.session.query(Track.artist_id, Track.artist, Track.station_id,
        func.count(SelectionDecision.id).label('plays')).join(SelectionDecision, SelectionDecision.track_id == Track.id).filter(
        SelectionDecision.status == 'started', SelectionDecision.started_at >= begin, SelectionDecision.started_at < finish)
    if scope:
        artists_query = artists_query.filter(SelectionDecision.station_id == scope)
    artists = [dict(r._mapping) for r in artists_query.group_by(Track.artist_id, Track.artist, Track.station_id).order_by(func.count(SelectionDecision.id).desc()).limit(limit)]
    count_query = SelectionDecision.query.filter(SelectionDecision.status == 'started', SelectionDecision.started_at >= begin, SelectionDecision.started_at < finish)
    if scope:
        count_query = count_query.filter_by(station_id=scope)
    plays = count_query.filter(SelectionDecision.track_id.isnot(None)).count()
    imaging = count_query.filter(SelectionDecision.imaging_asset_id.isnot(None)).count()
    unique = all_plays.count()
    votes = db.session.query(Track.id, Track.uuid, Track.title, Track.artist, Track.station_id,
        func.sum(case((ListenerVote.value == 1, 1), else_=0)).label('up'),
        func.sum(case((ListenerVote.value == -1, 1), else_=0)).label('down')).join(ListenerVote, ListenerVote.track_id == Track.id).filter(ListenerVote.excluded.is_(False), ListenerVote.value != 0)
    if scope:
        votes = votes.filter(ListenerVote.station_id == scope)
    votes = votes.group_by(Track.id, Track.uuid, Track.title, Track.artist, Track.station_id)
    # Keep each ranking bounded in SQL, including dislike-heavy songs.
    up = func.sum(case((ListenerVote.value == 1, 1), else_=0))
    down = func.sum(case((ListenerVote.value == -1, 1), else_=0))
    def records(q):
        output = []
        for row in q.limit(limit):
            item = dict(row._mapping)
            item['total'] = item['up'] + item['down']
            item['approval'] = round(item['up'] / item['total'] * 100, 1) if item['total'] else None
            output.append(item)
        return output
    liked = records(votes.order_by(up.desc(), Track.id))
    disliked = records(votes.order_by(down.desc(), Track.id))
    approval = records(votes.having(up + down >= 10).order_by((up * 1.0 / (up + down)).desc(), (up + down).desc()))
    preference = ListenerVote.query.filter(ListenerVote.excluded.is_(False))
    if scope:
        preference = preference.filter_by(station_id=scope)
    positive, negative = preference.filter_by(value=1).count(), preference.filter_by(value=-1).count()
    events = ListenerFeedbackEvent.query.filter(ListenerFeedbackEvent.action == 'vote', ListenerFeedbackEvent.created_at >= begin, ListenerFeedbackEvent.created_at < finish)
    transitions = FeedbackTransition.query.filter(FeedbackTransition.at >= start, FeedbackTransition.at < end)
    if scope:
        events = events.filter_by(station_id=scope)
        transitions = transitions.filter_by(scope=scope)
    changes = transitions.filter(FeedbackTransition.old_value != FeedbackTransition.new_value).count()
    removals = transitions.filter(FeedbackTransition.old_value != 0, FeedbackTransition.new_value == 0).count()
    library = tracks_for(scope) if scope else Track.query.filter_by(deleted_at=None)
    library_count = library.count()
    aired_ids = count_query.filter(SelectionDecision.track_id.isnot(None)).with_entities(SelectionDecision.track_id)
    library_aired = library.filter(Track.id.in_(aired_ids)).count()
    return dict(songs=songs, artists=artists, liked=liked, disliked=disliked, approval=approval, plays=plays,
        imaging_plays=imaging, unique_songs=unique, library_count=library_count,
        rotation_coverage=100 * library_aired / library_count if library_count else None,
        feedback=dict(up=positive, down=negative, total=positive + negative,
            approval=100 * positive / (positive + negative) if positive + negative else None,
            activity=events.count(), changes=changes, removals=removals))


def geography(scope, source, mode, start, end, now):
    from . import geo
    locations = {}
    def add(location, value, seconds=0, first=None, last=None):
        place = location.get('place', 'unknown')
        row = locations.setdefault(place, dict(location, count=0, seconds=0, first_seen=None, last_seen=None))
        row['count'] += value
        row['seconds'] += seconds
        if first is not None:
            row['first_seen'] = min(first, row['first_seen'] or first)
        if last is not None:
            row['last_seen'] = max(last, row['last_seen'] or last)
    if mode == 'live':
        query = AudiencePresence.query.filter_by(source=source).filter(AudiencePresence.last_seen >= now - (90 if source == 'website' else 45))
        if scope:
            query = query.filter_by(scope=scope)
        states = {r.scope: r.data for r in StatsState.query.all()}
        for row in query:
            if source == 'stream':
                data = states.get(row.scope, {})
                if data.get('online') is not True or row.last_seen < data.get('clients_at', 0):
                    continue
            add(row.geo, 1, first=row.first_seen, last=row.last_seen)
    elif mode == 'all':
        query = GeoReach.query.filter_by(source=source)
        if scope:
            query = query.filter_by(scope=scope)
        for row in query:
            add(row.geo, row.sessions, row.observed_seconds, row.first_seen, row.last_seen)
    else:
        query = GeoBucket.query.filter_by(source=source).filter(GeoBucket.at >= start // 3600 * 3600, GeoBucket.at < end)
        if scope:
            query = query.filter_by(scope=scope)
        for row in query:
            add(row.geo, row.sessions, row.observed_seconds, row.at, row.at + 3600)
    result = sorted(locations.values(), key=lambda r: (-r['count'], -r['seconds']))
    return dict(locations=result[:2000], total=sum(r['count'] for r in result),
        located=sum(r['count'] for r in result if r.get('lat') is not None),
        countries=len({r['country_code'] for r in result if r['country_code'] != 'XX'}),
        truncated=len(result) > 2000, source=source, mode=mode, database=geo.status())


def dashboard(scope, args, now=None):
    now = int(time.time()) if now is None else now
    station = db.session.get(Station, scope) if scope else None
    period = window(args, station.timezone if station else 'UTC', now)
    start, end = period['start'], period['end']
    source, mode = args.get('source', 'stream'), args.get('map', 'live')
    if source not in ('stream', 'website') or mode not in ('live', 'history', 'all'):
        raise ValueError('Choose a valid map view')
    state = db.session.get(StatsState, scope)
    current = dict(state.data) if state else {}
    fresh = bool(current.get('at') and 0 <= now - current['at'] <= 45)
    stats = aggregate(scope, start, end, now)
    previous = aggregate(scope, start - (end - start), start, now) if args.get('compare') == '1' else None
    music = ranking(scope, start, end)
    latest_storage = StorageSnapshot.query.filter_by(scope=scope).order_by(StorageSnapshot.at.desc()).first()
    storage_history = StorageSnapshot.query.filter_by(scope=scope).filter(StorageSnapshot.at >= start, StorageSnapshot.at < end).order_by(StorageSnapshot.at).all()
    stride = max(1, math.ceil(len(storage_history) / 180))
    zones = ZoneInfo(period['timezone'])
    local = datetime.fromtimestamp(now, zones).replace(hour=0, minute=0, second=0, microsecond=0)
    transfer = {}
    for name, begin in [('month', local.replace(day=1)), ('year', local.replace(month=1, day=1))]:
        data = aggregate(scope, int(begin.timestamp()), now + 1, now)['total']
        transfer[name] = dict(bytes=data['bytes_sent'], coverage=data['transfer_coverage'])
    lifetime = db.session.get(StatsBucket, (scope, 'lifetime', 0))
    transfer['total'] = dict(bytes=lifetime.bytes_sent if lifetime else 0, since=current.get('since'))
    incidents = BroadcastIncident.query.filter(BroadcastIncident.started_at < end,
        (BroadcastIncident.ended_at.is_(None) | (BroadcastIncident.ended_at >= start)))
    if scope:
        incidents = incidents.filter_by(scope=scope)
    names = {s.id: s.name for s in Station.query.all()}
    channels = []
    for s in Station.query.filter_by(deleted_at=None).order_by(Station.name):
        row = db.session.get(StatsState, s.id)
        data = row.data if row else {}
        value = aggregate(s.id, start, end, now)['total']
        channels.append(dict(id=s.id, name=s.name, slug=s.slug, current=data.get('listeners') if now - data.get('at', 0) <= 45 else None,
            online=data.get('online'), **value))
    begin, finish = (datetime.fromtimestamp(x, timezone.utc) for x in (start, end))
    failures = SelectionDecision.query.filter(SelectionDecision.status == 'failed', SelectionDecision.selected_at >= begin, SelectionDecision.selected_at < finish)
    if scope:
        failures = failures.filter_by(station_id=scope)
    outcomes = {}
    for name, model, column in [('events', TimedEventOccurrence, TimedEventOccurrence.state),
                                 ('commercials', TrafficPlacement, TrafficPlacement.status)]:
        query = db.session.query(column, func.count(model.id)).filter(
            model.scheduled_for_utc >= begin, model.scheduled_for_utc < finish)
        if scope:
            query = query.filter(model.station_id == scope)
        outcomes[name] = dict(query.group_by(column).all())
    return dict(period=period, now=now, current=current, fresh=fresh, stats=stats,
        previous=previous['total'] if previous else None, previous_timeline=previous['timeline'] if previous else None,
        music=music, geography=geography(scope, source, mode, start, end, now), transfer=transfer,
        storage=dict(at=latest_storage.at, **latest_storage.data) if latest_storage else None,
        storage_history=[dict(at=r.at, bytes=r.data.get('total', 0)) for r in storage_history[::stride]],
        channels=channels, incidents=[dict(kind=r.kind, station=names.get(r.scope, 'Archived channel'),
            started_at=r.started_at, ended_at=r.ended_at, detail=r.detail) for r in incidents.order_by(BroadcastIncident.started_at.desc()).limit(100)],
        failed_plays=failures.count(), outcomes=outcomes, timezone=period['timezone'])


def feedback_transition(row, old_value, old_excluded, now):
    db.session.flush()
    db.session.add(FeedbackTransition(scope=row.station_id, track_id=row.track_id, vote_id=row.id, revision=row.revision,
        at=stamp(now), old_value=old_value, new_value=row.value, old_excluded=old_excluded, new_excluded=row.excluded or False))
