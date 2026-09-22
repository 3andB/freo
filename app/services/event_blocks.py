"""Station-scoped block definitions and immutable ordered execution snapshots."""
from app.services.availability import available
from app.services.availability import tracks_for
import re
from datetime import datetime, timezone

from app.extensions import db
from app.models import (EventBlock, EventBlockExecution, EventBlockItem,
                        EventBlockItemExecution, ImagingAsset, SelectionDecision, Track)
from app.services.media_storage import LocalMediaStorage
from app.services.stations import get_station

BLOCK_TYPES = ('GENERIC','STOPSET','NEWS','LEGAL_ID','PROMO_BLOCK','SPECIAL')
FAILURE_POLICIES = ('SKIP_FAILED_ITEM','ABORT_BLOCK')
ITEM_TYPES = ('TRACK',)
ACTIVE_STATES = ('PENDING','QUEUED','STARTED')

def _clean(value, limit, required=False):
    value = ''.join(c for c in (value or '').strip() if c.isprintable())
    if len(value) > limit or required and not value: raise ValueError(f'Enter a value of at most {limit} characters')
    return value

def _slug(value):
    value = re.sub(r'[^a-z0-9]+', '-', (value or '').strip().lower()).strip('-')
    if not value or len(value) > 64: raise ValueError('Block slug is invalid')
    return value

def block_for(slug, identifier):
    station = get_station(slug)
    row = EventBlock.query.filter_by(station_id=station.id, slug=identifier).first() if station else None
    if row is None: raise ValueError('Block not found')
    return row

def commercial_log_for_block(block):
    if not block.id:
        return None
    from app.models import TrafficLog, TrafficPlacement
    return TrafficLog.query.join(TrafficPlacement, TrafficPlacement.traffic_log_id == TrafficLog.id).join(
        EventBlockItem, EventBlockItem.id == TrafficPlacement.event_block_item_id).filter(
        TrafficLog.station_id == block.station_id, EventBlockItem.event_block_id == block.id).first()


def require_editable(block):
    if commercial_log_for_block(block):
        raise ValueError('Finalized commercial sequences are managed through Commercials')


def save_block(slug, *, identifier=None, name, description='', block_type='GENERIC', failure_policy='ABORT_BLOCK'):
    station = get_station(slug)
    if station is None: raise ValueError('Station not found')
    if block_type not in BLOCK_TYPES or failure_policy not in FAILURE_POLICIES: raise ValueError('Unsupported block option')
    row = block_for(slug, identifier) if identifier else EventBlock(station_id=station.id, slug=_slug(name), enabled=False)
    require_editable(row)
    row.name, row.description = _clean(name,120,True), _clean(description,500)
    row.block_type, row.failure_policy = block_type, failure_policy
    db.session.add(row); db.session.commit(); return row

def _target(block, item_type, identifier):
    if item_type == 'TRACK': row = tracks_for(block.station_id).filter_by(uuid=identifier).first()
    else: raise ValueError('Unsupported block item type')
    if row is None: raise ValueError('Block content belongs to another station or does not exist')
    return row

def add_item(block, item_type, identifier, label='', failure_policy=None):
    require_editable(block)
    if failure_policy not in (None,'') + FAILURE_POLICIES: raise ValueError('Unsupported item failure policy')
    if item_type == 'IMAGING_ASSET':
        from app.services.audio_classification import migrated_audio
        identifier = migrated_audio(block.station_id,identifier).uuid
        item_type = 'TRACK'
    target = _target(block,item_type,identifier)
    row = EventBlockItem(block=block, position=len(block.items)+1, item_type=item_type,
        track_id=target.id if item_type=='TRACK' else None, imaging_asset_id=target.id if item_type=='IMAGING_ASSET' else None,
        label=_clean(label,120), failure_policy=failure_policy or None)
    db.session.add(row); db.session.commit(); return row

def remove_item(block, item_id):
    require_editable(block)
    row = EventBlockItem.query.filter_by(id=item_id,event_block_id=block.id).first()
    if row is None: raise ValueError('Block item not found')
    db.session.delete(row); db.session.flush()
    for position,item in enumerate(EventBlockItem.query.filter_by(event_block_id=block.id).order_by(EventBlockItem.position),1): item.position=position
    db.session.commit()

def reorder(block, ordered_ids):
    require_editable(block)
    items = {i.id:i for i in block.items}
    try: ids=[int(v) for v in ordered_ids]
    except (TypeError,ValueError): raise ValueError('Invalid block item order')
    if len(ids)!=len(items) or set(ids)!=set(items): raise ValueError('Block item order does not match this block')
    temporary=max(items)+len(items)+1000
    for n,item_id in enumerate(ids,1): items[item_id].position=temporary+n
    db.session.flush()
    for n,item_id in enumerate(ids,1): items[item_id].position=n
    db.session.commit()

def validate_block(block, storage=None, *, check_files=True):
    errors=[]; storage=storage or LocalMediaStorage(); enabled=[i for i in block.items if i.enabled]
    if not enabled: errors.append('Block must contain at least one enabled item.')
    for item in enabled:
        target=item.track or item.imaging_asset
        if target is None or (not available(target,block.station_id) if item.item_type == 'TRACK' else target.station_id!=block.station_id) or not target.enabled or target.ingest_status!='accepted' or target.decommissioned_at:
            errors.append(f'Item {item.position} is disabled or unavailable.'); continue
        if not check_files: continue
        try:
            (storage.regular_file if item.track else storage.imaging_file)(target.station.slug,target.storage_key)
        except (OSError,ValueError): errors.append(f'Item {item.position} failed storage verification.')
    return errors

def set_enabled(block, enabled):
    require_editable(block)
    if enabled:
        errors=validate_block(block)
        if errors: raise ValueError(errors[0])
    block.enabled=bool(enabled); db.session.commit()

def create_execution(block, source, *, occurrence=None, clock_slot=None, admin_user_id=None):
    if not block.enabled: raise ValueError('Block is disabled')
    errors=validate_block(block)
    if errors: raise ValueError(errors[0])
    if occurrence:
        existing=EventBlockExecution.query.filter_by(timed_event_occurrence_id=occurrence.id).first()
        if existing: return existing
    execution=EventBlockExecution(station_id=block.station_id,event_block_id=block.id,source=source,
        timed_event_occurrence_id=occurrence.id if occurrence else None,clock_slot_id=clock_slot.id if clock_slot else None,admin_user_id=admin_user_id)
    db.session.add(execution); db.session.flush()
    for item in block.items:
        if item.enabled:
            db.session.add(EventBlockItemExecution(execution=execution,event_block_item_id=item.id,position=item.position,
                item_type=item.item_type,track_id=item.track_id,imaging_asset_id=item.imaging_asset_id,label=item.label,
                failure_policy=item.failure_policy or block.failure_policy))
    db.session.commit(); return execution

def active_execution(station_id):
    return EventBlockExecution.query.filter_by(station_id=station_id).filter(EventBlockExecution.state.in_(ACTIVE_STATES)).order_by(EventBlockExecution.id).first()

def prepare_next(execution, now=None):
    now=now or datetime.now(timezone.utc)
    item=next((i for i in execution.items if i.state=='PENDING'),None)
    if item is None: return None
    target=item.track or item.imaging_asset
    valid=target and (available(target,execution.station_id) if item.track else target.station_id==execution.station_id) and target.enabled and target.ingest_status=='accepted' and not target.decommissioned_at
    if not valid:
        item.state='FAILED'; item.failed_at=now; item.failure_reason='content_unavailable'
        if item.failure_policy=='ABORT_BLOCK': execution.state='FAILED'; execution.failure_reason='content_unavailable'
        db.session.commit(); return None
    decision=SelectionDecision(station_id=execution.station_id,track_id=item.track_id,imaging_asset_id=item.imaging_asset_id,
        selection_method='event_block',status='selected',selected_at=now,admin_user_id=execution.admin_user_id,
        clock_slot_id=execution.clock_slot_id,reason=f'block:{execution.id}:item:{item.position}')
    db.session.add(decision); db.session.flush(); item.selection_decision_id=decision.id; db.session.commit(); return item

def confirm_item_started(decision, now):
    item=EventBlockItemExecution.query.filter_by(selection_decision_id=decision.id).first()
    if not item: return
    execution=item.execution
    for prior in execution.items:
        if prior.position < item.position and prior.state=='STARTED': prior.state='COMPLETED'; prior.completed_at=now
    item.state='STARTED'; item.started_at=now
    if execution.state!='STARTED': execution.state='STARTED'; execution.started_at=now
    occurrence=execution.timed_event_occurrence
    if occurrence and occurrence.state!='STARTED': occurrence.state='STARTED'; occurrence.started_at=now; occurrence.failure_reason=None
    if occurrence and execution.playlist:
        cursors = (occurrence.runtime or {}).get('playlist_cursors', {})
        cursor = cursors.get(str(item.position)) or (occurrence.runtime or {}).get('playlist_cursor')
        if cursor:
            occurrence.event.playlist_state = cursor
    from app.services.traffic import reconcile_placement
    reconcile_placement(item)


def create_playlist_execution(occurrence, storage=None):
    """Freeze a finite run; the cursor commits only when its item starts."""
    from app.services.playlists import playable_tracks, advance
    event = occurrence.event
    existing = EventBlockExecution.query.filter_by(timed_event_occurrence_id=occurrence.id).first()
    if existing: return existing
    tracks = playable_tracks(event.playlist, event.station_id, storage or LocalMediaStorage())
    if not tracks: raise ValueError('Playlist has no playable audio')
    if event.playlist_playback == 'ONE':
        track, cursor = advance(event.playlist, tracks, event.playlist_state)
        tracks = [track]
        occurrence.runtime = {**(occurrence.runtime or {}), 'playlist_cursor':cursor}
    elif event.playlist.mode == 'RANDOM':
        shuffled = []
        cursor = dict(event.playlist_state or {})
        cursors = {}
        for position in range(1, len(tracks) + 1):
            track, cursor = advance(event.playlist, tracks, cursor,
                exclude={item.id for item in shuffled})
            shuffled.append(track)
            cursors[str(position)] = dict(cursor)
        tracks = shuffled
        occurrence.runtime = {**(occurrence.runtime or {}), 'playlist_cursors': cursors}
    execution = EventBlockExecution(station_id=event.station_id, playlist=event.playlist,
        playlist_revision=event.playlist.revision, source='TIMED_EVENT', timed_event_occurrence=occurrence)
    db.session.add(execution)
    for position, track in enumerate(tracks, 1):
        execution.items.append(EventBlockItemExecution(position=position,item_type='TRACK',track=track,
            label=track.title[:120],failure_policy='SKIP_FAILED_ITEM'))
    db.session.flush()
    return execution


def confirm_finished(station, decision_id, at, identity):
    """Only matching engine EOF completes event audio; replay is harmless."""
    from app.models import TimedEventOccurrence
    decision = SelectionDecision.query.filter_by(id=decision_id,station_id=station.id,status='started',socket_identity=identity).first()
    if not decision or decision.started_at and at < decision.started_at.replace(tzinfo=decision.started_at.tzinfo or timezone.utc): return
    occurrence = decision.timed_event_occurrence
    item = decision.block_item_execution
    if item:
        if item.state != 'STARTED': return
        item.state, item.completed_at = 'COMPLETED', at
        execution = item.execution
        if execution.state in ('ABORTED','CANCELLED','FAILED'):
            db.session.commit();return
        if all(i.state in ('COMPLETED','SKIPPED','FAILED') for i in execution.items):
            finish_execution(execution,at)
            occurrence = execution.timed_event_occurrence
    if occurrence and occurrence.state == 'STARTED' and (not item or item.execution.state == 'COMPLETED'):
        occurrence.state, occurrence.completed_at = 'COMPLETED', at
    db.session.commit()


def reconcile_occurrences(station_id):
    """Repair stale Playing labels from durable, already finished sequences."""
    from app.models import TimedEventOccurrence
    executions = EventBlockExecution.query.join(EventBlockExecution.timed_event_occurrence).filter(
        EventBlockExecution.station_id == station_id,
        EventBlockExecution.state.in_(('COMPLETED', 'FAILED', 'ABORTED', 'CANCELLED')),
        TimedEventOccurrence.state.in_(('QUEUED', 'STARTED'))).all()
    for execution in executions:
        occurrence = execution.timed_event_occurrence
        occurrence.state = 'FAILED' if execution.state == 'ABORTED' else execution.state
        occurrence.completed_at = execution.completed_at
        occurrence.failure_reason = execution.failure_reason or ('sequence_aborted' if execution.state == 'ABORTED' else None)
    return len(executions)


def finish_execution(execution, at):
    """Keep partial playback visible; never call an entirely failed run success."""
    failed = any(i.state in ('FAILED','SKIPPED') for i in execution.items)
    played = any(i.state == 'COMPLETED' for i in execution.items)
    execution.state = 'COMPLETED' if played else 'FAILED'
    execution.completed_at = at
    execution.failure_reason = 'partial_playback' if played and failed else 'no_items_completed' if not played else None
    if execution.timed_event_occurrence:
        occurrence = execution.timed_event_occurrence
        occurrence.state = execution.state
        occurrence.completed_at = at
        occurrence.failure_reason = execution.failure_reason


def cancel_future_items(execution, reason):
    from app.models import EventQueueCancellation
    for item in execution.items:
        if item.state not in ('PENDING','QUEUED','FAILED'): continue
        decision = item.selection_decision
        if decision and decision.status in ('queued','submitting'):
            if not db.session.get(EventQueueCancellation,decision.id):
                db.session.add(EventQueueCancellation(decision_id=decision.id,station_id=execution.station_id,processed=False))
        elif decision and decision.status == 'selected':
            decision.status, decision.reason = 'failed', reason
        if item.state != 'FAILED': item.state = 'SKIPPED'
        item.failure_reason = reason


def submit_snapshot(execution, now):
    """Stage every finite event item before releasing the sequence to the engine."""
    from app.services.playout_queue import push_sequence, socket_identity
    from app.services.availability import playable
    decisions=[];items=[]
    for item in execution.items:
        if item.state!='PENDING':continue
        target=item.track or item.imaging_asset
        valid=target and (playable(target,execution.station_id) if item.track else target.enabled and target.ingest_status=='accepted' and not target.decommissioned_at)
        if valid:
            try:
                storage=LocalMediaStorage()
                (storage.regular_file if item.track else storage.imaging_file)(target.station.slug,target.storage_key)
            except (OSError,ValueError):valid=False
        if not valid:
            item.state='FAILED';item.failure_reason='content_unavailable';item.failed_at=now
            if item.failure_policy=='ABORT_BLOCK':
                execution.state='FAILED';execution.failure_reason='content_unavailable'
                if execution.timed_event_occurrence:
                    execution.timed_event_occurrence.state='FAILED';execution.timed_event_occurrence.failure_reason='content_unavailable'
                db.session.commit();return
            continue
        decision=item.selection_decision
        if not decision:
            decision=SelectionDecision(station_id=execution.station_id,track_id=item.track_id,imaging_asset_id=item.imaging_asset_id,selection_method='event_block',status='submitting',selected_at=now,reason=f'block:{execution.id}:item:{item.position}')
            db.session.add(decision);db.session.flush();item.selection_decision=decision
        decision.status='submitting';decisions.append(decision);items.append(item)
    if not decisions:
        execution.state='FAILED';execution.failure_reason='no_playable_items'
        if execution.timed_event_occurrence:execution.timed_event_occurrence.state='FAILED'
        db.session.commit();return
    db.session.commit()
    try:
        request_ids=push_sequence(decisions)
    except (OSError,ValueError,RuntimeError):
        # Socket acceptance can precede a lost response. Remove future requests
        # by their decision annotations even when no request IDs were received.
        cancel_future_items(execution,'sequence_unavailable')
        for item,decision in zip(items,decisions):
            item.state='FAILED';item.failure_reason='sequence_unavailable';decision.status='failed';decision.reason='sequence_unavailable'
        execution.state='FAILED';execution.failure_reason='sequence_unavailable'
        if execution.timed_event_occurrence:execution.timed_event_occurrence.state='FAILED';execution.timed_event_occurrence.failure_reason='sequence_unavailable'
        db.session.commit();return
    identity=socket_identity(execution.station.slug)
    from app.services.traffic import placement_queued
    for item,decision,rid in zip(items,decisions,request_ids):
        decision.status='queued';decision.liquidsoap_request_id=rid;decision.socket_identity=identity
        item.state='QUEUED';item.queued_at=now;placement_queued(item)
    execution.state='QUEUED'
    if execution.timed_event_occurrence:
        execution.timed_event_occurrence.state='QUEUED';execution.timed_event_occurrence.queued_at=now
    db.session.commit()
