"""Installation overview built from local, worker-owned observations only."""
import time
from datetime import datetime, timezone

from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (AutomationHeartbeat, BroadcastIncident, CentralInstallation, CentralConnectionCheck, CentralStationState,
                        LiveQueueSnapshot, SelectionDecision, Station, StatsState, StorageSnapshot)
from app.services.admin_view import aware, format_station_time
from app.services.statistics import aggregate
from app.services.schedule import resolve
from app.services.central_api.releases import version_view


def fresh(at, now, seconds):
    if isinstance(at, datetime):
        at = aware(at).timestamp()
    return at is not None and 0 <= now - at <= seconds


def connection(stations, now):
    from app.services.central_api import metadata, digest
    from app.services.central_api.client import timestamp
    from app.services.central_api.connection_check import check_status
    row = db.session.get(CentralInstallation, 1)
    state = row.state if row else {}
    receipt = state.get('last_heartbeat', {})
    last = receipt.get('server_time')
    try:
        last_at = timestamp(last)
        recent = fresh(last_at, now, receipt.get('next_heartbeat_seconds', 3600) + 300)
    except (ValueError, TypeError):
        last_at = 0
        recent = False
    manual = db.session.get(CentralConnectionCheck, 1)
    failed_check = bool(manual and manual.status == 'failed' and (manual.finished_at or 0) >= last_at)
    connected = bool(recent and row and not row.last_error
                     and row.registration_state != 'credentials_rejected' and not failed_check)
    status = ('Connection to mother ship established' if connected else
              'Connection needs attention' if failed_check or row and row.last_error else
              'Connection stale' if last else 'Awaiting first connection')
    synced = {s.station_id: s.synced_digest for s in CentralStationState.query.all()}
    synced_count = sum(synced.get(s.id) == digest(metadata(s)) for s in stations)
    # This installation uses the offline perpetual license, not legacy remote
    # entitlements (older API responses can still advertise a two-station plan).
    from app.services.software_license import status as license_status
    from app.services.installation_settings import get_setting
    local_license = license_status()
    paid = local_license['edition'] == 'unlimited'
    local_limit = get_setting('FREO_MAX_STATIONS')
    version = version_view(state, now, manual=manual)
    return dict(status=status, connected=connected, last_contact=last or 'Not yet observed',
                **version,
                check=check_status(now),
                synced=f'{synced_count} / {len(stations)} stations up to date',
                plan='Unlimited · perpetual' if paid else 'Free · three stations per owner',
                entitlement_status=local_license.get('error') or 'Active · registration optional',
                channel_limit='Unlimited' if paid else min(local_limit or 3, 3),
                error=row.last_error if row else '')


def snapshot(stations, now=None):
    now = time.time() if now is None else now
    from app.services.broadcast_status import cached_status
    broadcasts = cached_status(stations, now)
    station_ids = [station.id for station in stations]
    stats = {s.scope: s.data for s in StatsState.query.filter(StatsState.scope.in_([0, *station_ids]))}
    live = {s.station_id: s for s in LiveQueueSnapshot.query.filter(LiveQueueSnapshot.station_id.in_(station_ids))}
    incidents = {}
    for incident in BroadcastIncident.query.filter(
            BroadcastIncident.scope.in_(station_ids), BroadcastIncident.ended_at.is_(None)):
        incidents.setdefault(incident.scope, []).append(incident.detail)
    # Indexed latest-row lookups avoid sorting the full airplay archive on every refresh.
    latest_id = db.select(SelectionDecision.id).where(
        SelectionDecision.station_id == Station.id, SelectionDecision.status == 'started').order_by(
        SelectionDecision.started_at.desc(), SelectionDecision.id.desc()).limit(1).correlate(Station).scalar_subquery()
    latest_ids = db.select(latest_id).select_from(Station).where(Station.id.in_(station_ids))
    latest = {s.station_id: s for s in SelectionDecision.query.filter(SelectionDecision.id.in_(latest_ids))
              .options(joinedload(SelectionDecision.track), joinedload(SelectionDecision.imaging_asset)).all()}
    current_ids = [s.current_decision_id for s in live.values() if s.current_decision_id]
    current = {s.id: s for s in SelectionDecision.query.filter(SelectionDecision.id.in_(current_ids))
               .options(joinedload(SelectionDecision.track), joinedload(SelectionDecision.imaging_asset)).all()}
    rows = {}
    for station in stations:
        sample = stats.get(station.id, {})
        observed = live.get(station.id)
        stats_fresh = fresh(sample.get('at'), now, 45)
        online = broadcasts[station.slug]['online']
        listeners = broadcasts[station.slug]['listeners']
        reliable = bool(observed and fresh(observed.observed_at, now, 10) and not observed.error_code)
        playing = current.get(observed.current_decision_id) if reliable else None
        if playing and (playing.station_id != station.id or playing.status != 'started'):
            playing = None
        song = playing or latest.get(station.id)
        automation = station.automation
        worker_ok = bool(automation and fresh(automation.worker_heartbeat_at, now, 15))
        worker = ('Disabled' if not automation or not automation.enabled else
                  'Held · healthy' if worker_ok and automation.hold else
                  'Healthy' if worker_ok else 'Unavailable')
        issues = []
        if station.lifecycle_error:
            issues.append(station.lifecycle_error)
        if station.enabled and station.desired_state == 'running':
            if online is not True:
                issues.append('Stream offline' if online is False else 'Stream observation unavailable')
            if automation and automation.enabled and not worker_ok:
                issues.append('Automation heartbeat unavailable')
        if observed and fresh(observed.observed_at, now, 10) and observed.error_code:
            issues.append(observed.error_code)
        issues.extend(detail if stats_fresh else 'Last reported: ' + detail
                      for detail in incidents.get(station.id, []) if detail not in issues)
        mode = 'DJ Booth' if automation and automation.operator_mode == 'DJ_BOOTH' else (
            station.scheduling.mode.title() if station.scheduling else 'Calendar')
        try:
            programming = resolve(station, datetime.fromtimestamp(now, timezone.utc))
            program = (programming.visual.get('label') if programming.visual else
                       programming.program.name if programming.program else
                       programming.clock.name if programming.clock else
                       automation.default_clock.name if automation and automation.default_clock else
                       automation.active_rotation.name if automation and automation.active_rotation else
                       'Nothing scheduled')
            next_transition = (format_station_time(programming.next_transition, station.timezone)
                               if programming.next_transition else 'No transition scheduled')
        except (ValueError, KeyError, TypeError):
            program, next_transition = 'Programming unavailable', 'Unknown'
            issues.append('Programming needs attention')
        title = song.track.title if song and song.track else song.imaging_asset.name if song and song.imaging_asset else 'No confirmed playback'
        artist = song.track.artist if song and song.track else ''
        rows[station.slug] = dict(status='On air' if online is True else 'Offline' if online is False else 'Unknown',
            listeners=listeners, worker=worker, mode=mode, program=program,
            next_transition=next_transition, title=title, artist=artist,
            playback_label='On air now' if playing else 'Last confirmed start',
            started_at=format_station_time(song.started_at, station.timezone) if song and song.started_at else None,
            queue=automation.observed_queue_depth if worker_ok else None,
            lifecycle=station.lifecycle_state.replace('_', ' '), issues=' · '.join(issues) or 'No reported issues',
            attention=bool(issues), desired=station.desired_state,
            updated_at=datetime.fromtimestamp(sample['at'], timezone.utc).isoformat() if sample.get('at') else None)
    total = aggregate(0, int(now) - 86400, int(now), int(now))['total']
    overall = stats.get(0, {})
    heartbeat = db.session.get(AutomationHeartbeat, 1)
    storage = StorageSnapshot.query.filter_by(scope=0).order_by(StorageSnapshot.at.desc()).first()
    return dict(stations=rows, connection=connection(stations, now), generated_at=now,
        summary=dict(stations=len(stations), on_air=sum(r['status'] == 'On air' for r in rows.values()),
            stopped=sum(s.desired_state == 'stopped' for s in stations),
            attention=sum(r['attention'] for r in rows.values()),
            listeners=overall.get('listeners') if fresh(overall.get('at'), now, 45) else None,
            listener_hours=round(total['listener_hours'], 1) if total['observed_seconds'] else None,
            peak=total['peak'] if total['observed_seconds'] else None,
            coverage=round(total['coverage'], 2),
            uptime=round(total['uptime'], 1) if total['uptime'] is not None else None,
            storage=storage.data.get('total') if storage else None,
            automation='Healthy' if heartbeat and fresh(heartbeat.seen_at, now, 15) else 'Unavailable',
            collector='Current' if fresh(overall.get('at'), now, 45) else 'Observation unavailable'))
