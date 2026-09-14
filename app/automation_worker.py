"""Non-root, single-process refiller with per-station error isolation."""
import logging
import os
from pathlib import Path
import time
from datetime import datetime, timezone
import math

from app import create_app
from app.extensions import db
from app.models import AutomationHeartbeat, AutomationState, LiveControlCommand, LiveQueueSnapshot, SelectionDecision, Station
from app.services.automation import playback_started, select_next
from app.services.playout_queue import push_decision, queue_depth, queued_ids, queued_order, active_ids, socket_identity, request_decision_id, skip_current
from app.services.schedule import resolve, usable_clock

logger = logging.getLogger('freo.automation')
EVENT_ROOT = Path('/run/freo/playout')


class EventReader:
    def __init__(self):
        self.offsets = {}
        self.starved_until = {}
        self.unavailable_until = {}

    def collect(self, slug):
        path = EVENT_ROOT / slug / 'events.log'
        try:
            info = path.stat()
            identity = (info.st_dev, info.st_ino)
            prior_identity, offset = self.offsets.get(slug, (None, 0))
            if prior_identity != identity or offset > info.st_size:
                offset = 0
            with path.open('r') as stream:
                stream.seek(offset)
                lines = stream.readlines(65536)
                self.offsets[slug] = (identity, stream.tell())
        except FileNotFoundError:
            self.offsets.pop(slug, None)
            return 0
        count = 0
        for line in lines:
            fields = line.strip().split()
            if not fields or len(fields) > 2 or not fields[0].isascii() or not fields[0].isdecimal() or len(fields[0]) > 12:
                continue
            observed_at = None
            if len(fields) == 2:
                try:
                    stamp = float(fields[1])
                except ValueError:
                    continue
                if not math.isfinite(stamp) or abs(time.time() - stamp) > 7 * 86400:
                    continue
                observed_at = datetime.fromtimestamp(stamp, timezone.utc)
            count += bool(playback_started(int(fields[0]), slug, observed_at))
        return count


def heartbeat():
    row = db.session.get(AutomationHeartbeat, 1)
    if row is None:
        row = AutomationHeartbeat(id=1, seen_at=datetime.now(timezone.utc))
        db.session.add(row)
    else:
        row.seen_at = datetime.now(timezone.utc)
    db.session.commit()


def refill_station(slug, reader, target_depth=2):
    reader.collect(slug)
    reconcile_requests(slug)
    if time.monotonic() < reader.starved_until.get(slug, 0):
        return 0
    depth = queue_depth(slug)
    added = 0
    while depth < target_depth:
        decision = select_next(slug)
        if decision is None:
            reader.starved_until[slug] = time.monotonic() + 30
            break
        try:
            request_id = push_decision(decision)
            decision.status = 'queued'
            decision.liquidsoap_request_id = request_id
            decision.socket_identity = socket_identity(slug)
            db.session.commit()
            depth += 1
            added += 1
            logger.info('Queued station=%s rotation=%s slot=%s category=%s track=%s imaging=%s method=%s relaxation=%s candidates=%s',
                        slug, decision.rotation_id, decision.slot_id, decision.category_id,
                        decision.track_id, decision.imaging_asset_id, decision.selection_method,
                        decision.relaxation, decision.candidate_count)
        except Exception:
            decision.status = 'failed'
            decision.reason = 'queue_failed'
            db.session.commit()
            logger.exception('Queue request failed for station=%s decision=%s', slug, decision.id)
            break
    return added


def reconcile_requests(slug):
    identity = socket_identity(slug)
    live = queued_ids(slug) | active_ids(slug)
    rows = SelectionDecision.query.join(SelectionDecision.station).filter(
        SelectionDecision.status == 'queued', Station.slug == slug).all()
    changed = 0
    for row in rows:
        if row.socket_identity is None or row.liquidsoap_request_id is None:
            selected = row.selected_at.replace(tzinfo=row.selected_at.tzinfo or timezone.utc)
            if (datetime.now(timezone.utc) - selected).total_seconds() > 120:
                row.status = 'failed'
                row.reason = 'legacy_request_untracked'
                changed += 1
            continue
        if row.socket_identity != identity or row.liquidsoap_request_id not in live:
            row.status = 'failed'
            row.reason = 'playout_restarted' if row.socket_identity != identity else 'request_not_started'
            changed += 1
    if changed:
        db.session.commit()
    return changed


def process_manual(station, reader):
    slug = station.slug
    reader.collect(slug)
    reconcile_requests(slug)
    identity = socket_identity(slug)
    live = queued_ids(slug) | active_ids(slug)
    # Recover a push completed just before worker failure using Liquidsoap's
    # decision annotation. Metadata is parsed here and never returned to web.
    unresolved = SelectionDecision.query.filter_by(station_id=station.id, status='submitting').all()
    observed = {request_decision_id(slug, rid): rid for rid in live} if unresolved else {}
    for row in unresolved:
        if row.id in observed:
            row.liquidsoap_request_id = observed[row.id]
            row.socket_identity = identity
            row.status = 'queued'
        else:
            row.status = 'selected'
    db.session.commit()
    pending = SelectionDecision.query.filter_by(station_id=station.id, status='selected').filter(
        SelectionDecision.admin_user_id.isnot(None)).order_by(SelectionDecision.id).all()
    for row in pending:
        if queue_depth(slug) >= 20:
            break
        row.status = 'submitting'
        db.session.commit()
        try:
            request_id = push_decision(row)
            if row.status != 'started':
                row.status = 'queued'
            row.liquidsoap_request_id = request_id
            row.socket_identity = identity
            db.session.commit()
        except (OSError, RuntimeError, ValueError):
            row.status = 'failed'
            row.reason = 'manual_queue_failed'
            db.session.commit()
            logger.exception('Manual queue failed station=%s decision=%s', slug, row.id)
    commands = LiveControlCommand.query.filter_by(station_id=station.id, status='pending').order_by(LiveControlCommand.id).all()
    for command in commands:
        current = command.expected_decision
        try:
            if not current or current.socket_identity != identity or current.liquidsoap_request_id not in active_ids(slug):
                command.status, command.error_code = 'failed', 'current_changed'
            else:
                skip_current(slug)
                command.status = 'sent'
            command.processed_at = datetime.now(timezone.utc)
            db.session.commit()
        except (OSError, RuntimeError, ValueError):
            db.session.rollback()
            logger.exception('Skip failed station=%s command=%s', slug, command.id)
            break


def observe_queue(station, error_code=None):
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    if snapshot is None:
        snapshot = LiveQueueSnapshot(station_id=station.id, observed_at=datetime.now(timezone.utc), queued_decision_ids=[])
        db.session.add(snapshot)
    snapshot.observed_at = datetime.now(timezone.utc)
    snapshot.error_code = error_code
    if error_code:
        snapshot.current_decision_id = None
        snapshot.queued_decision_ids = []
        snapshot.unknown_count = 0
    else:
        identity = socket_identity(station.slug)
        active, ordered = active_ids(station.slug), queued_order(station.slug)
        rows = SelectionDecision.query.filter_by(station_id=station.id, socket_identity=identity).filter(
            SelectionDecision.liquidsoap_request_id.in_(list(active) + ordered)).all() if active or ordered else []
        by_request = {row.liquidsoap_request_id: row.id for row in rows}
        snapshot.current_decision_id = next((by_request[rid] for rid in active if rid in by_request), None)
        snapshot.queued_decision_ids = [by_request[rid] for rid in ordered if rid in by_request]
        snapshot.unknown_count = len([rid for rid in ordered if rid not in by_request])
    db.session.commit()


def tick(reader, target_depth=2):
    heartbeat()
    states = AutomationState.query.all()
    for state in states:
        slug = state.station.slug
        if not state.station.enabled or state.station.desired_state != 'running':
            continue
        if time.monotonic() < reader.unavailable_until.get(slug, 0):
            continue
        try:
            process_manual(state.station, reader)
            if not state.enabled or state.hold:
                state.worker_heartbeat_at = datetime.now(timezone.utc)
                state.observed_queue_depth = queue_depth(slug)
                db.session.commit()
                observe_queue(state.station)
                continue
            programming = resolve(state.station)
            has_clock = bool(programming.clock or usable_clock(state.default_clock, state.station_id))
            has_rotation = bool(state.active_rotation and state.active_rotation.enabled and any(slot.enabled for slot in state.active_rotation.slots))
            if not has_clock and not has_rotation:
                observe_queue(state.station)
                continue
            depth_limit = target_depth
            if programming.next_transition:
                remaining = (programming.next_transition - datetime.now(timezone.utc)).total_seconds()
                if 0 < remaining <= 20:
                    depth_limit = 0
            refill_station(slug, reader, depth_limit)
            state.worker_heartbeat_at = datetime.now(timezone.utc)
            state.observed_queue_depth = queue_depth(slug)
            db.session.commit()
            observe_queue(state.station)
        except OSError as error:
            db.session.rollback()
            reader.unavailable_until[slug] = time.monotonic() + 5
            logger.warning('Playout temporarily unavailable for station=%s: %s', slug, type(error).__name__)
            observe_queue(state.station, 'playout_unavailable')
        except Exception:
            db.session.rollback()
            logger.exception('Automation tick failed for station=%s', slug)


def main():
    logging.basicConfig(level=os.environ.get('LOG_LEVEL', 'INFO'))
    app = create_app()
    reader = EventReader()
    with app.app_context():
        while True:
            try:
                tick(reader)
            except Exception:
                db.session.rollback()
                logger.exception('Automation database or worker tick failed')
            time.sleep(2)


if __name__ == '__main__':
    main()
