"""Station-scoped operator intent. Only the automation worker touches playout sockets."""
import uuid
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import (AutomationState, EventBlock, EventBlockExecution, ImagingAsset, LiveControlCommand, LiveQueueSnapshot,
                        SelectionDecision, Station, Track)
from app.services.admin_media import audit
from app.services.media_storage import LocalMediaStorage

MAX_LIVE_QUEUE_ITEMS = 20


def _nonce(value):
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError('Invalid operation token') from error


def set_hold(station, user, held):
    state = db.session.get(AutomationState, station.id)
    if state is None or not state.enabled or not station.enabled or station.desired_state != 'running':
        raise ValueError('Station automation is unavailable')
    state.hold = held
    audit('automation_held' if held else 'automation_resumed', user_id=user.id,
          station_id=station.id, target_type='station', target_id=station.slug,
          summary='Automation refill held' if held else 'Automation refill resumed')
    db.session.commit()


def queue_playable(station, user, kind, identifier, nonce):
    nonce = _nonce(nonce)
    # Serialize concurrent browser queue requests for this station. PostgreSQL
    # row locking keeps the 20-item cap meaningful across multiple operators.
    db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
    existing = SelectionDecision.query.filter_by(idempotency_key=nonce).first()
    if existing:
        if existing.station_id == station.id and existing.admin_user_id == user.id and existing.selection_method == f'manual_{kind}' and (existing.track and existing.track.uuid == identifier or existing.imaging_asset and existing.imaging_asset.uuid == identifier):
            return existing
        raise ValueError('Operation token was already used')
    if not station.enabled or station.desired_state != 'running':
        raise ValueError('Station is not running')
    if kind == 'track':
        playable = Track.query.filter_by(station_id=station.id, uuid=identifier).first()
    elif kind == 'imaging':
        playable = ImagingAsset.query.filter_by(station_id=station.id, uuid=identifier).first()
    else:
        raise ValueError('Invalid playable type')
    if playable is None or not playable.enabled or playable.ingest_status != 'accepted' or playable.decommissioned_at:
        raise ValueError('Playable is unavailable for this station')
    storage = LocalMediaStorage()
    try:
        if kind == 'track':
            storage.regular_file(station.slug, playable.storage_key)
        else:
            storage.imaging_file(station.slug, playable.storage_key)
    except (OSError, ValueError) as error:
        raise ValueError('Approved audio is unavailable') from error
    # This cap includes worker-submitted and browser-pending requests. The worker
    # checks actual Liquidsoap depth again before pushing.
    pending = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.status.in_(('selected', 'submitting', 'queued'))).count()
    if pending >= MAX_LIVE_QUEUE_ITEMS:
        raise ValueError('Live queue is full')
    row = SelectionDecision(station_id=station.id, track_id=playable.id if kind == 'track' else None,
        imaging_asset_id=playable.id if kind == 'imaging' else None,
        selection_method=f'manual_{kind}', admin_user_id=user.id,
        idempotency_key=nonce, status='selected', reason='operator_queue_end')
    db.session.add(row)
    db.session.flush()
    audit('manual_track_queued' if kind == 'track' else 'manual_imaging_queued',
          user_id=user.id, station_id=station.id, target_type=kind,
          target_id=identifier, summary='Operator requested Queue End')
    db.session.commit()
    return row


def request_skip(station, user, expected_decision_id, nonce):
    nonce = _nonce(nonce)
    existing = LiveControlCommand.query.filter_by(idempotency_key=nonce).first()
    if existing:
        if existing.station_id == station.id and existing.admin_user_id == user.id and existing.expected_decision_id == expected_decision_id:
            return existing
        raise ValueError('Operation token was already used')
    current = SelectionDecision.query.filter_by(id=expected_decision_id, station_id=station.id, status='started').first()
    if current is None or not station.enabled or station.desired_state != 'running':
        raise ValueError('Current item changed; refresh before skipping')
    row = LiveControlCommand(station_id=station.id, admin_user_id=user.id,
        idempotency_key=nonce, expected_decision_id=current.id, status='pending')
    db.session.add(row)
    audit('manual_skip_requested', user_id=user.id, station_id=station.id,
          target_type='decision', target_id=str(current.id), summary='Operator requested skip of current item')
    db.session.commit()
    return row

def queue_block(station, user, identifier):
    from app.services.event_blocks import block_for, create_execution, active_execution
    if active_execution(station.id): raise ValueError('A block is already active')
    try: block=block_for(station.slug,identifier)
    except ValueError as error: raise ValueError('Block is unavailable for this station') from error
    execution=create_execution(block,'MANUAL',admin_user_id=user.id)
    audit('event_block_queued',user_id=user.id,station_id=station.id,target_type='event_block',target_id=block.slug,summary='Operator queued ordered block')
    db.session.commit(); return execution

def request_abort_block(station, user, execution_id):
    execution=EventBlockExecution.query.filter_by(id=execution_id,station_id=station.id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).first()
    if execution is None: raise ValueError('Active block changed; refresh first')
    execution.abort_requested=True
    audit('event_block_abort_requested',user_id=user.id,station_id=station.id,target_type='event_block_execution',target_id=str(execution.id),summary='Operator requested block abort')
    db.session.commit(); return execution


def safe_item(row):
    source = 'BLOCK' if row.selection_method == 'event_block' else 'EVENT' if row.selection_method == 'timed_event' else 'MANUAL' if row.admin_user_id else 'AUTO'
    if row.track:
        return dict(decision_id=row.id, kind='track', title=row.track.title,
                    artist=row.track.artist, source=source,
                    started_at=row.started_at.isoformat() if row.started_at else None,
                    duration_ms=row.track.duration_ms)
    if row.imaging_asset:
        asset = row.imaging_asset
        return dict(decision_id=row.id, kind='imaging', title=asset.name,
                    artist=asset.asset_type.replace('_', ' ').title(), cart_code=asset.cart_code,
                    source=source,
                    started_at=row.started_at.isoformat() if row.started_at else None,
                    duration_ms=asset.duration_ms)
    return dict(decision_id=row.id, kind='unavailable', title='Unavailable item', artist='', source='UNKNOWN')


def status(station):
    from app.services.schedule import resolve
    state = station.automation
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    fresh = bool(snapshot and (datetime.now(timezone.utc) - snapshot.observed_at.replace(
        tzinfo=snapshot.observed_at.tzinfo or timezone.utc)).total_seconds() < 10)
    live_error = snapshot.error_code if fresh else 'Worker observation unavailable'
    ids = ([snapshot.current_decision_id] if fresh and snapshot.current_decision_id else []) + (snapshot.queued_decision_ids if fresh else [])
    rows = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.id.in_(ids)).all() if ids else []
    by_id = {row.id: row for row in rows}
    current = safe_item(by_id[snapshot.current_decision_id]) if fresh and snapshot.current_decision_id in by_id else None
    queue = [safe_item(by_id[identifier]) for identifier in snapshot.queued_decision_ids if identifier in by_id] if fresh else []
    unknown = snapshot.unknown_count if fresh else 0
    recent = SelectionDecision.query.filter_by(station_id=station.id, status='started').order_by(
        SelectionDecision.started_at.desc(), SelectionDecision.id.desc()).limit(10).all()
    programming = resolve(station)
    from app.services.timed_events import upcoming
    events = upcoming(station, limit=1)
    next_event = events[0] if events else None
    overrun_seconds = None
    if next_event and current and current.get('started_at') and current.get('duration_ms'):
        estimated_end = datetime.fromisoformat(current['started_at']) + timedelta(milliseconds=current['duration_ms'])
        scheduled = next_event.scheduled_for_utc.replace(tzinfo=next_event.scheduled_for_utc.tzinfo or timezone.utc)
        overrun_seconds = round((estimated_end - scheduled).total_seconds())
    active_block=EventBlockExecution.query.filter_by(station_id=station.id).filter(EventBlockExecution.state.in_(('PENDING','QUEUED','STARTED'))).first()
    return dict(station=station.slug, automation='HELD' if state and state.hold else 'RUNNING' if state and state.enabled else 'DISABLED',
        current=current, queue=queue, unknown_queue_items=unknown,
        fallback='Possible' if not current and not live_error and station.desired_state == 'running' else 'Not observed',
        playout_error=live_error, recent=[safe_item(row) for row in recent],
        clock=programming.clock.name if programming.clock else None,
        next_transition=programming.next_transition.isoformat() if programming.next_transition else None,
        local_time=programming.local_time.isoformat(), timed_events='ACTIVE',
        active_block=(dict(id=active_block.id,name=active_block.block.name,state=active_block.state,
            source=active_block.source,completed_items=len([i for i in active_block.items if i.state in ('COMPLETED','SKIPPED')]),total_items=len(active_block.items)) if active_block else None),
        next_event=(dict(id=next_event.id, name=next_event.event.name,
            timing_mode=next_event.event.timing_mode, state=next_event.state,
            scheduled_for=next_event.scheduled_for_utc.isoformat(), estimated_current_overrun_seconds=overrun_seconds) if next_event else None))
