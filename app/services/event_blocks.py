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
ITEM_TYPES = ('TRACK','IMAGING_ASSET')
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
    elif item_type == 'IMAGING_ASSET': row = ImagingAsset.query.filter_by(station_id=block.station_id, uuid=identifier).first()
    else: raise ValueError('Unsupported block item type')
    if row is None: raise ValueError('Block content belongs to another station or does not exist')
    return row

def add_item(block, item_type, identifier, label='', failure_policy=None):
    require_editable(block)
    if failure_policy not in (None,'') + FAILURE_POLICIES: raise ValueError('Unsupported item failure policy')
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

def validate_block(block, storage=None):
    errors=[]; storage=storage or LocalMediaStorage(); enabled=[i for i in block.items if i.enabled]
    if not enabled: errors.append('Block must contain at least one enabled item.')
    for item in enabled:
        target=item.track or item.imaging_asset
        if target is None or (not available(target,block.station_id) if item.item_type == 'TRACK' else target.station_id!=block.station_id) or not target.enabled or target.ingest_status!='accepted' or target.decommissioned_at:
            errors.append(f'Item {item.position} is disabled or unavailable.'); continue
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
    from app.services.traffic import reconcile_placement
    reconcile_placement(item)
