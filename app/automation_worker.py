"""Non-root, single-process refiller with per-station error isolation."""
import logging
import os
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone
import math
from contextlib import contextmanager

from app import create_app
from app.extensions import db
from app.models import AuditEvent, AutomationHeartbeat, AutomationState, EventBlockExecution, EventBlockItemExecution, LiveControlCommand, LiveQueueSnapshot, SelectionDecision, Station, TimedEventOccurrence
from app.services.automation import playback_started, select_next
from app.services.playout_queue import push_decision, queue_depth, queued_ids, queued_order, active_ids, socket_identity, request_decision_id, skip_current, interrupt_for_event
from app.services.schedule import resolve, usable_clock

logger = logging.getLogger('freo.automation')
EVENT_ROOT = Path('/run/freo/playout')


@contextmanager
def worker_lease():
    """Only one refiller may hand audio to this installation's engines."""
    if db.engine.dialect.name != 'postgresql':
        yield
        return
    from sqlalchemy import text
    # Keep a dedicated connection: session-level ownership must survive the
    # many ORM commits between preparing, submitting and confirming a request.
    with db.engine.connect() as connection:
        acquired = connection.scalar(text('SELECT pg_try_advisory_lock(741902, 1)'))
        connection.commit()
        if not acquired:
            raise RuntimeError('Another automation worker owns this installation')
        try:
            yield connection
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(741902, 1)'))
            connection.commit()


class EventReader:
    def __init__(self):
        self.offsets = {}
        self.starved_until = {}
        self.unavailable_until = {}
        self.dj_has_played = set()
        self.dj_stopped_since = {}
        self.auto_return_until = {}
        self.programming_signatures = {}

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
            if len(fields) == 3 and fields[0] == 'END':
                try:
                    identifier, stamp = int(fields[1]), float(fields[2])
                    if identifier <= 0 or not math.isfinite(stamp) or abs(time.time() - stamp) > 7 * 86400:
                        continue
                    station = Station.query.filter_by(slug=slug).first()
                    if station:
                        from app.services.event_blocks import confirm_finished
                        confirm_finished(station, identifier, datetime.fromtimestamp(stamp, timezone.utc), socket_identity(slug))
                        from app.services.booth_cue import completed
                        completed(station, identifier, datetime.fromtimestamp(stamp, timezone.utc), socket_identity(slug))
                except (ValueError, OverflowError):
                    continue
                except Exception:
                    # Preserve EOF for retry after an unavailable DB/socket. Its
                    # durable playback row makes replaying earlier lines safe.
                    self.offsets[slug] = (identity, offset)
                    raise
                continue
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
            decision = db.session.get(SelectionDecision,int(fields[0]))
            if decision and decision.station.slug == slug and decision.status == 'submitting' and not decision.socket_identity:
                decision.socket_identity = socket_identity(slug)
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
            block = EventBlockExecution.query.join(EventBlockExecution.station).filter(
                Station.slug == slug, EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).first()
            if block is None:
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
    from app.services.event_blocks import reconcile_occurrences
    station = Station.query.filter_by(slug=slug).one()
    if reconcile_occurrences(station.id):
        db.session.commit()
    live = queued_ids(slug) | active_ids(slug)
    complete_inventory = True
    from app.services.playout_queue import channel_queue
    try:
        from app.services.playout_queue import _command
        live |= {int(v) for v in _command(slug,'freo_event.queue').split()}
        live |= set(channel_queue(slug, 'A')) | set(channel_queue(slug, 'B')) | set(channel_queue(slug, 'CART'))
    except (OSError, RuntimeError, ValueError):
        complete_inventory = False
    # A confirmed start remains airplay history, but an engine restart cannot
    # leave its occurrence or sequence permanently marked Playing.
    interrupted = SelectionDecision.query.join(SelectionDecision.station).outerjoin(
        TimedEventOccurrence,TimedEventOccurrence.selection_decision_id == SelectionDecision.id).outerjoin(
        EventBlockItemExecution,EventBlockItemExecution.selection_decision_id == SelectionDecision.id).filter(
        Station.slug == slug, SelectionDecision.status == 'started',
        SelectionDecision.socket_identity.isnot(None),
        db.or_(TimedEventOccurrence.state == 'STARTED',EventBlockItemExecution.state == 'STARTED'),
        SelectionDecision.selection_method.in_(('timed_event','event_block'))).all()
    now = datetime.now(timezone.utc)
    for decision in interrupted:
        reason = 'playout_restarted' if decision.socket_identity != identity else None
        audio = decision.track or decision.imaging_asset
        # A missing END is failure, not evidence of successful playback. Never
        # time out a paused request still retained by the engine, or infer
        # absence from an incomplete socket inventory.
        if not reason and complete_inventory and audio and decision.started_at and decision.liquidsoap_request_id not in live:
            began = decision.started_at.replace(tzinfo=decision.started_at.tzinfo or timezone.utc)
            if now >= began + timedelta(milliseconds=audio.duration_ms,seconds=120):
                reason = 'missing_end_confirmation'
        if not reason: continue
        item = decision.block_item_execution
        if item and item.state == 'STARTED':
            item.state='FAILED';item.failure_reason=reason
            item.failed_at=now
        occurrence = decision.timed_event_occurrence
        if occurrence and occurrence.state == 'STARTED':
            occurrence.state='FAILED';occurrence.failure_reason=reason
    if interrupted: db.session.commit()
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
            if row.reason != 'programming_refresh_pending':
                row.reason = 'playout_restarted' if row.socket_identity != identity else 'request_not_started'
            changed += 1
    if changed:
        for row in rows:
            if row.status == 'failed' and row.selection_method == 'timed_event':
                occurrence = TimedEventOccurrence.query.filter_by(selection_decision_id=row.id).first()
                if occurrence and occurrence.state == 'QUEUED':
                    occurrence.state, occurrence.failure_reason = 'FAILED', row.reason
        db.session.commit()
    return changed


def process_block(station, reader, now=None):
    """Own a station queue while one durable block snapshot is active."""
    from app.services.event_blocks import active_execution, prepare_next, finish_execution, cancel_future_items
    now = now or datetime.now(timezone.utc)
    execution = active_execution(station.id)
    if execution is None:
        return False
    reader.collect(station.slug); reconcile_requests(station.slug)
    if execution.abort_requested:
        cancel_future_items(execution,'operator_abort')
        if execution.timed_event_occurrence:
            execution.timed_event_occurrence.state='CANCELLED'
            execution.timed_event_occurrence.failure_reason='operator_abort'
        execution.state='ABORTED'; execution.aborted_at=now; execution.failure_reason='operator_abort'; db.session.commit()
        process_event_cancellations(station)
        return False
    for item in execution.items:
        if item.state == 'PENDING' and item.selection_decision and item.selection_decision.status == 'queued':
            item.state = 'QUEUED'
            item.queued_at = item.queued_at or now
            execution.state = 'QUEUED'
            if execution.timed_event_occurrence:
                execution.timed_event_occurrence.state = 'QUEUED'
                execution.timed_event_occurrence.queued_at = now
    db.session.commit()
    if execution.timed_event_occurrence and execution.state == 'PENDING' and not execution.abort_requested and all(item.state in ('PENDING','FAILED','SKIPPED') for item in execution.items):
        from app.services.event_blocks import submit_snapshot
        submit_snapshot(execution,now)
        return execution.state in ('PENDING','QUEUED','STARTED')
    # Translate request loss into item policy rather than allowing automation
    # to slip between block items.
    for item in execution.items:
        if item.state == 'QUEUED' and item.selection_decision and item.selection_decision.status == 'failed':
            item.state, item.failed_at, item.failure_reason = 'FAILED', now, item.selection_decision.reason
            if item.failure_policy == 'ABORT_BLOCK':
                execution.state, execution.failure_reason = 'FAILED', item.failure_reason
    if execution.state == 'FAILED':
        cancel_future_items(execution,execution.failure_reason or 'sequence_failed')
        if execution.timed_event_occurrence:
            execution.timed_event_occurrence.state='FAILED'
            execution.timed_event_occurrence.failure_reason=execution.failure_reason
        db.session.commit(); process_event_cancellations(station); return False
    started = next((i for i in reversed(execution.items) if i.state == 'STARTED'), None)
    pending = next((i for i in execution.items if i.state == 'PENDING'), None)
    queued = next((i for i in execution.items if i.state == 'QUEUED'), None)
    if not started and not pending and not queued:
        finish_execution(execution,now)
        db.session.commit(); return False
    if pending and not queued:
        item = prepare_next(execution, now)
        if item:
            decision = item.selection_decision; decision.status = 'submitting'; db.session.commit()
            try:
                request_id = push_decision(decision)
                decision.status = 'queued'; decision.liquidsoap_request_id = request_id; decision.socket_identity = socket_identity(station.slug)
                item.state = 'QUEUED'; item.queued_at = now
                from app.services.traffic import placement_queued
                placement_queued(item)
                if execution.state == 'PENDING': execution.state = 'QUEUED'
                if execution.timed_event_occurrence and execution.timed_event_occurrence.state == 'READY':
                    execution.timed_event_occurrence.state = 'QUEUED'; execution.timed_event_occurrence.queued_at = now
                db.session.commit()
            except (OSError, RuntimeError, ValueError):
                decision.status='failed'; decision.reason='block_queue_failed'; item.state='FAILED'; item.failed_at=now; item.failure_reason='queue_failed'
                if item.failure_policy == 'ABORT_BLOCK': execution.state='FAILED'; execution.failure_reason='queue_failed'
                db.session.commit()
    # Timed executions require END evidence. A missing END eventually fails
    # visibly; elapsed duration alone cannot prove a paused song completed.
    if started and not pending and not queued and all(i.state in ('COMPLETED','SKIPPED','FAILED') or i is started for i in execution.items):
        duration_ms = (started.track or started.imaging_asset).duration_ms
        began = started.started_at.replace(tzinfo=started.started_at.tzinfo or timezone.utc)
        active = active_ids(station.slug)
        if now >= began + timedelta(milliseconds=max(0, duration_ms-500),seconds=120 if execution.timed_event_occurrence else 0) and started.selection_decision.liquidsoap_request_id not in active:
            started.state='FAILED' if execution.timed_event_occurrence else 'COMPLETED'
            started.failure_reason='missing_end_confirmation' if execution.timed_event_occurrence else None
            started.completed_at=now
            finish_execution(execution,now)
            db.session.commit(); return False
    return execution.state in ('PENDING','QUEUED','STARTED')


def process_manual(station, reader):
    slug = station.slug
    reader.collect(slug)
    reconcile_requests(slug)
    identity = socket_identity(slug)
    live = queued_ids(slug) | active_ids(slug)
    from app.services.playout_queue import channel_queue
    try:
        from app.services.playout_queue import _command
        live |= {int(v) for v in _command(slug,'freo_event.queue').split()}
        live |= set(channel_queue(slug, 'A')) | set(channel_queue(slug, 'B')) | set(channel_queue(slug, 'CART'))
    except (OSError, RuntimeError, ValueError):
        pass
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
    takeover_targets=db.session.query(LiveControlCommand.target_decision_id).filter_by(station_id=station.id,status='pending').filter(LiveControlCommand.target_decision_id.isnot(None))
    pending = SelectionDecision.query.filter_by(station_id=station.id, status='selected').filter(
        SelectionDecision.admin_user_id.isnot(None),~SelectionDecision.id.in_(takeover_targets)).order_by(SelectionDecision.id).all()
    for row in pending:
        if station.automation.operator_mode == 'DJ_BOOTH' and row.playback_bus != 'CART':
            row.status='failed';row.reason='dj_decks_only';db.session.commit();continue
        if row.playback_bus in ('B','CART'):
            from app.services.playout_queue import channel_queue, mixer_state, prepare_cart
            try:
                observed = mixer_state(slug)
                key = 'cart_id' if row.playback_bus == 'CART' else 'b_id'
                if observed.get(key) or channel_queue(slug, row.playback_bus):
                    continue
                if row.playback_bus == 'CART':
                    prepare_cart(row)
            except (OSError, RuntimeError, ValueError):
                continue
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
            if command.action.startswith('DECK_'):
                process_deck_command(station,command,identity)
                continue
            idle_start = command.action == 'TAKEOVER' and command.expected_decision_id is None
            active = active_ids(slug)
            valid = (not active and not queued_ids(slug)) if idle_start else (current is not None and current.socket_identity == identity and current.liquidsoap_request_id in active)
            if command.action == 'TAKEOVER':
                from app.services.playout_queue import mixer_state
                try:
                    mixer = mixer_state(slug)
                    valid = (not mixer['a_id'] and not queued_ids(slug)) if idle_start else (current is not None and current.socket_identity == identity and mixer['a_id'] == current.id)
                except (OSError, RuntimeError, ValueError):
                    pass
            if command.action == 'SKIP' and station.automation.operator_mode != 'AUTO':
                valid = False
            if not valid:
                command.status, command.error_code = 'failed', 'current_changed'
                if command.target_decision and command.target_decision.status == 'selected':
                    command.target_decision.status = 'failed'
                    command.target_decision.reason = 'manual_takeover_stale'
            elif command.action=='TAKEOVER':
                target=command.target_decision
                if not target or target.status!='selected':command.status,command.error_code='failed','target_changed'
                else:
                    # Persist the in-flight target before the destructive skip.
                    # A failed submit is terminal so a retry cannot skip a second item.
                    target.status='submitting'
                    db.session.commit()
                    if not idle_start:
                        interrupt_for_event(slug)
                    target.liquidsoap_request_id=push_decision(target)
                    target.socket_identity=identity
                    target.status='queued'
                    command.status='sent'
                    station.automation.crossfader = 0.0
                    station.automation.deck_a_playing = True
            else:
                if command.action in ('FADE','SKIP'):
                    from app.services.playout_queue import fade_current
                    fade_current(slug,current.id)
                else:
                    skip_current(slug)
                if current.block_item_execution and current.block_item_execution.state == 'STARTED':
                    current.block_item_execution.state = 'SKIPPED'
                    current.block_item_execution.failure_reason = 'operator_skip'
                if current.timed_event_occurrence and current.timed_event_occurrence.state == 'STARTED':
                    current.timed_event_occurrence.state = 'FAILED'
                    current.timed_event_occurrence.failure_reason = 'operator_skip'
                command.status = 'sent'
            command.processed_at = datetime.now(timezone.utc)
            db.session.commit()
        except (OSError, RuntimeError, ValueError) as error:
            db.session.rollback()
            failed = db.session.get(LiveControlCommand, command.id)
            failed.status = 'failed'
            failed.error_code = 'takeover_failed' if failed.action == 'TAKEOVER' else 'control_failed'
            failed.processed_at = datetime.now(timezone.utc)
            if failed.target_decision and failed.target_decision.status in ('selected', 'submitting'):
                failed.target_decision.status = 'failed'
                failed.target_decision.reason = 'manual_takeover_failed'
            if failed.target_decision and failed.target_decision.selection_method == 'cue_auto':
                from app.services.booth_cue import disarm, CueChanged, locked
                if isinstance(error, CueChanged):
                    failed.error_code = 'cue_changed'
                    cue = locked(station)
                    cue.start_pending = cue.auto_enabled
                else:
                    disarm(station, 'AUTO_CUE paused · a pending start could not be confirmed. Review the deck and re-arm.')
            db.session.commit()
            if failed.error_code != 'cue_changed':
                logger.exception('Live control failed station=%s command=%s', slug, command.id)
            break



def process_deck_command(station, command, identity):
    from app.services.booth_cue import interrupt, locked, validate_automatic
    from app.models import CuePlayback
    cue = locked(station)
    automatic = command.target_decision is not None and command.target_decision.selection_method == 'cue_auto'
    if automatic:
        binding = db.session.get(CuePlayback, command.target_decision_id) if command.target_decision_id else None
        validate_automatic(station, cue, binding)
    from app.services.playout_queue import deck_control, mixer_state, channel_queue
    deck=command.deck
    if deck not in ('A','B') or station.automation.operator_mode != 'DJ_BOOTH':
        raise ValueError('DJ command is no longer applicable')
    mixer=mixer_state(station.slug)
    if mixer['mode'] != 'DJ_BOOTH':
        raise ValueError('Engine has not entered DJ mode')
    current=mixer.get(deck.lower()+'_id')
    prepared=[request_decision_id(station.slug,rid) for rid in channel_queue(station.slug,deck)]
    expected=current or next((value for value in prepared if value),None)
    if expected != command.expected_decision_id:
        raise ValueError('Deck changed before the command reached the engine')
    operation=command.action.removeprefix('DECK_')
    if operation in ('LOAD', 'CLEAR', 'FADE'):
        interrupt(station, current)
    if operation == 'PLAY' or (operation == 'LOAD' and command.play_on_load):
        interrupt(station, mixer.get(('b' if deck == 'A' else 'a')+'_id'))
    if operation == 'LOAD' and current and mixer.get(deck.lower()+'_playing') and not command.play_on_load:
        raise ValueError('Deck started playing before replacement was confirmed')
    if operation in ('LOAD','REPEAT'):
        target=command.target_decision
        if not target or target.status!='selected':
            raise ValueError('Prepared song is no longer available')
        # Persist intent before submitting. An uncertain socket result is terminal;
        # a browser retry cannot apply the same destructive operation twice.
        target.status='submitting';db.session.commit()
        # Hold the same lock as Cue edits through the socket operation. A New,
        # Load, removal or disable committed before this point cancels the take.
        cue = locked(station)
        if automatic:
            validate_automatic(station, cue, binding)
        deck_control(station.slug,deck,'clear' if operation=='LOAD' else 'future')
        target.liquidsoap_request_id=push_decision(target)
        target.socket_identity=identity;target.status='queued'
        if operation == 'REPEAT':
            # Transfer rotation only after the repeat was actually accepted.
            interrupt(station, current)
        if operation == 'LOAD' and command.play_on_load:
            deck_control(station.slug,deck,'take',command.fade_seconds)
    else:
        action = {'PLAY':'take','PAUSE':'pause','CLEAR':'clear','FADE':'fade'}[operation]
        if operation in ('PLAY','FADE'):
            deck_control(station.slug,deck,action,command.fade_seconds)
        else:
            deck_control(station.slug,deck,action)
    command.status='sent';command.processed_at=datetime.now(timezone.utc)
    db.session.commit()

def observe_queue(station, error_code=None):
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    if snapshot is None:
        snapshot = LiveQueueSnapshot(station_id=station.id, observed_at=datetime.now(timezone.utc), queued_decision_ids=[])
        db.session.add(snapshot)
    from app.services.broadcast_status import observation
    snapshot.broadcast_online,snapshot.listeners=observation(station.slug)
    snapshot.broadcast_observed_at=datetime.now(timezone.utc)
    snapshot.error_code = error_code
    if error_code:
        snapshot.program_rms = None
    else:
        snapshot.observed_at = datetime.now(timezone.utc)
        from app.services.playout_queue import program_rms, mixer_state
        try:
            snapshot.mixer = mixer_state(station.slug)
        except (OSError, RuntimeError, ValueError):
            snapshot.mixer = None
        try:
            snapshot.program_rms = program_rms(station.slug)
        except (OSError, RuntimeError, ValueError):
            snapshot.program_rms = None
        identity = socket_identity(station.slug)
        active, ordered = active_ids(station.slug), queued_order(station.slug)
        rows = SelectionDecision.query.filter_by(station_id=station.id, socket_identity=identity).filter(
            SelectionDecision.liquidsoap_request_id.in_(list(active) + ordered)).all() if active or ordered else []
        by_request = {row.liquidsoap_request_id: row.id for row in rows}
        # New engines expose final-output metadata, so prefetch and crossfade
        # request identities cannot make the displayed song flicker.
        from app.services.playout_queue import program_decision_id
        try:
            program_id = program_decision_id(station.slug)
            program = db.session.get(SelectionDecision, program_id) if program_id else None
            snapshot.current_decision_id = program.id if program and program.station_id == station.id and program.socket_identity == identity else None
        except (OSError, RuntimeError, ValueError):
            # Compatibility for station engines rendered before output metadata.
            candidates = [row for row in rows if row.liquidsoap_request_id in active]
            current = max(candidates, key=lambda row: (row.status == 'started', row.id), default=None)
            snapshot.current_decision_id = current.id if current else None
        snapshot.queued_decision_ids = [by_request[rid] for rid in ordered if rid in by_request]
        snapshot.unknown_count = len([rid for rid in set(ordered) | active if rid not in by_request])
    db.session.commit()


def _queue_event(occurrence, slug, now):
    decision = occurrence.selection_decision
    if decision.status == 'queued':
        occurrence.state = 'QUEUED'
        occurrence.queued_at = occurrence.queued_at or now
        db.session.commit()
        return
    decision.status = 'submitting'
    db.session.commit()
    request_id = push_decision(decision)
    decision.status = 'queued'
    decision.liquidsoap_request_id = request_id
    decision.socket_identity = socket_identity(slug)
    occurrence.state = 'QUEUED'
    occurrence.queued_at = now
    db.session.commit()
    logger.info('Timed event queued station=%s occurrence=%s event=%s scheduled=%s', slug, occurrence.id, occurrence.event.name, occurrence.scheduled_for_utc)


def automatic_future_only(station):
    """Permit insertion ahead of normal audio, preserving its relative order."""
    requests = queued_ids(station.slug)
    if not requests:
        return True
    rows = SelectionDecision.query.filter_by(station_id=station.id, socket_identity=socket_identity(station.slug)).filter(
        SelectionDecision.liquidsoap_request_id.in_(requests)).all()
    return {row.liquidsoap_request_id for row in rows} == requests and all(
        row.selection_method not in ('timed_event', 'event_block')
        and row.playback_bus in (None, 'A') for row in rows)


def process_event_cancellations(station):
    from app.models import EventQueueCancellation
    from app.services.playout_queue import _command
    jobs = EventQueueCancellation.query.filter_by(station_id=station.id,processed=False).all()
    if not jobs: return
    from app.services.music_delete import clear_deleted_playback
    deleted = [job for job in jobs if job.decision.track and job.decision.track.deleted_at]
    if deleted:
        clear_deleted_playback(station, deleted)
        db.session.commit()
    jobs = [job for job in jobs if job not in deleted]
    if not jobs: return
    token, _ = _command(station.slug,'freo_event.state').split('|')
    dj_queue = {int(v) for v in _command(station.slug,'freo_event.queue').split()}
    auto_queue = queued_ids(station.slug)
    uncertain = {job.decision_id for job in jobs if job.decision.liquidsoap_request_id is None}
    recovered = {request_decision_id(station.slug,rid):rid for rid in dj_queue | auto_queue} if uncertain else {}
    if token and any(job.decision.socket_identity == socket_identity(station.slug) and job.decision.liquidsoap_request_id in dj_queue for job in jobs):
        _command(station.slug,'freo_event.cancel '+token)
    for job in jobs:
        row = job.decision
        rid = recovered.get(row.id) if row.liquidsoap_request_id is None else row.liquidsoap_request_id if row.socket_identity == socket_identity(station.slug) else None
        if rid in auto_queue:
            _command(station.slug, f'freo_queue.remove {rid}')
        if rid in dj_queue:
            _command(station.slug, f'freo_event.remove {rid}')
        if row.status != 'started': row.status, row.reason = 'failed', 'event_cancelled'
        job.processed = True
    db.session.commit()


def process_dj_events(station, reader, now=None, allow_new=True):
    """Reserve a DJ boundary without changing mode, deck positions, or cue state."""
    from app.services.timed_events import generate_occurrences, upcoming, prepare_decision, aware, expire_due
    from app.services.playout_queue import event_bus
    from app.services.event_blocks import create_execution, create_playlist_execution
    from app.models import TimedEvent
    if not TimedEvent.query.filter_by(station_id=station.id,interrupt_dj=True).first() and not any((o.runtime or {}).get('dj') for o in TimedEventOccurrence.query.filter_by(station_id=station.id).filter(TimedEventOccurrence.state.in_(('READY','QUEUED','STARTED','CANCELLED','FAILED'))).filter(TimedEventOccurrence.boundary_reserved.is_(True))):
        return False
    now = now or datetime.now(timezone.utc)
    reader.collect(station.slug)
    generate_occurrences(station,now)
    expire_due(station,now,'dj_control')
    token, phase = event_bus(station.slug).split('|')
    if token:
        occurrence = db.session.get(TimedEventOccurrence,int(token))
        if not occurrence or occurrence.state in ('COMPLETED','FAILED','MISSED','CANCELLED'):
            event_bus(station.slug,'cancel' if occurrence and occurrence.state in ('CANCELLED','FAILED') else 'release',int(token))
            return phase == 'PLAYING' and bool(occurrence and occurrence.state in ('CANCELLED','FAILED'))
        process_block(station,reader,now)
        return True
    if not allow_new: return False
    from app.services.playout_queue import mixer_state
    if mixer_state(station.slug).get('cart_id'): return False
    for occurrence in upcoming(station,now,500):
        if aware(occurrence.scheduled_for_utc) > now: break
        if now > aware(occurrence.deadline_at_utc) and not occurrence.boundary_reserved:
            occurrence.state='MISSED';occurrence.failure_reason='dj_control';continue
        if not occurrence.event.interrupt_dj:
            occurrence.failure_reason='waiting_for_dj';continue
        if occurrence.event.recurrence_type != 'ONE_TIME' and occurrence.event.missed_policy == 'SKIP' and not occurrence.boundary_reserved and TimedEventOccurrence.query.filter_by(timed_event_id=occurrence.timed_event_id).filter(TimedEventOccurrence.scheduled_for_utc > occurrence.scheduled_for_utc,TimedEventOccurrence.scheduled_for_utc <= now,TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED','STARTED','COMPLETED'))).first():
            occurrence.state='MISSED';occurrence.failure_reason='superseded_repeat';continue
        occurrence.boundary_reserved=True
        occurrence.runtime={**(occurrence.runtime or {}),'dj':True}
        try:
            if occurrence.state == 'PENDING': prepare_decision(occurrence,now)
            if occurrence.event.playlist: create_playlist_execution(occurrence)
            elif occurrence.event.event_block: create_execution(occurrence.event.event_block,'TIMED_EVENT',occurrence=occurrence)
            else: _queue_event(occurrence,station.slug,now)
            if occurrence.block_execution: process_block(station,reader,now)
            if occurrence.state == 'FAILED':
                event_bus(station.slug,'release',occurrence.id);return False
            event_bus(station.slug,'arm',occurrence.id)
            db.session.commit();return True
        except (ValueError,OSError,RuntimeError):
            occurrence.state='FAILED';occurrence.failure_reason='dj_event_unavailable'
            db.session.commit()
            event_bus(station.slug,'release',occurrence.id)
            raise
    db.session.commit()
    return False


def process_timed_events(station, reader, now=None):
    """Prepare and execute durable occurrences; returns seconds to next event."""
    from app.services.timed_events import generate_occurrences, prepare_decision, upcoming, expire_due
    now = now or datetime.now(timezone.utc)
    # A request can transiently disappear between queue prefetch and on-air
    # observation. The later authoritative on_track confirmation wins.
    confirmed = TimedEventOccurrence.query.join(TimedEventOccurrence.selection_decision).filter(
        TimedEventOccurrence.station_id == station.id,
        SelectionDecision.status == 'started', TimedEventOccurrence.state.in_(('PENDING','READY','QUEUED'))).all()
    for occurrence in confirmed:
        occurrence.state = 'STARTED'
        occurrence.started_at = occurrence.selection_decision.started_at
        occurrence.failure_reason = None
    if confirmed:
        db.session.commit()
    generate_occurrences(station, now)
    expire_due(station,now)
    process_event_cancellations(station)
    rows = upcoming(station, now, 500)
    from app.services.event_blocks import active_execution
    active_event = TimedEventOccurrence.query.filter_by(station_id=station.id,state='STARTED').filter(TimedEventOccurrence.selection_decision_id.isnot(None)).first()
    if active_event and (not active_event.selection_decision or active_event.selection_decision.liquidsoap_request_id not in active_ids(station.slug)):
        active_event = None
    if active_execution(station.id) or active_event:
        future=[row for row in rows if row.state in ('PENDING','READY')]
        return min(((row.scheduled_for_utc.replace(tzinfo=row.scheduled_for_utc.tzinfo or timezone.utc)-now).total_seconds() for row in future),default=None)
    for candidate in rows:
        occurrence = TimedEventOccurrence.query.filter_by(id=candidate.id).with_for_update().first()
        if occurrence is None or occurrence.state not in ('PENDING','READY','QUEUED'):
            continue
        if occurrence.block_execution and occurrence.block_execution.state in ('PENDING','QUEUED','STARTED','COMPLETED'):
            continue
        if occurrence.state in ('PENDING', 'READY') and occurrence.selection_decision and occurrence.selection_decision.status == 'queued':
            occurrence.state = 'QUEUED'
            occurrence.queued_at = occurrence.queued_at or now
            db.session.commit()
        event = occurrence.event
        if event.recurrence_type != 'ONE_TIME' and event.missed_policy == 'SKIP' and not occurrence.boundary_reserved and any(other.timed_event_id == event.id and other.scheduled_for_utc > occurrence.scheduled_for_utc and other.scheduled_for_utc.replace(tzinfo=other.scheduled_for_utc.tzinfo or timezone.utc) <= now for other in rows):
            occurrence.state='MISSED';occurrence.failure_reason='superseded_repeat';db.session.commit();continue
        deadline = occurrence.deadline_at_utc.replace(tzinfo=occurrence.deadline_at_utc.tzinfo or timezone.utc)
        scheduled = occurrence.scheduled_for_utc.replace(tzinfo=occurrence.scheduled_for_utc.tzinfo or timezone.utc)
        if now > deadline and occurrence.state != 'QUEUED' and not occurrence.boundary_reserved:
            if occurrence.state != 'STARTED':
                occurrence.state = 'MISSED'
                occurrence.missed_at = now
                occurrence.failure_reason = 'deadline_exceeded'
                if occurrence.selection_decision and occurrence.selection_decision.status in ('selected','submitting'):
                    occurrence.selection_decision.status = 'failed'
                    occurrence.selection_decision.reason = 'timed_event_missed'
                db.session.commit()
                logger.warning('Timed event missed station=%s occurrence=%s event=%s', station.slug, occurrence.id, event.name)
            continue
        if occurrence.state == 'PENDING' and (scheduled-now).total_seconds() <= 60:
            try:
                prepare_decision(occurrence, now)
            except (OSError, ValueError):
                occurrence.state, occurrence.failure_reason = 'FAILED', 'content_unavailable'
                db.session.commit()
                logger.warning('Timed event content unavailable station=%s occurrence=%s', station.slug, occurrence.id)
                continue
        if occurrence.state != 'READY':
            continue
        # One event owns the real queue at a time. Same-time collisions were
        # ordered by priority; lower-priority events wait for policy handling.
        if TimedEventOccurrence.query.filter_by(station_id=station.id, state='QUEUED').filter(TimedEventOccurrence.id != occurrence.id).first():
            continue
        due = now >= scheduled if event.timing_mode != 'SOFT' else now >= occurrence.eligible_at_utc.replace(tzinfo=occurrence.eligible_at_utc.tzinfo or timezone.utc)
        if not due:
            continue
        active = active_ids(station.slug)
        current = SelectionDecision.query.filter_by(station_id=station.id, socket_identity=socket_identity(station.slug)).filter(
            SelectionDecision.liquidsoap_request_id.in_(active), SelectionDecision.status == 'started').order_by(SelectionDecision.started_at.desc()).first() if active else None
        if event.timing_mode == 'HARD':
            interruptible = (current is None and not active) or (current is not None and current.track_id is not None and current.admin_user_id is None and current.selection_method != 'timed_event' and event.interrupt_policy == 'MUSIC_ONLY')
            if not interruptible:
                continue
            interrupt_for_event(station.slug)
            logger.info('Timed event hard interruption station=%s occurrence=%s current_decision=%s', station.slug, occurrence.id, current.id if current else None)
            # Old queued automation was deliberately removed and is reconciled
            # on the next pass; the timed event is now the sole next request.
            if event.event_block or event.playlist:
                from app.services.event_blocks import create_execution, create_playlist_execution
                if event.playlist: create_playlist_execution(occurrence)
                else: create_execution(event.event_block, 'TIMED_EVENT', occurrence=occurrence)
                occurrence.state='READY'; db.session.commit()
            else:
                _queue_event(occurrence, station.slug, now)
            break
        elif queue_depth(station.slug) == 0 or (event.timing_mode == 'SOFT' and automatic_future_only(station)):
            # SOFT and NON_INTERRUPTING never cut current content. SOFT may use
            # its early window; NON_INTERRUPTING waits until target time.
            duration_ms = current.track.duration_ms if current and current.track else current.imaging_asset.duration_ms if current and current.imaging_asset else 0
            started = current.started_at.replace(tzinfo=current.started_at.tzinfo or timezone.utc) if current and current.started_at else now
            expected_end = started + timedelta(milliseconds=duration_ms)
            # Reserve the next boundary even for songs longer than the late allowance.
            occurrence.boundary_reserved = True
            if event.event_block or event.playlist:
                from app.services.event_blocks import create_execution, create_playlist_execution
                if event.playlist: create_playlist_execution(occurrence)
                else: create_execution(event.event_block, 'TIMED_EVENT', occurrence=occurrence)
                occurrence.state='READY'; db.session.commit()
            else:
                _queue_event(occurrence, station.slug, now)
            break
    future = [row for row in rows if row.state in ('PENDING','READY')]
    return min(((row.scheduled_for_utc.replace(tzinfo=row.scheduled_for_utc.tzinfo or timezone.utc)-now).total_seconds()
                for row in future), default=None)


def return_to_auto_if_stopped(station, reader, mixer, now=None):
    """Return after aired DJ music stops, never from a missing engine response."""
    slug=station.slug
    if station.automation.operator_mode != 'DJ_BOOTH' or mixer['mode'] != 'DJ_BOOTH':
        reader.dj_has_played.discard(slug);reader.dj_stopped_since.pop(slug,None)
        return False
    if mixer.get('auto_standby'):
        reader.dj_has_played.discard(slug);reader.dj_stopped_since.pop(slug,None)
        return False
    audible=any(mixer.get(deck+'_playing') and mixer.get(deck+'_id') and
        mixer.get('transition',{}).get(deck+'_gain',1)>0 for deck in ('a','b'))
    if audible:
        if slug not in reader.dj_has_played:
            from app.services.admin_media import audit
            audit('live_dj_audio_started',station_id=station.id,target_type='station',target_id=slug,
                  summary='DJ audio observed; automatic return armed')
            db.session.commit()
        reader.dj_has_played.add(slug);reader.dj_stopped_since.pop(slug,None)
        return False
    if slug not in reader.dj_has_played:
        # Keep stop detection armed across worker restarts, scoped to this DJ session.
        entered=AuditEvent.query.filter_by(station_id=station.id,action='live_mode_changed').order_by(AuditEvent.id.desc()).first()
        armed=AuditEvent.query.filter_by(station_id=station.id,action='live_dj_audio_started').order_by(AuditEvent.id.desc()).first()
        played=bool(entered and SelectionDecision.query.filter(SelectionDecision.station_id==station.id,
            SelectionDecision.started_at>=entered.created_at,SelectionDecision.playback_bus.in_(('A','B'))).first())
        if not ((armed and (not entered or armed.id>entered.id)) or played):
            return False
        reader.dj_has_played.add(slug)
    if mixer.get('cart_id') or LiveControlCommand.query.filter_by(station_id=station.id,status='pending').first():
        reader.dj_stopped_since.pop(slug,None)
        return False
    now=time.monotonic() if now is None else now
    since=reader.dj_stopped_since.setdefault(slug,now)
    if now-since < 2:
        return False
    from app.services.live_assist import return_to_schedule
    return_to_schedule(station, reason='DJ music stopped. Returning to the schedule in Auto mode.')
    reader.dj_has_played.discard(slug);reader.dj_stopped_since.pop(slug,None)
    return True


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
            from app.services.schedule_switch import process_transition
            if process_transition(state.station, reader):
                observe_queue(state.station)
                continue
            from app.services.playout_queue import sync_mixer
            mic_active = False
            try:
                from app.services.live_mic import sync_live_mic
                mic_active = sync_live_mic(state.station)
                prior_mixer = sync_mixer(state.station)
                if state.operator_mode == 'AUTO' and prior_mixer['mode'] == 'DJ_BOOTH':
                    reader.auto_return_until[slug]=time.monotonic()+4
                if state.operator_mode != 'DJ_BOOTH':
                    from app.services.booth_cue import disarm
                    disarm(state.station, 'AUTO_CUE is off · station AUTO is active.')
                    reader.dj_has_played.discard(slug);reader.dj_stopped_since.pop(slug,None)
            except (OSError, RuntimeError, ValueError):
                pass
            if mic_active:
                from app.services.booth_cue import disarm
                disarm(state.station, 'AUTO_CUE is off · live microphone is active.')
                db.session.commit()
            process_manual(state.station, reader)
            process_event_cancellations(state.station)
            if not mic_active and state.operator_mode == 'AUTO' and process_dj_events(state.station,reader,allow_new=False):
                state.worker_heartbeat_at=datetime.now(timezone.utc);db.session.commit();observe_queue(state.station);continue
            if mic_active:
                state.worker_heartbeat_at = datetime.now(timezone.utc)
                db.session.commit()
                observe_queue(state.station)
                continue
            standby=False
            if state.operator_mode == 'DJ_BOOTH':
                from app.services.playout_queue import mixer_state
                from app.services.booth_cue import advance
                observed_mixer = mixer_state(slug)
                standby=observed_mixer.get('auto_standby',False)
                if process_dj_events(state.station,reader):
                    state.worker_heartbeat_at=datetime.now(timezone.utc);db.session.commit();observe_queue(state.station);continue
                cue_active = advance(state.station, observed_mixer, reader)
                if not cue_active and return_to_auto_if_stopped(state.station,reader,mixer_state(slug)):
                    sync_mixer(state.station)
                    reader.auto_return_until[slug]=time.monotonic()+4
            if state.operator_mode == 'DJ_BOOTH' and not standby:
                for execution in EventBlockExecution.query.filter_by(station_id=state.station_id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).all():
                    execution.state='ABORTED';execution.aborted_at=datetime.now(timezone.utc);execution.failure_reason='dj_control'
                    for item in execution.items:
                        if item.state in ('PENDING','QUEUED'):
                            item.state='SKIPPED';item.failure_reason='dj_control'
                db.session.commit()
                from app.services.timed_events import generate_occurrences
                now = datetime.now(timezone.utc)
                generate_occurrences(state.station, now)
                for occurrence in TimedEventOccurrence.query.filter_by(station_id=state.station_id).filter(TimedEventOccurrence.state.in_(('PENDING','READY')),TimedEventOccurrence.scheduled_for_utc <= now).all():
                    if occurrence.deadline_at_utc.replace(tzinfo=occurrence.deadline_at_utc.tzinfo or timezone.utc) < now:
                        occurrence.state='MISSED';occurrence.failure_reason='dj_control'
                    else:occurrence.failure_reason='waiting_for_dj'
                state.worker_heartbeat_at=now;state.observed_queue_depth=queue_depth(slug)
                db.session.commit();observe_queue(state.station);continue
            from app.services.programming_refresh import signature,refresh
            current_signature=signature(state.station)
            if reader.programming_signatures.get(slug)!=current_signature:
                reader.starved_until.pop(slug,None)
            refresh(state.station,reader,current_signature)
            reader.programming_signatures[slug]=current_signature
            # Hard timed events must not skip the outgoing DJ source mid-fade.
            returning=time.monotonic()<reader.auto_return_until.get(slug,0)
            event_seconds = None if returning else process_timed_events(state.station, reader)
            block_active = False if returning else process_block(state.station, reader)
            if block_active:
                state.worker_heartbeat_at = datetime.now(timezone.utc)
                state.observed_queue_depth = queue_depth(slug)
                db.session.commit(); observe_queue(state.station); continue
            if not state.enabled or (state.hold and not standby):
                state.worker_heartbeat_at = datetime.now(timezone.utc)
                state.observed_queue_depth = queue_depth(slug)
                db.session.commit()
                observe_queue(state.station)
                continue
            programming = resolve(state.station)
            has_clock = bool(programming.visual is not None or programming.clock or usable_clock(state.default_clock, state.station_id))
            has_rotation = bool(state.active_rotation and state.active_rotation.enabled and any(slot.enabled for slot in state.active_rotation.slots))
            if not has_clock and not has_rotation:
                observe_queue(state.station)
                continue
            depth_limit = target_depth
            if event_seconds is not None and 0 < event_seconds <= 20:
                depth_limit = 0
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
            reader.dj_stopped_since.pop(slug,None)
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
    with app.app_context(), worker_lease() as lease:
        while True:
            if lease is not None:
                # A lost lease connection stops this process before it can
                # reconnect the ORM and compete with a replacement worker.
                from sqlalchemy import text
                lease.scalar(text('SELECT 1'))
                lease.commit()
            try:
                tick(reader)
            except Exception:
                db.session.rollback()
                logger.exception('Automation database or worker tick failed')
            # Two-second normal cadence; the final event window adapts to 250ms
            # without a persistent busy loop.
            nearest = None
            try:
                from app.models import TimedEventOccurrence
                due = TimedEventOccurrence.query.filter(TimedEventOccurrence.state.in_(('PENDING','READY'))).order_by(TimedEventOccurrence.scheduled_for_utc).first()
                if due:
                    nearest = (due.scheduled_for_utc.replace(tzinfo=due.scheduled_for_utc.tzinfo or timezone.utc)-datetime.now(timezone.utc)).total_seconds()
            except Exception:
                db.session.rollback()
            dj_active = db.session.query(AutomationState.station_id).join(Station).filter(AutomationState.operator_mode=='DJ_BOOTH',Station.enabled.is_(True),Station.desired_state=='running').first() is not None
            time.sleep(.25 if dj_active or (nearest is not None and -5 <= nearest <= 5) else 2)


if __name__ == '__main__':
    main()
