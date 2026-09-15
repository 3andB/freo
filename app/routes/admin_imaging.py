"""Authenticated imaging library; audio bytes never leave the trusted ingest worker."""
import uuid
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from app.extensions import db
from app.models import ClockSlot, EventBlockItem, ImagingAsset, ImagingGroup, IMAGING_TYPES, MediaIngestJob, SelectionDecision
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, current_admin, media_mutation_required, require_csrf
from app.services.admin_media import audit, stage_upload
from app.services.imaging import (asset_for, create_group, group_for,
    set_asset_enabled, set_group_membership, update_asset, update_group, set_group_enabled,
    decommission_asset)
from app.services.media_probe import MediaValidationError

admin_imaging_blueprint = Blueprint('admin_imaging', __name__)


@admin_imaging_blueprint.errorhandler(413)
def upload_too_large(_error):
    limit = current_app.config['MAX_MEDIA_UPLOAD_BYTES'] // (1024 * 1024)
    return render_template('admin/media_error.html', stations=admin_stations(), selected=None,
        page='imaging', message=f'Upload exceeds the {limit} MB limit.'), 413


def context(station, **values):
    return dict(stations=admin_stations(), selected=station, page='imaging', **values)


def asset_or_404(slug, identifier):
    try:
        return asset_for(slug, identifier)
    except ValueError:
        abort(404)


def group_or_404(slug, identifier):
    try:
        return group_for(slug, identifier)
    except ValueError:
        abort(404)


@admin_imaging_blueprint.get('/admin/stations/<slug>/imaging')
@admin_required
def library(slug):
    station = station_or_404(slug, require_enabled=False)
    query = ImagingAsset.query.filter_by(station_id=station.id)
    search = request.args.get('q', '').strip()[:100]
    if search:
        pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(ImagingAsset.name.ilike(pattern, escape='\\'),
                                 ImagingAsset.cart_code.ilike(pattern, escape='\\')))
    kind = request.args.get('type', '')
    if kind:
        if kind not in IMAGING_TYPES:
            abort(400)
        query = query.filter_by(asset_type=kind)
    group_slug = request.args.get('group', '')
    if group_slug:
        group = group_or_404(slug, group_slug)
        query = query.filter(ImagingAsset.groups.any(ImagingGroup.id == group.id))
    page = request.args.get('page', '1')
    if not page.isdecimal() or not 1 <= int(page) <= 100000:
        abort(400)
    total = query.count()
    assets = query.order_by(ImagingAsset.created_at.desc(), ImagingAsset.id.desc()).offset((int(page)-1)*50).limit(50).all()
    groups = ImagingGroup.query.filter_by(station_id=station.id).order_by(ImagingGroup.name).all()
    jobs = MediaIngestJob.query.filter_by(station_id=station.id, kind='imaging').order_by(MediaIngestJob.created_at.desc()).limit(5).all()
    return render_template('admin/imaging.html', **context(station, assets=assets, groups=groups,
        jobs=jobs, total=total, page_number=int(page), pages=max(1,(total+49)//50), types=IMAGING_TYPES))


@admin_imaging_blueprint.route('/admin/stations/<slug>/imaging/upload', methods=['GET','POST'])
@admin_required
def upload(slug):
    station = station_or_404(slug, require_enabled=False)
    if request.method == 'GET':
        return render_template('admin/imaging_upload.html', **context(station, types=IMAGING_TYPES))
    require_csrf()
    if not station.enabled:
        abort(409)
    file = request.files.get('file')
    if file is None:
        flash('Choose an audio file.', 'error')
        return redirect(url_for('.upload', slug=slug))
    try:
        job = stage_upload(station, current_admin(), file, kind='imaging',
            imaging_type=request.form.get('asset_type'), imaging_name=request.form.get('name'),
            cart_code=request.form.get('cart_code'))
    except (MediaValidationError, ValueError) as error:
        flash(str(error), 'error')
        return redirect(url_for('.upload', slug=slug))
    return redirect(url_for('.job', slug=slug, job_id=job.id), code=303)


@admin_imaging_blueprint.get('/admin/stations/<slug>/imaging/jobs/<job_id>')
@admin_required
def job(slug, job_id):
    station = station_or_404(slug, require_enabled=False)
    row = MediaIngestJob.query.filter_by(station_id=station.id, id=job_id).first()
    if row is None or row.kind not in ('imaging','img_verify','img_enable'):
        abort(404)
    return render_template('admin/imaging_job.html', **context(station, job=row))


@admin_imaging_blueprint.get('/admin/stations/<slug>/imaging/groups/<group_slug>')
@admin_required
def group_detail(slug, group_slug):
    station = station_or_404(slug, require_enabled=False)
    group = group_or_404(slug, group_slug)
    assets = ImagingAsset.query.filter_by(station_id=station.id, decommissioned_at=None).order_by(ImagingAsset.name).limit(500).all()
    return render_template('admin/imaging_group.html', **context(station, group=group, assets=assets))


@admin_imaging_blueprint.post('/admin/stations/<slug>/imaging/groups/create')
@media_mutation_required
def group_create(slug):
    station = station_or_404(slug, require_enabled=False)
    try:
        group = create_group(slug, request.form.get('name'), request.form.get('group_slug'),
            request.form.get('description'), request.form.get('minimum_separation_seconds', 0), commit=False)
        audit('imaging_group_created', user_id=current_admin().id, station_id=station.id,
              target_type='imaging_group', target_id=group.slug, summary='Imaging group created')
        db.session.commit()
        flash('Imaging group created.', 'success')
    except (ValueError, TypeError) as error:
        db.session.rollback(); flash(str(error), 'error')
    return redirect(url_for('.library', slug=slug), code=303)


@admin_imaging_blueprint.post('/admin/stations/<slug>/imaging/groups/<group_slug>/<operation>')
@media_mutation_required
def group_action(slug, group_slug, operation):
    station = station_or_404(slug, require_enabled=False)
    group = group_or_404(slug, group_slug)
    try:
        if operation == 'edit':
            update_group(group, request.form.get('name'), request.form.get('description'),
                request.form.get('minimum_separation_seconds', 0), commit=False)
        elif operation in ('enable','disable'):
            set_group_enabled(group, operation == 'enable', commit=False)
        elif operation in ('assign','remove'):
            asset = asset_or_404(slug, request.form.get('asset_uuid'))
            set_group_membership(slug, group_slug, asset.uuid, operation == 'assign', commit=False)
        else: abort(404)
        audit('imaging_group_' + operation, user_id=current_admin().id, station_id=station.id,
              target_type='imaging_group', target_id=group.slug, summary='Imaging group ' + operation)
        db.session.commit(); flash('Imaging group updated.', 'success')
    except (ValueError, TypeError) as error:
        db.session.rollback(); flash(str(error), 'error')
    return redirect(url_for('.group_detail', slug=slug, group_slug=group_slug), code=303)


@admin_imaging_blueprint.get('/admin/stations/<slug>/imaging/<identifier>')
@admin_required
def detail(slug, identifier):
    station = station_or_404(slug, require_enabled=False)
    asset = asset_or_404(slug, identifier)
    groups = ImagingGroup.query.filter_by(station_id=station.id).order_by(ImagingGroup.name).all()
    history = SelectionDecision.query.filter_by(station_id=station.id, imaging_asset_id=asset.id, status='started').order_by(SelectionDecision.started_at.desc()).limit(10).all()
    queued = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
        SelectionDecision.imaging_asset_id == asset.id, SelectionDecision.status.in_(('selected','queued'))).count()
    return render_template('admin/imaging_asset.html', **context(station, asset=asset, groups=groups,
        history=history, queued=queued, referenced=ClockSlot.query.filter_by(imaging_asset_id=asset.id).count()+EventBlockItem.query.filter_by(imaging_asset_id=asset.id).count(), types=IMAGING_TYPES))


@admin_imaging_blueprint.post('/admin/stations/<slug>/imaging/<identifier>/<operation>')
@media_mutation_required
def asset_action(slug, identifier, operation):
    station = station_or_404(slug, require_enabled=False)
    asset = asset_or_404(slug, identifier)
    if operation in ('enable','verify'):
        if asset.decommissioned_at or asset.ingest_status != 'accepted':
            abort(409)
        job = MediaIngestJob(id=str(uuid.uuid4()), kind='img_enable' if operation == 'enable' else 'img_verify',
            station_id=station.id, admin_user_id=current_admin().id, original_filename=asset.original_filename,
            status='pending', imaging_asset_id=asset.id)
        db.session.add(job); db.session.commit()
        return redirect(url_for('.job', slug=slug, job_id=job.id), code=303)
    try:
        if operation == 'edit':
            update_asset(asset, request.form.get('name'), request.form.get('asset_type'),
                request.form.get('cart_code'), request.form.get('description'), commit=False)
        elif operation == 'disable':
            set_asset_enabled(asset, False, commit=False)
        elif operation in ('assign','remove'):
            group = group_or_404(slug, request.form.get('group_slug'))
            set_group_membership(slug, group.slug, asset.uuid, operation == 'assign', commit=False)
        elif operation == 'decommission':
            confirmation = request.form.get('confirm', '').strip()
            if not confirmation or confirmation not in (asset.cart_code, asset.uuid):
                raise ValueError('Confirm with the cart code or asset UUID')
            active = ()
            if station.desired_state == 'running':
                from app.services.playout_queue import active_ids
                try:
                    active = active_ids(slug)
                except (OSError, RuntimeError, ValueError) as error:
                    raise ValueError('Cannot confirm current playout state; decommission later') from error
            decommission_asset(asset, active_request_ids=active, commit=False)
        else: abort(404)
        audit('imaging_' + operation, user_id=current_admin().id, station_id=station.id,
              target_type='imaging_asset', target_id=asset.uuid, summary='Imaging asset ' + operation)
        db.session.commit(); flash('Imaging asset updated.', 'success')
    except (ValueError, TypeError) as error:
        db.session.rollback(); flash(str(error), 'error')
    return redirect(url_for('.detail', slug=slug, identifier=asset.uuid), code=303)
