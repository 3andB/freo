"""Anonymous session rollups from the existing Icecast presence observations."""
import hashlib
import json
import math
from datetime import timezone
from app.extensions import db
from app.models import AudiencePresence, SessionBucket, StatsState, Station

DEVICES = ('desktop', 'mobile', 'tablet', 'other/unknown')
PLAYERS = ('Chrome', 'Edge', 'Firefox', 'Safari', 'Opera', 'VLC', 'Winamp',
           'foobar2000', 'iTunes', 'Other/unknown')
THRESHOLDS = (60, 300, 900, 1800, 3600)
BANDS = ('Under 1 minute', '1–5 minutes', '5–15 minutes', '15–30 minutes',
         '30–60 minutes', '60+ minutes')


def classify(agent):
    """Conservative categories only: an audio player alone says nothing about device."""
    agent = agent[:2048].lower() if isinstance(agent, str) else ''
    device, player = 'other/unknown', 'Other/unknown'
    if not agent or any(token in agent for token in ('bot', 'crawler', 'spider')):
        return device, player
    if any(token in agent for token in ('ipad', 'tablet', 'kindle', 'silk/')):
        device = 'tablet'
    elif any(token in agent for token in ('iphone', 'ipod', 'windows phone', 'mobi')):
        device = 'mobile'
    elif 'android' in agent and 'mozilla/' in agent and not any(token in agent for token in (' tv', 'aft', 'smart-tv')):
        device = 'tablet'  # Android's browser UA omits Mobile on tablets.
    elif any(token in agent for token in ('windows nt', 'macintosh', 'x11', 'cros')):
        device = 'desktop'
    for tokens, name in (
        (('vlc/', 'libvlc'), 'VLC'), (('winamp',), 'Winamp'),
        (('foobar2000',), 'foobar2000'), (('itunes/',), 'iTunes'),
        (('edg/', 'edga/', 'edgios/'), 'Edge'), (('opr/', 'opera'), 'Opera'),
        (('firefox/', 'fxios/'), 'Firefox'), (('chrome/', 'crios/'), 'Chrome'),
        (('version/',), 'Safari'),
    ):
        if any(token in agent for token in tokens):
            if name != 'Safari' or 'safari/' in agent:
                player = name
            break
    return device, player


def epoch(item):
    return hashlib.sha256(json.dumps([item.get('epoch'), item.get('source_epoch')]).encode()).hexdigest()


def server_epoch(item):
    return hashlib.sha256(str(item['epoch']).encode()).hexdigest() if item.get('epoch') is not None else None


def key(scope, item, client):
    return hashlib.sha256(json.dumps([scope, epoch(item), str(client['id'])]).encode()).hexdigest()


def empty():
    return dict(starts=0, completed=0, interrupted=0, duration_seconds=0,
                covered_seconds=0, bands=[0] * len(BANDS), devices={}, players={})


def increment(scope, at, **values):
    at = at // 3600 * 3600
    row = db.session.get(SessionBucket, (scope, at))
    if row is None:
        row = SessionBucket(scope=scope, at=at, data=empty())
        db.session.add(row)
    data = dict(row.data)
    for name, value in values.items():
        if name in ('devices', 'players'):
            counts = dict(data[name])
            counts[value] = counts.get(value, 0) + 1
            data[name] = counts
        elif name == 'bands':
            counts = list(data[name])
            counts[value] += 1
            data[name] = counts
        else:
            data[name] += value
    row.data = data


def finish(row, interrupted):
    state = dict(row.listening)
    if state['status'] != 'active':
        return
    if interrupted:
        increment(row.scope, state['at'], interrupted=1)
    else:
        band = sum(state['seconds'] >= threshold for threshold in THRESHOLDS)
        increment(row.scope, state['at'], completed=1, duration_seconds=state['seconds'], bands=band)
    state['status'] = 'interrupted' if interrupted else 'completed'
    row.listening = state


def observe(scope, clients, item, old, now):
    """Called after geographic presence updates, inside the collector transaction."""
    item['sessions_since'] = old.get('sessions_since', now)
    item['session_clients_at'] = now if clients is not None else old.get('session_clients_at', 0)
    item['session_clients_valid'] = clients is not None
    # Only intervals bounded by two usable lists contribute coverage.
    if clients is not None and old.get('session_clients_valid') and 0 < now - old['at'] <= 45:
        point = old['at']
        while point < now:
            end = min(now, (point // 3600 + 1) * 3600)
            increment(scope, point, covered_seconds=end - point)
            point = end
    rows = AudiencePresence.query.filter_by(scope=scope, source='stream').filter(
        (AudiencePresence.last_seen >= now - 45) | (AudiencePresence.listening['status'].as_string() == 'active')).all()
    present = {key(scope, item, c): c for c in clients or [] if c.get('id') is not None}
    current_epoch = epoch(item)
    for row in rows:
        state = row.listening
        if not state or state['status'] != 'active':
            continue
        reset = (server_epoch(item) is not None and state.get('server_epoch') is not None
                 and server_epoch(item) != state['server_epoch']) or (
                     item.get('online') is True and state['epoch'] != current_epoch)
        if now - state['at'] > 45 or reset:
            finish(row, True)
        elif clients is not None and row.key not in present:
            finish(row, False)
    for row in rows:
        client = present.get(row.key)
        if client is None:
            continue
        state = row.listening
        if not state or state['status'] != 'active':
            device, player = classify(client.get('agent'))
            state = dict(status='active', at=now, seconds=0, device=device, player=player,
                         epoch=current_epoch, server_epoch=server_epoch(item))
            increment(scope, now, starts=1, devices=device, players=player)
        else:
            state = dict(state, seconds=state['seconds'] + now - state['at'], at=now)
        row.listening = state


def expire(now):
    # Also close abandoned/archived station sessions before presence cleanup.
    for row in AudiencePresence.query.filter_by(source='stream').filter(
            AudiencePresence.last_seen < now - 45, AudiencePresence.listening.isnot(None)):
        if row.listening and row.listening['status'] == 'active':
            finish(row, True)
    SessionBucket.query.filter(SessionBucket.at < now - 5 * 366 * 86400).delete()


def report(scope, start, end, now):
    begin, finish_at = start // 3600 * 3600, min(now, math.ceil(end / 3600) * 3600)
    query = SessionBucket.query.filter(SessionBucket.at >= begin, SessionBucket.at < finish_at)
    states_query = StatsState.query.filter(StatsState.scope > 0)
    if scope:
        query = query.filter_by(scope=scope)
        states_query = states_query.filter_by(scope=scope)
    states = {r.scope: r.data for r in states_query}
    since_values = [s['sessions_since'] for s in states.values() if s.get('sessions_since') is not None]
    since = min(since_values) if since_values else None
    total = empty()
    step = max(3600, math.ceil(max(1, finish_at - begin) / 180 / 3600) * 3600)
    points = {}
    for row in query:
        at = begin + (row.at - begin) // step * step
        point = points.setdefault(at, dict(at=at, starts=0, completed=0, duration_seconds=0, covered_seconds=0))
        for name in point:
            if name != 'at':
                point[name] += row.data[name]
        for name, value in row.data.items():
            if name in ('devices', 'players'):
                for category, count in value.items():
                    total[name][category] = total[name].get(category, 0) + count
            elif name == 'bands':
                total[name] = [a + b for a, b in zip(total[name], value)]
            else:
                total[name] += value
    timeline = []
    for at in range(begin, finish_at, step):
        p = points.get(at, dict(at=at, starts=0, completed=0, duration_seconds=0, covered_seconds=0))
        p['average_seconds'] = p['duration_seconds'] / p['completed'] if p['completed'] else None
        if not p['covered_seconds'] and not p['starts'] and not p['completed']:
            p['starts'] = p['completed'] = None
        timeline.append(p)
    # Include unobserved stations, and stop expecting coverage after archival.
    station_query = Station.query.filter_by(id=scope) if scope else Station.query
    stations = station_query.all()
    denominator = sum(max(0, min(finish_at, int(s.deleted_at.replace(tzinfo=timezone.utc).timestamp()) if s.deleted_at else finish_at) - begin)
                      for s in stations)
    denominator = max(1, denominator)
    coverage = min(100, 100 * total['covered_seconds'] / denominator)
    active_query = AudiencePresence.query.filter_by(source='stream').filter(AudiencePresence.last_seen >= now - 45)
    if scope:
        active_query = active_query.filter_by(scope=scope)
    current_scopes = {s.id for s in stations if not s.deleted_at}
    active = []
    for row in active_query:
        state = states.get(row.scope, {})
        if (row.scope in current_scopes and row.listening and row.listening['status'] == 'active' and state.get('online') is True
                and 0 <= now - state.get('session_clients_at', 0) <= 45
                and row.last_seen >= state.get('session_clients_at', 0)):
            active.append(row.listening)
    current_available = bool(current_scopes) and all(
        states.get(identifier, {}).get('session_clients_valid') and
        0 <= now - states[identifier].get('session_clients_at', 0) <= 45 for identifier in current_scopes)
    available = bool(total['covered_seconds'] or total['starts'] or total['completed'] or total['interrupted'])
    def categories(names, field):
        return [dict(name=name, starts=total[field].get(name, 0) if available else None,
                     share=100 * total[field].get(name, 0) / total['starts'] if total['starts'] else None,
                     current=sum(a['device' if field == 'devices' else 'player'] == name for a in active)
                     if current_available else None) for name in names]
    return dict(sessions=dict(
        since=since, available=available, start=begin, end=finish_at, resolution_seconds=3600,
        coverage=coverage, starts=total['starts'] if available else None,
        completed=total['completed'] if available else None,
        interrupted=total['interrupted'] if available else None,
        active=len(active) if current_available else None,
        average_seconds=total['duration_seconds'] / total['completed'] if total['completed'] else None,
        bands=[dict(label=label, count=count if available else None,
                    share=100 * count / total['completed'] if total['completed'] else None)
               for label, count in zip(BANDS, total['bands'])],
        retention=[dict(seconds=threshold, share=100 * sum(total['bands'][i + 1:]) / total['completed']
                        if total['completed'] else None) for i, threshold in enumerate(THRESHOLDS)],
        timeline=timeline), devices=dict(groups=categories(DEVICES, 'devices'), players=categories(PLAYERS, 'players')))
