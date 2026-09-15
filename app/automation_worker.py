"""Non-root, single-process refiller with per-station error isolation."""
import logging
import os
from pathlib import Path
import time
from datetime import datetime, timedelta, timezone
import math

from app import create_app
from app.extensions import db
from app.models import AutomationHeartbeat, AutomationState, EventBlockExecution, EventBlockItemExecution, LiveControlCommand, LiveQueueSnapshot, SelectionDecision, Station, TimedEventOccurrence
from app.services.automation import playback_started, select_next
from app.services.playout_queue import push_decision, queue_depth, queued_ids, queued_order, active_ids, socket_identity, request_decision_id, skip_current, interrupt_for_event
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
    live = queued_ids(slug) | active_ids(slug)
    from app.services.playout_queue import channel_queue
    try:
        live |= set(channel_queue(slug, 'B')) | set(channel_queue(slug, 'CART'))
    except (OSError, RuntimeError, ValueError):
        pass
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
        for row in rows:
            if row.status == 'failed' and row.selection_method == 'timed_event':
                occurrence = TimedEventOccurrence.query.filter_by(selection_decision_id=row.id).first()
                if occurrence and occurrence.state == 'QUEUED':
                    occurrence.state, occurrence.failure_reason = 'FAILED', row.reason
        db.session.commit()
    return changed


def process_block(station, reader, now=None):
    """Own a station queue while one durable block snapshot is active."""
    from app.services.event_blocks import active_execution, prepare_next
    now = now or datetime.now(timezone.utc)
    execution = active_execution(station.id)
    if execution is None:
        return False
    reader.collect(station.slug); reconcile_requests(station.slug)
    if execution.abort_requested:
        interrupt_for_event(station.slug)
        for item in execution.items:
            if item.state in ('PENDING','QUEUED'): item.state='SKIPPED'; item.failure_reason='operator_abort'
        execution.state='ABORTED'; execution.aborted_at=now; execution.failure_reason='operator_abort'; db.session.commit()
        return False
    # Translate request loss into item policy rather than allowing automation
    # to slip between block items.
    for item in execution.items:
        if item.state == 'QUEUED' and item.selection_decision and item.selection_decision.status == 'failed':
            item.state, item.failed_at, item.failure_reason = 'FAILED', now, item.selection_decision.reason
            if item.failure_policy == 'ABORT_BLOCK':
                execution.state, execution.failure_reason = 'FAILED', item.failure_reason
    if execution.state == 'FAILED':
        db.session.commit(); return False
    started = next((i for i in reversed(execution.items) if i.state == 'STARTED'), None)
    pending = next((i for i in execution.items if i.state == 'PENDING'), None)
    queued = next((i for i in execution.items if i.state == 'QUEUED'), None)
    if not started and not pending and not queued:
        execution.state='COMPLETED'; execution.completed_at=now; db.session.commit(); return False
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
    # Final item completion is inferred only after its known duration elapsed
    # and Liquidsoap no longer reports its exact request as active.
    if started and not pending and not queued and started == execution.items[-1]:
        duration_ms = (started.track or started.imaging_asset).duration_ms
        began = started.started_at.replace(tzinfo=started.started_at.tzinfo or timezone.utc)
        active = active_ids(station.slug)
        if now >= began + timedelta(milliseconds=max(0, duration_ms-500)) and started.selection_decision.liquidsoap_request_id not in active:
            started.state='COMPLETED'; started.completed_at=now; execution.state='COMPLETED'; execution.completed_at=now; db.session.commit(); return False
    return execution.state in ('PENDING','QUEUED','STARTED')


def process_manual(station, reader):
    slug = station.slug
    reader.collect(slug)
    reconcile_requests(slug)
    identity = socket_identity(slug)
    live = queued_ids(slug) | active_ids(slug)
    from app.services.playout_queue import channel_queue
    try:
        live |= set(channel_queue(slug, 'B')) | set(channel_queue(slug, 'CART'))
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
                if command.action == 'FADE':
                    from app.services.playout_queue import fade_current
                    fade_current(slug)
                else:
                    skip_current(slug)
                if current.block_item_execution and current.block_item_execution.state == 'STARTED':
                    current.block_item_execution.state = 'SKIPPED'
                    current.block_item_execution.failure_reason = 'operator_skip'
                command.status = 'sent'
            command.processed_at = datetime.now(timezone.utc)
            db.session.commit()
        except (OSError, RuntimeError, ValueError):
            db.session.rollback()
            failed = db.session.get(LiveControlCommand, command.id)
            failed.status = 'failed'
            failed.error_code = 'takeover_failed' if failed.action == 'TAKEOVER' else 'control_failed'
            failed.processed_at = datetime.now(timezone.utc)
            if failed.target_decision and failed.target_decision.status in ('selected', 'submitting'):
                failed.target_decision.status = 'failed'
                failed.target_decision.reason = 'manual_takeover_failed'
            db.session.commit()
            logger.exception('Live control failed station=%s command=%s', slug, command.id)
            break



def process_deck_command(station, command, identity):
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
    if operation == 'LOAD' and current and mixer.get(deck.lower()+'_playing') and not command.play_on_load:
        raise ValueError('Deck started playing before replacement was confirmed')
    if operation in ('LOAD','REPEAT'):
        target=command.target_decision
        if not target or target.status!='selected':
            raise ValueError('Prepared song is no longer available')
        # Persist intent before submitting. An uncertain socket result is terminal;
        # a browser retry cannot apply the same destructive operation twice.
        target.status='submitting';db.session.commit()
        deck_control(station.slug,deck,'clear' if operation=='LOAD' else 'future')
        target.liquidsoap_request_id=push_decision(target)
        target.socket_identity=identity;target.status='queued'
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


def process_timed_events(station, reader, now=None):
    """Prepare and execute durable occurrences; returns seconds to next event."""
    from app.services.timed_events import generate_occurrences, prepare_decision, upcoming
    now = now or datetime.now(timezone.utc)
    # A request can transiently disappear between queue prefetch and on-air
    # observation. The later authoritative on_track confirmation wins.
    confirmed = TimedEventOccurrence.query.join(TimedEventOccurrence.selection_decision).filter(
        TimedEventOccurrence.station_id == station.id,
        SelectionDecision.status == 'started', TimedEventOccurrence.state != 'STARTED').all()
    for occurrence in confirmed:
        occurrence.state = 'STARTED'
        occurrence.started_at = occurrence.selection_decision.started_at
        occurrence.failure_reason = None
    if confirmed:
        db.session.commit()
    generate_occurrences(station, now)
    rows = upcoming(station, now, 20)
    from app.services.event_blocks import active_execution
    if active_execution(station.id):
        future=[row for row in rows if row.state in ('PENDING','READY')]
        return min(((row.scheduled_for_utc.replace(tzinfo=row.scheduled_for_utc.tzinfo or timezone.utc)-now).total_seconds() for row in future),default=None)
    for candidate in rows:
        occurrence = TimedEventOccurrence.query.filter_by(id=candidate.id).with_for_update().first()
        if occurrence is None or occurrence.state not in ('PENDING','READY','QUEUED'):
            continue
        if occurrence.block_execution and occurrence.block_execution.state in ('PENDING','QUEUED','STARTED','COMPLETED'):
            continue
        event = occurrence.event
        deadline = occurrence.deadline_at_utc.replace(tzinfo=occurrence.deadline_at_utc.tzinfo or timezone.utc)
        scheduled = occurrence.scheduled_for_utc.replace(tzinfo=occurrence.scheduled_for_utc.tzinfo or timezone.utc)
        if now > deadline and occurrence.state != 'QUEUED':
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
            SelectionDecision.liquidsoap_request_id.in_(active)).first() if active else None
        if event.timing_mode == 'HARD':
            interruptible = current is None or (current.track_id is not None and current.admin_user_id is None and current.selection_method != 'timed_event' and event.interrupt_policy == 'MUSIC_ONLY')
            if not interruptible:
                continue
            interrupt_for_event(station.slug)
            logger.info('Timed event hard interruption station=%s occurrence=%s current_decision=%s', station.slug, occurrence.id, current.id if current else None)
            # Old queued automation was deliberately removed and is reconciled
            # on the next pass; the timed event is now the sole next request.
            if event.event_block:
                from app.services.event_blocks import create_execution
                create_execution(event.event_block, 'TIMED_EVENT', occurrence=occurrence)
                occurrence.state='READY'; db.session.commit()
            else:
                _queue_event(occurrence, station.slug, now)
            break
        elif queue_depth(station.slug) == 0:
            # SOFT and NON_INTERRUPTING never cut current content. SOFT may use
            # its early window; NON_INTERRUPTING waits until target time.
            duration_ms = current.track.duration_ms if current and current.track else current.imaging_asset.duration_ms if current and current.imaging_asset else 0
            started = current.started_at.replace(tzinfo=current.started_at.tzinfo or timezone.utc) if current and current.started_at else now
            expected_end = started + timedelta(milliseconds=duration_ms)
            if current and expected_end > deadline:
                continue
            if event.event_block:
                from app.services.event_blocks import create_execution
                create_execution(event.event_block, 'TIMED_EVENT', occurrence=occurrence)
                occurrence.state='READY'; db.session.commit()
            else:
                _queue_event(occurrence, station.slug, now)
            break
    future = [row for row in rows if row.state in ('PENDING','READY') and row.event.timing_mode != 'NON_INTERRUPTING']
    return min(((row.scheduled_for_utc.replace(tzinfo=row.scheduled_for_utc.tzinfo or timezone.utc)-now).total_seconds()
                for row in future), default=None)


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
            from app.services.playout_queue import sync_mixer
            try:
                prior_mixer = sync_mixer(state.station)
                if state.operator_mode == 'DJ_BOOTH' and prior_mixer['mode'] != 'DJ_BOOTH':
                    for execution in EventBlockExecution.query.filter_by(station_id=state.station_id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).all():
                        execution.state='ABORTED';execution.aborted_at=datetime.now(timezone.utc);execution.failure_reason='dj_control'
                        for item in execution.items:
                            if item.state in ('PENDING','QUEUED'):
                                item.state='SKIPPED';item.failure_reason='dj_control'
                    db.session.commit()
            except (OSError, RuntimeError, ValueError):
                pass
            process_manual(state.station, reader)
            if state.operator_mode == 'DJ_BOOTH':
                from app.services.timed_events import generate_occurrences
                now = datetime.now(timezone.utc)
                generate_occurrences(state.station, now)
                for occurrence in TimedEventOccurrence.query.filter_by(station_id=state.station_id).filter(TimedEventOccurrence.state.in_(('PENDING','READY')),TimedEventOccurrence.deadline_at_utc < now).all():
                    occurrence.state='MISSED';occurrence.failure_reason='dj_control'
                state.worker_heartbeat_at=now;state.observed_queue_depth=queue_depth(slug)
                db.session.commit();observe_queue(state.station);continue
            event_seconds = process_timed_events(state.station, reader)
            block_active = process_block(state.station, reader)
            if block_active:
                state.worker_heartbeat_at = datetime.now(timezone.utc)
                state.observed_queue_depth = queue_depth(slug)
                db.session.commit(); observe_queue(state.station); continue
            if not state.enabled or state.hold:
                state.worker_heartbeat_at = datetime.now(timezone.utc)
                state.observed_queue_depth = queue_depth(slug)
                db.session.commit()
                observe_queue(state.station)
                continue
            programming = resolve(state.station)
            from app.models import ClockState
            prior_clock = db.session.get(ClockState, state.station_id)
            next_key = programming.occurrence_key if programming.clock else f'default:{state.default_clock_id}' if state.default_clock_id else None
            if prior_clock and prior_clock.occurrence_key and prior_clock.occurrence_key != next_key:
                from app.services.playout_queue import clear_future
                try:
                    clear_future(slug)
                except (OSError, RuntimeError, ValueError):
                    pass
            has_clock = bool(programming.clock or usable_clock(state.default_clock, state.station_id))
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
            time.sleep(.25 if nearest is not None and -5 <= nearest <= 5 else 2)


if __name__ == '__main__':
    main()
