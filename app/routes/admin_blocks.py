"""Authenticated station-scoped ordered block editor."""
from app.services.availability import tracks_for
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import AuditEvent, EventBlock, EventBlockExecution, ImagingAsset, Track
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, can_manage_events, current_admin, require_csrf
from app.services.admin_media import audit
from app.services.event_blocks import (BLOCK_TYPES, FAILURE_POLICIES, add_item, block_for,
    commercial_log_for_block, remove_item, reorder, save_block, set_enabled, validate_block)

admin_blocks_blueprint=Blueprint('admin_blocks',__name__)

def station_for_admin(slug):
    station=station_or_404(slug,require_enabled=False)
    if not can_manage_events(current_admin(),station): abort(403)
    return station

def context(station,**extra): return dict(stations=admin_stations(),selected=station,page='blocks',**extra)

@admin_blocks_blueprint.get('/admin/stations/<slug>/blocks')
@admin_required
def list_page(slug):
    station=station_for_admin(slug)
    rows=EventBlock.query.filter_by(station_id=station.id).order_by(EventBlock.enabled.desc(),EventBlock.name).all()
    return render_template('admin/blocks.html',**context(station,blocks=rows,types=BLOCK_TYPES,policies=FAILURE_POLICIES))

@admin_blocks_blueprint.post('/admin/stations/<slug>/blocks')
@admin_required
def create(slug):
    station=station_for_admin(slug); require_csrf()
    try:
        row=save_block(slug,name=request.form.get('name'),description=request.form.get('description'),block_type=request.form.get('block_type'),failure_policy=request.form.get('failure_policy'))
        audit('event_block_created',user_id=current_admin().id,station_id=station.id,target_type='event_block',target_id=row.slug,summary=f'Created block {row.name}')
        db.session.commit(); flash('Block created as a disabled draft.','success'); return redirect(url_for('.detail',slug=slug,identifier=row.slug),code=303)
    except ValueError as error: db.session.rollback(); flash(str(error),'error'); return redirect(url_for('.list_page',slug=slug),code=303)

@admin_blocks_blueprint.get('/admin/stations/<slug>/blocks/<identifier>')
@admin_required
def detail(slug,identifier):
    station=station_for_admin(slug)
    try: row=block_for(slug,identifier)
    except ValueError: abort(404)
    log = commercial_log_for_block(row)
    if log:
        return redirect(url_for('admin_traffic.log_detail',slug=slug,log_date=log.log_date))
    executions=EventBlockExecution.query.filter_by(event_block_id=row.id).order_by(EventBlockExecution.id.desc()).limit(25).all()
    tracks=tracks_for(station.id).filter_by(enabled=True,ingest_status='accepted',decommissioned_at=None).order_by(Track.title).all()
    imaging=ImagingAsset.query.filter_by(station_id=station.id,enabled=True,ingest_status='accepted',decommissioned_at=None).order_by(ImagingAsset.cart_code,ImagingAsset.name).all()
    return render_template('admin/block_detail.html',**context(station,block=row,errors=validate_block(row),tracks=tracks,imaging=imaging,executions=executions,types=BLOCK_TYPES,policies=FAILURE_POLICIES))

@admin_blocks_blueprint.post('/admin/stations/<slug>/blocks/<identifier>/<operation>')
@admin_required
def mutate(slug,identifier,operation):
    station=station_for_admin(slug); require_csrf()
    try: row=block_for(slug,identifier)
    except ValueError: abort(404)
    try:
        if operation=='edit':
            save_block(slug,identifier=identifier,name=request.form.get('name'),description=request.form.get('description'),block_type=request.form.get('block_type'),failure_policy=request.form.get('failure_policy')); action='event_block_updated'
        elif operation in ('enable','disable'): set_enabled(row,operation=='enable'); action=f'event_block_{operation}d'
        elif operation=='add': add_item(row,request.form.get('item_type'),request.form.get('identifier'),request.form.get('label'),request.form.get('failure_policy')); action='event_block_item_added'
        elif operation=='remove': remove_item(row,request.form.get('item_id')); action='event_block_item_removed'
        elif operation=='reorder': reorder(row,request.form.getlist('item_id')); action='event_block_items_reordered'
        elif operation=='move':
            item_id=int(request.form.get('item_id')); direction=request.form.get('direction')
            ids=[item.id for item in row.items]; index=ids.index(item_id); target=index+(-1 if direction=='up' else 1)
            if target < 0 or target >= len(ids): raise ValueError('Item cannot move farther')
            ids[index],ids[target]=ids[target],ids[index]; reorder(row,ids); action='event_block_items_reordered'
        else: abort(404)
        audit(action,user_id=current_admin().id,station_id=station.id,target_type='event_block',target_id=row.slug,summary=f'{action.replace("_"," ")} for {row.name}')
        db.session.commit(); flash('Block updated.','success')
    except ValueError as error: db.session.rollback(); flash(str(error),'error')
    return redirect(url_for('.detail',slug=slug,identifier=identifier),code=303)
