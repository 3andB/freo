"""Minute observations reduced to seven days of replaceable hourly aggregates."""
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


def machine_snapshot():
    if current_app.config['FREO_INSTALL_TYPE'] not in ('self-hosted', 'freo-live'):
        raise APIError('invalid_install_type')
    try:
        ram = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (ValueError, OSError):
        ram = None
    try:
        disk = shutil.disk_usage(current_app.config['FREO_MEDIA_ROOT'] or '/var/lib/freo')
        total, free = disk.total, disk.free
    except OSError:
        total = free = None
    return dict(freo_version=VERSION, install_type=current_app.config['FREO_INSTALL_TYPE'],
                os=platform.system()[:128], architecture=platform.machine()[:128], cpu_count=os.cpu_count(),
                ram_bytes=ram, disk_total_bytes=total, disk_free_bytes=free)


def seconds(value):
    return value.replace(tzinfo=timezone.utc).timestamp() if value and value.tzinfo is None else value.timestamp() if value else 0


def library_snapshot(station, online, listeners, now):
    # SQL returns aggregates only; names never enter a report or durable outbox.
    count, artists, albums, duration, storage = db.session.query(
        func.count(Track.id), func.count(func.distinct(func.nullif(Track.artist, ''))),
        func.count(func.distinct(func.nullif(Track.album, ''))),
        func.coalesce(func.sum(Track.duration_ms), 0), func.coalesce(func.sum(Track.file_size_bytes), 0)
    ).filter(track_scope(station.id)).one()
    heartbeat = db.session.get(AutomationHeartbeat, 1)
    automation = station.automation
    scheduler = bool(automation and automation.enabled and heartbeat and
                     0 <= now - seconds(heartbeat.seen_at) < 120)
    return dict(current_listeners=listeners, songs_in_library=count, artists=artists, albums=albums,
                library_duration_seconds=int(duration // 1000), library_storage_bytes=int(storage),
                stream_running=bool(online), scheduler_running=scheduler)


def station_state(station):
    state = db.session.get(CentralStationState, station.id)
    if state is None:
        state = CentralStationState(station_id=station.id)
        db.session.add(state)
        db.session.flush()
    return state


def observe_station(station):
    if station.deleted_at or station.lifecycle_state in ('pending_delete', 'delete_failed'):
        return False, 0
    return observation(station.slug)


def sample(now):
    CentralHourlyMetric.query.filter(CentralHourlyMetric.period_start < now - 7 * 86400).delete()
    on_air = {}
    for station in Station.query.order_by(Station.id):
        state = station_state(station)
        online, listeners = observe_station(station)
        if online is None or listeners is None:
            previous_at = (state.last_sample or {}).get('at', now)
            state.last_sample = {'at': max(now, previous_at), 'listeners': None}
            continue  # Unknown is never turned into a zero measurement.
        on_air[station.id] = bool(online)
        previous = state.last_sample
        if previous and now <= previous['at']:
            continue  # Do not count the same interval again after clock rollback.
        # Long downtime is an unobserved gap, not extrapolated listener time.
        if previous and previous['listeners'] is not None and 0 < now - previous['at'] <= 120:
            start = previous['at']
            while start < now:
                hour = int(start // 3600) * 3600
                end = min(now, hour + 3600)
                row = db.session.get(CentralHourlyMetric, (station.id, hour))
                if row is None:
                    row = CentralHourlyMetric(station_id=station.id, period_start=hour,
                        observed_seconds=0, listener_seconds=0, peak_listeners=0, snapshot={}, sent=False)
                    db.session.add(row)
                row.observed_seconds += end - start
                row.listener_seconds += previous['listeners'] * (end - start)
                row.peak_listeners = max(row.peak_listeners, previous['listeners'], listeners)
                # Latest health/library snapshot at the measurement boundary.
                row.snapshot = library_snapshot(station, online, listeners, now)
                row.sent = False
                start = end
        state.last_sample = {'at': now, 'listeners': listeners}
    db.session.commit()
    return on_air


def wire_metric(row):
    return dict(row.snapshot, period_start=datetime.fromtimestamp(row.period_start, timezone.utc).strftime('%Y-%m-%dT%H:00:00Z'),
                average_listeners=row.listener_seconds / row.observed_seconds,
                peak_listeners=row.peak_listeners, listener_hours=row.listener_seconds / 3600)
