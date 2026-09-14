"""Non-root, single-process refiller with per-station error isolation."""
import logging
import os
from pathlib import Path
import time
from datetime import datetime, timezone
import math

from app import create_app
from app.extensions import db
from app.models import AutomationHeartbeat, AutomationState, SelectionDecision, Station
from app.services.automation import playback_started, select_next
from app.services.playout_queue import push_decision, queue_depth, queued_ids, active_ids, socket_identity
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


def tick(reader, target_depth=2):
    heartbeat()
    states = AutomationState.query.filter_by(enabled=True).all()
    for state in states:
        slug = state.station.slug
        if not state.station.enabled or state.station.desired_state != 'running':
            continue
        if time.monotonic() < reader.unavailable_until.get(slug, 0):
            continue
        try:
            programming = resolve(state.station)
            has_clock = bool(programming.clock or usable_clock(state.default_clock, state.station_id))
            has_rotation = bool(state.active_rotation and state.active_rotation.enabled and any(slot.enabled for slot in state.active_rotation.slots))
            if not has_clock and not has_rotation:
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
        except OSError as error:
            db.session.rollback()
            reader.unavailable_until[slug] = time.monotonic() + 5
            logger.warning('Playout temporarily unavailable for station=%s: %s', slug, type(error).__name__)
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
