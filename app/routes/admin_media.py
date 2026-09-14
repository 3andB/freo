"""Authenticated, CSRF-protected media management; no raw-file delivery."""
import uuid
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from app.extensions import db
from app.models import AuditEvent, MediaCategory, MediaIngestJob, SelectionDecision, Track
from app.services.admin_auth import admin_required, current_admin, media_mutation_required
from app.services.admin_media import audit, stage_upload, track_for_station
from app.services.automation import assign_track
from app.services.media import normalize, set_enabled_db
from app.services.media_probe import MediaValidationError
from app.routes.web import admin_stations, station_or_404

admin_media_blueprint = Blueprint('admin_media', __name__)


def page_context(station, **extra):
    return dict(stations=admin_stations(), selected=station, page='media', **extra)


def owned_track(station, track_uuid):
    track = track_for_station(station, track_uuid)
    if track is None:
        abort(404)
    return track


def media_url(station):
    return url_for('admin_media.library', slug=station.slug)


@admin_media_blueprint.get('/admin/stations/<slug>/media')
@admin_required
def library(slug):
    station = station_or_404(slug, require_enabled=False)
    query = Track.query.filter_by(station_id=station.id)
    search = request.args.get('q', '').strip()[:100]
    if search:
        pattern = '%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Track.title.ilike(pattern, escape='\\'),
                                 Track.artist.ilike(pattern, escape='\\'),
                                 Track.album.ilike(pattern, escape='\\')))
    category_id = request.args.get('category', '')
    if category_id:
        if not category_id.isdecimal():
            abort(400)
        category = MediaCategory.query.filter_by(station_id=station.id, id=int(category_id)).first()
        if category is None:
            abort(404)
        query = query.filter(Track.categories.any(MediaCategory.id == category.id))
    enabled = request.args.get('enabled', '')
    if enabled in ('yes', 'no'):
        query = query.filter_by(enabled=enabled == 'yes')
    elif enabled:
        abort(400)
    ingest_status = request.args.get('status', '')
    if ingest_status in ('accepted', 'rejected'):
        query = query.filter_by(ingest_status=ingest_status)
    elif ingest_status:
        abort(400)
    media_type = request.args.get('format', '')
    if media_type:
        if media_type != 'mp3':
            abort(400)
        query = query.filter_by(media_type=media_type)
    sort = request.args.get('sort', 'title')
    sorts = {'title': Track.title.asc(), 'artist': Track.artist.asc(),
             'newest': Track.created_at.desc(), 'duration': Track.duration_ms.asc()}
    if sort not in sorts:
        abort(400)
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        abort(400)
    if page > 100000:
        abort(400)
    total = query.count()
    tracks = query.order_by(sorts[sort], Track.id).offset((page - 1) * 50).limit(50).all()
    jobs = (MediaIngestJob.query.filter_by(station_id=station.id, kind='ingest')
            .order_by(MediaIngestJob.created_at.desc()).limit(5).all())
    return render_template('admin/media.html', **page_context(station, tracks=tracks, total=total,
                           page_number=page, pages=max(1, (total + 49) // 50), jobs=jobs,
                           categories=MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name).all()))


@admin_media_blueprint.route('/admin/stations/<slug>/media/upload', methods=['GET', 'POST'])
@admin_required
def upload(slug):
    station = station_or_404(slug, require_enabled=False)
    if request.method == 'GET':
        return render_template('admin/media_upload.html', **page_context(station))
    from app.services.admin_auth import require_csrf
    require_csrf()
    if not station.enabled:
        abort(409)
    file = request.files.get('file')
    if file is None:
        flash('Choose an audio file to upload.', 'error')
        return redirect(url_for('admin_media.upload', slug=slug))
    try:
        job = stage_upload(station, current_admin(), file)
    except MediaValidationError as error:
        flash(str(error), 'error')
        return redirect(url_for('admin_media.upload', slug=slug))
    return redirect(url_for('admin_media.job_status', slug=slug, job_id=job.id), code=303)


@admin_media_blueprint.get('/admin/stations/<slug>/media/jobs/<job_id>')
@admin_required
def job_status(slug, job_id):
    station = station_or_404(slug, require_enabled=False)
    job = MediaIngestJob.query.filter_by(station_id=station.id, id=job_id).first()
    if job is None:
        abort(404)
    return render_template('admin/media_job.html', **page_context(station, job=job))


@admin_media_blueprint.get('/admin/stations/<slug>/media/<track_uuid>')
@admin_required
def track_detail(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    categories = MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name).all()
    starts = (SelectionDecision.query.filter_by(station_id=station.id, track_id=track.id, status='started')
              .order_by(SelectionDecision.started_at.desc()).limit(5).all())
    count = SelectionDecision.query.filter_by(station_id=station.id, track_id=track.id, status='started').count()
    return render_template('admin/media_track.html', **page_context(station, track=track,
                           categories=categories, starts=starts, play_count=count))


@admin_media_blueprint.post('/admin/stations/<slug>/media/<track_uuid>/edit')
@media_mutation_required
def edit_track(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    if track.decommissioned_at:
        abort(409)
    try:
        title = normalize(request.form.get('title'), 200)
        artist = normalize(request.form.get('artist'), 200)
        album = normalize(request.form.get('album'), 200)
        if not title or not artist:
            raise MediaValidationError('Title and artist are required')
        track.title, track.artist, track.album = title, artist, album
        audit('media_metadata_updated', user_id=current_admin().id, station_id=station.id,
              target_id=track.uuid, summary='Descriptive metadata updated')
        db.session.commit()
        flash('Track metadata updated.', 'success')
    except MediaValidationError as error:
        flash(str(error), 'error')
    return redirect(url_for('admin_media.track_detail', slug=slug, track_uuid=track_uuid), code=303)


@admin_media_blueprint.post('/admin/stations/<slug>/media/<track_uuid>/categories')
@media_mutation_required
def update_categories(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    if track.decommissioned_at:
        abort(409)
    requested = request.form.getlist('category_id')
    if any(not value.isdecimal() for value in requested):
        abort(400)
    desired = set(map(int, requested))
    categories = MediaCategory.query.filter_by(station_id=station.id).all()
    by_id = {category.id: category for category in categories}
    if not desired.issubset(by_id):
        abort(404)
    current = {category.id for category in track.categories}
    for category_id in desired - current:
        assign_track(slug, track.uuid, by_id[category_id].slug, True, commit=False)
        audit('media_category_assigned', user_id=current_admin().id, station_id=station.id,
              target_id=track.uuid, summary=f'Category {by_id[category_id].slug} assigned')
    for category_id in current - desired:
        if category_id not in by_id:
            abort(409)
        assign_track(slug, track.uuid, by_id[category_id].slug, False, commit=False)
        audit('media_category_removed', user_id=current_admin().id, station_id=station.id,
              target_id=track.uuid, summary=f'Category {by_id[category_id].slug} removed')
    db.session.commit()
    flash('Categories updated.', 'success')
    return redirect(url_for('admin_media.track_detail', slug=slug, track_uuid=track_uuid), code=303)


@admin_media_blueprint.post('/admin/stations/<slug>/media/<track_uuid>/disable')
@media_mutation_required
def disable_track(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    set_enabled_db(track, False)
    audit('media_disabled', user_id=current_admin().id, station_id=station.id,
          target_id=track.uuid, summary='Excluded from future selection; queued audio is retained')
    db.session.commit()
    flash('Track disabled. Current or queued audio may finish.', 'success')
    return redirect(url_for('admin_media.track_detail', slug=slug, track_uuid=track_uuid), code=303)


def queue_media_job(station, track, kind):
    job = MediaIngestJob(id=str(uuid.uuid4()), kind=kind, station_id=station.id,
                         admin_user_id=current_admin().id, original_filename=track.original_filename,
                         status='pending', track_id=track.id)
    db.session.add(job)
    db.session.commit()
    return job


@admin_media_blueprint.post('/admin/stations/<slug>/media/<track_uuid>/enable')
@media_mutation_required
def enable_track(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    if track.decommissioned_at or track.ingest_status != 'accepted':
        abort(409)
    job = queue_media_job(station, track, 'enable')
    return redirect(url_for('admin_media.job_status', slug=slug, job_id=job.id), code=303)


@admin_media_blueprint.post('/admin/stations/<slug>/media/<track_uuid>/verify')
@media_mutation_required
def verify_track(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    job = queue_media_job(station, track, 'verify')
    return redirect(url_for('admin_media.job_status', slug=slug, job_id=job.id), code=303)


@admin_media_blueprint.post('/admin/stations/<slug>/media/<track_uuid>/decommission')
@media_mutation_required
def decommission_track(slug, track_uuid):
    station = station_or_404(slug, require_enabled=False)
    track = owned_track(station, track_uuid)
    if request.form.get('confirm') != 'decommission':
        abort(400)
    if track.decommissioned_at is None:
        track.decommissioned_at = datetime.now(timezone.utc)
        track.enabled = False
        track.categories.clear()
        audit('media_decommissioned', user_id=current_admin().id, station_id=station.id,
              target_id=track.uuid, summary='Disabled and uncategorized; file and history retained')
        db.session.commit()
    flash('Track decommissioned; file and history retained.', 'success')
    return redirect(url_for('admin_media.track_detail', slug=slug, track_uuid=track_uuid), code=303)


@admin_media_blueprint.get('/admin/audit')
@admin_required
def audit_view():
    events = AuditEvent.query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(100).all()
    return render_template('admin/media_audit.html', stations=admin_stations(), selected=None,
                           page='audit', events=events)


@admin_media_blueprint.errorhandler(413)
def upload_too_large(_error):
    limit = current_app.config['MAX_MEDIA_UPLOAD_BYTES'] // (1024 * 1024)
    return render_template('admin/media_error.html', stations=admin_stations(), selected=None,
                           page='media', message=f'Upload exceeds the {limit} MB limit.'), 413
