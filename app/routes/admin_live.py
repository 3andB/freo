"""Authenticated Live Assist; mutations create worker-processed intent only."""
import uuid

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_

from app.extensions import db
from app.models import EventBlock, ImagingAsset, Track
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, can_control_playout, current_admin, require_csrf
from app.services.live_assist import queue_block, queue_playable, request_abort_block, request_skip, set_hold, status

admin_live_blueprint = Blueprint('admin_live', __name__)


def station_for_operator(slug):
    station = station_or_404(slug, require_enabled=False)
    if not can_control_playout(current_admin(), station):
        abort(403)
    return station


def search_term():
    term = request.args.get('q', '').strip()[:100]
    return '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


@admin_live_blueprint.get('/admin/stations/<slug>/live')
@admin_required
def page(slug):
    station = station_for_operator(slug)
    search = request.args.get('q', '').strip()[:100]
    pattern = search_term()
    tracks = Track.query.filter_by(station_id=station.id, enabled=True, ingest_status='accepted', decommissioned_at=None)
    imaging = ImagingAsset.query.filter_by(station_id=station.id, enabled=True, ingest_status='accepted', decommissioned_at=None)
    if search:
        tracks = tracks.filter(or_(Track.title.ilike(pattern, escape='\\'), Track.artist.ilike(pattern, escape='\\'), Track.album.ilike(pattern, escape='\\')))
        imaging = imaging.filter(or_(ImagingAsset.name.ilike(pattern, escape='\\'), ImagingAsset.cart_code.ilike(pattern, escape='\\')))
    return render_template('admin/live.html', stations=admin_stations(), selected=station,
        page='live', live=status(station), tracks=tracks.order_by(Track.title).limit(30).all(),
        imaging=imaging.order_by(ImagingAsset.asset_type, ImagingAsset.cart_code, ImagingAsset.name).limit(60).all(),
        blocks=EventBlock.query.filter_by(station_id=station.id,enabled=True).order_by(EventBlock.name).all(),
        search=search, live_nonce=str(uuid.uuid4()), uuid4=lambda: str(uuid.uuid4()))


@admin_live_blueprint.get('/admin/api/stations/<slug>/live-status')
@admin_required
def live_status(slug):
    return jsonify(status(station_for_operator(slug)))


@admin_live_blueprint.post('/admin/stations/<slug>/live/<action>')
@admin_required
def action(slug, action):
    station = station_for_operator(slug)
    require_csrf()
    if action not in ('hold', 'resume', 'queue-track', 'queue-imaging', 'queue-block', 'abort-block', 'skip'):
        abort(404)
    try:
        if action in ('hold', 'resume'):
            set_hold(station, current_admin(), action == 'hold')
            message = 'Automation refill held; items already queued may still play.' if action == 'hold' else 'Automation resumed using the current schedule.'
        elif action in ('queue-track', 'queue-imaging'):
            kind = action.removeprefix('queue-')
            queue_playable(station, current_admin(), kind, request.form.get('identifier'), request.form.get('nonce'))
            message = 'Queued at the end of the real playout queue.'
        elif action == 'queue-block':
            queue_block(station,current_admin(),request.form.get('identifier')); message='Ordered block queued; automation will not enter between its items.'
        elif action == 'abort-block':
            request_abort_block(station,current_admin(),int(request.form.get('execution_id','0'))); message='Block abort requested; the worker will clear its remaining sequence.'
        else:
            expected = request.form.get('expected_decision_id', '')
            if not expected.isdecimal():
                raise ValueError('Current item changed; refresh before skipping')
            request_skip(station, current_admin(), int(expected), request.form.get('nonce'))
            message = 'Skip requested. The worker will verify the current item before advancing.'
        flash(message, 'success')
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(url_for('.page', slug=slug, q=request.form.get('q', '')[:100]))
