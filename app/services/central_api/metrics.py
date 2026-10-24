"""Minute observations and durable, replaceable hourly reporting history."""
import os
import platform
import shutil
from datetime import datetime, timezone
from flask import current_app
from sqlalchemy import func
from app.extensions import db
from app.version import VERSION
from app.models import Station, Track, AutomationHeartbeat, CentralStationState, CentralHourlyMetric
from app.services.availability import track_scope
from app.services.broadcast_status import observation
from .client import APIError

METRIC_KEYS = ('current_listeners', 'songs_in_library', 'artists', 'albums',
               'library_duration_seconds', 'library_storage_bytes', 'stream_running', 'scheduler_running')


def machine_snapshot(extended=False):
    install_type = current_app.config['FREO_INSTALL_TYPE']
    if install_type == 'freo-live':
        install_type = 'freo-studio'
    if install_type not in ('self-hosted', 'freo-studio'):
        raise APIError('invalid_install_type')
    try:
        page_size, pages = os.sysconf('SC_PAGE_SIZE'), os.sysconf('SC_PHYS_PAGES')
        ram = page_size * pages if page_size > 0 and pages > 0 else None
        if ram is not None and ram > 2**63 - 1:
            ram = None
    except (ValueError, OSError):
        ram = None
    try:
        disk = shutil.disk_usage(current_app.config['FREO_MEDIA_ROOT'] or '/var/lib/freo')
        total, free = disk.total, disk.free
    except OSError:
        total = free = None
    if total is not None and not 0 <= free <= total <= 2**63 - 1:
        total = free = None
    try:
        cpu_count = os.cpu_count()
    except OSError:
        cpu_count = None
    if type(cpu_count) is not int or not 1 <= cpu_count <= 65536:
        cpu_count = None
    result = dict(freo_version=VERSION, install_type=install_type if extended or install_type == 'self-hosted' else 'freo-live',
                  os=(platform.system() or 'unknown')[:128], architecture=(platform.machine() or 'unknown')[:128], cpu_count=cpu_count,
                  ram_bytes=ram, disk_total_bytes=total, disk_free_bytes=free)
    label = current_app.config.get('FREO_DEPLOYMENT_LABEL')
    lifecycle = current_app.config.get('FREO_INSTALLATION_LIFECYCLE')
    if label is not None and (not isinstance(label, str) or len(label.strip()) > 64 or '\x00' in label):
        raise APIError('invalid_deployment_label')
    if lifecycle not in (None, '', 'active', 'decommissioned'):
        raise APIError('invalid_installation_lifecycle')
    if extended:
        if label is not None:
            result['deployment_label'] = label.strip() or None
        if lifecycle:
            result['lifecycle_state'] = lifecycle
    return result


def seconds(value):
    return value.replace(tzinfo=timezone.utc).timestamp() if value and value.tzinfo is None else value.timestamp() if value else 0


def channel_lifecycle(station):
    """Map explicit local state; stopping/disablement never means deletion."""
    if station.deleted_at or station.lifecycle_state == 'deleted':
        return 'deleted'
    if station.lifecycle_state in ('retired', 'pending_delete', 'delete_failed'):
        return 'retired'
    if station.lifecycle_state in ('ready', 'active', 'pending_create', 'create_failed'):
        return 'active'
    return None


def library_snapshot(station, online, listeners, now):
    # Shared, nondeleted library availability; not unique installation storage.
    count, artists, albums, duration, storage = db.session.query(
        func.count(Track.id), func.count(func.distinct(func.nullif(Track.artist, ''))),
        func.count(func.distinct(func.nullif(Track.album, ''))),
        func.coalesce(func.sum(Track.duration_ms), 0), func.coalesce(func.sum(Track.file_size_bytes), 0)
    ).filter(track_scope(station.id)).one()
    heartbeat = db.session.get(AutomationHeartbeat, 1)
    automation = station.automation
    scheduler = (False if automation and not automation.enabled else
                 True if automation and heartbeat and 0 <= now - seconds(heartbeat.seen_at) < 120 else None)
    return dict(current_listeners=listeners, songs_in_library=count, artists=artists, albums=albums,
                library_duration_seconds=int(duration // 1000), library_storage_bytes=int(storage),
                stream_running=online, scheduler_running=scheduler)


def station_state(station):
    state = db.session.get(CentralStationState, station.id)
    if state is None:
        state = CentralStationState(station_id=station.id)
        db.session.add(state)
        db.session.flush()
    return state


def observe_station(station):
    if channel_lifecycle(station) in ('deleted', 'retired'):
        return False, 0
    return observation(station.slug)


def sample(now):
    # Delivery is bounded to seven days; identities and stored history are retained.
    on_air = {}
    for station in Station.query.order_by(Station.id):
        state = station_state(station)
        previous = state.last_sample or {}
        if channel_lifecycle(station) in ('deleted', 'retired'):
            state.last_sample = {'at': max(now, previous.get('at', now)), 'listeners': None}
            on_air[station.id] = False
            continue
        online, listeners = observe_station(station)
        on_air[station.id] = online
        if listeners is None:
            state.last_sample = {'at': max(now, previous.get('at', now)), 'listeners': None}
        if previous and now <= previous['at']:
            continue
        snapshot = library_snapshot(station, online, listeners, now)

        def hourly(hour):
            row = db.session.get(CentralHourlyMetric, (station.id, hour))
            if row is None:
                row = CentralHourlyMetric(station_id=station.id, period_start=hour,
                    observed_seconds=0, listener_seconds=0, peak_listeners=0,
                    snapshot={}, coverage={'known': True}, sent=False)
                db.session.add(row)
                db.session.flush()
            return row

        # No interval is extrapolated through a failed observation or a long gap.
        if (listeners is not None and previous.get('listeners') is not None
                and 0 < now - previous['at'] <= 120):
            start = previous['at']
            while start < now:
                hour = int(start // 3600) * 3600
                end = min(now, hour + 3600)
                row = hourly(hour)
                covered_from = max(start, (row.coverage or {}).get('until', start))
                if not row.sent and end > covered_from:
                    row.observed_seconds += end - covered_from
                    row.listener_seconds += previous['listeners'] * (end - covered_from)
                    row.peak_listeners = max(row.peak_listeners, previous['listeners'], listeners)
                    row.snapshot = dict(snapshot)
                    row.coverage = {'known': True, 'until': end, 'peak_known': True}
                start = end
        # Even a wholly unknown hour has a truthful nullable snapshot and zero coverage.
        row = hourly(int(now // 3600) * 3600)
        if not row.sent:
            if listeners is not None:
                row.peak_listeners = max(row.peak_listeners, listeners)
            row.snapshot = dict(snapshot)
            row.coverage = dict(row.coverage or {}, known=True,
                                peak_known=listeners is not None or (row.coverage or {}).get('peak_known', False))
        state.last_sample = {'at': now, 'listeners': listeners}
    db.session.commit()
    return on_air


def wire_metric(row, extended=False):
    snapshot = row.snapshot or {}
    provenance = row.coverage or {}
    coverage = row.observed_seconds if provenance.get('known') or (row.observed_seconds or 0) > 0 else None
    result = {key: snapshot.get(key) for key in METRIC_KEYS}
    result.update(period_start=datetime.fromtimestamp(row.period_start, timezone.utc).strftime('%Y-%m-%dT%H:00:00Z'),
                  average_listeners=row.listener_seconds / coverage if coverage else snapshot.get('average_listeners') if coverage is None else None,
                  listener_hours=row.listener_seconds / 3600 if coverage else snapshot.get('listener_hours') if coverage is None else None,
                  peak_listeners=row.peak_listeners if coverage or provenance.get('peak_known') else snapshot.get('peak_listeners'))
    if extended:
        result['observed_seconds'] = coverage
    return result
