"""Authenticated Live Assist; mutations create worker-processed intent only."""
from app.services.availability import tracks_for
import uuid

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_

from app.extensions import db
from app.models import EventBlock, ImagingAsset, LiveCartSlot, MediaCategory, Track
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, can_control_playout, current_admin, require_csrf
from app.services.live_assist import (request_deck, fire_cart, set_mixer, play_cue_on_b, assign_cart, clear_cue, cue_track, queue_block,
    queue_playable, request_abort_block, request_fade, request_skip,
    request_takeover, set_hold, set_mode, status)

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
    tracks = tracks_for(station.id).filter_by(enabled=True, ingest_status='accepted', decommissioned_at=None)
    imaging = ImagingAsset.query.filter_by(station_id=station.id, enabled=True, ingest_status='accepted', decommissioned_at=None)
    category=request.args.get('category','')
    if category:
        selected_category=MediaCategory.query.filter_by(station_id=station.id,slug=category).first_or_404();tracks=tracks.filter(Track.categories.any(MediaCategory.id==selected_category.id))
    if search:
        tracks = tracks.filter(or_(Track.title.ilike(pattern, escape='\\'), Track.artist.ilike(pattern, escape='\\'), Track.album.ilike(pattern, escape='\\')))
        imaging = imaging.filter(or_(ImagingAsset.name.ilike(pattern, escape='\\'), ImagingAsset.cart_code.ilike(pattern, escape='\\')))
    slots=LiveCartSlot.query.filter_by(station_id=station.id).all()
    return render_template('admin/live.html', stations=admin_stations(), selected=station,
        page='live', live=status(station), tracks=tracks.order_by(Track.title).limit(30).all(),
        imaging=imaging.order_by(ImagingAsset.asset_type, ImagingAsset.cart_code, ImagingAsset.name).limit(60).all(),
        blocks=EventBlock.query.filter_by(station_id=station.id,enabled=True).order_by(EventBlock.name).all(),
        categories=MediaCategory.query.filter_by(station_id=station.id,enabled=True).order_by(MediaCategory.name).all(),
        hot_slots={x.position:x for x in slots if x.role=='HOT'},id_slots={x.position:x for x in slots if x.role=='ID'},
        search=search, selected_category=category,live_nonce=str(uuid.uuid4()), uuid4=lambda: str(uuid.uuid4()))


@admin_live_blueprint.get('/admin/api/stations/<slug>/live-status')
@admin_required
def live_status(slug):
    return jsonify(status(station_for_operator(slug)))


@admin_live_blueprint.get('/admin/api/stations/<slug>/song-search')
@admin_required
def song_search(slug):
    station=station_for_operator(slug);term=request.args.get('q','').strip()[:100]
    query=tracks_for(station.id).filter_by(enabled=True,ingest_status='accepted',decommissioned_at=None)
    if term:
        pattern='%' + term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        query=query.filter(or_(Track.title.ilike(pattern,escape='\\'),Track.artist.ilike(pattern,escape='\\'),Track.album.ilike(pattern,escape='\\')))
    tracks=query.order_by(Track.artist,Track.title).limit(50).all()
    return jsonify([{'uuid':x.uuid,'title':x.title,'artist':x.artist,'album':x.album,'bpm':x.bpm,'duration_ms':x.duration_ms} for x in tracks])


@admin_live_blueprint.post('/admin/stations/<slug>/live/<action>')
@admin_required
def action(slug, action):
    station = station_for_operator(slug)
    require_csrf()
    if action not in ('deck','mixer','fire-cart','play-b','hold', 'resume','mode','takeover','fade','cue','clear-cue','start-cue','repeat','assign-cart','queue-track', 'queue-imaging', 'queue-block', 'abort-block', 'skip'):
        abort(404)
    try:
        if action in ('mixer','play-b','takeover','fade','cue','clear-cue','start-cue','repeat','skip') and station.automation and station.automation.operator_mode == 'DJ_BOOTH':
            raise ValueError('The deck controls have changed. Refresh the page to use the deck buttons.')
        if action=='deck':
            request_deck(station,current_admin(),request.form.get('deck'),request.form.get('operation'),request.form.get('identifier'),request.form.get('expected_decision_id',''),request.form.get('nonce'),fade_seconds=request.form.get('fade_seconds',3),play_on_load=request.form.get('play_on_load','false')=='true')
            message='Deck command requested. The deck display updates when the station applies it.'
        elif action=='mixer':
            set_mixer(station,current_admin(),request.form.get('control'),request.form.get('value'));message='Mixer change requested.'
        elif action=='fire-cart':
            fire_cart(station,current_admin(),request.form.get('role'),int(request.form.get('position','0')),request.form.get('nonce'));message='Cart requested. It will play when the cart bus is free.'
        elif action=='play-b':
            play_cue_on_b(station,current_admin(),request.form.get('nonce'));message='Deck B start requested. Move the fader toward B to bring it on air.'
        elif action=='mode':set_mode(station,current_admin(),request.form.get('mode'));message='DJ booth mode changed.'
        elif action=='takeover':
            expected=request.form.get('expected_decision_id','')
            if expected and not expected.isdecimal():raise ValueError('Invalid current selection')
            request_takeover(station,current_admin(),request.form.get('identifier'),int(expected) if expected else None,request.form.get('nonce'));message='Controlled takeover requested.'
        elif action == 'fade':
            expected=request.form.get('expected_decision_id','')
            if not expected.isdecimal():raise ValueError('Current item changed; refresh before fading')
            request_fade(station,current_admin(),int(expected),request.form.get('nonce'));message='Three-second fade and advance requested.'
        elif action == 'cue':
            cue_track(station,current_admin(),request.form.get('identifier'));message='Song loaded into the cue deck.'
        elif action == 'clear-cue':
            clear_cue(station,current_admin());message='Cue deck cleared.'
        elif action == 'start-cue':
            current=status(station).get('current');track=station.automation.cued_track
            if not track:raise ValueError('Load a song into Cue first')
            expected = request.form.get('expected_decision_id', '')
            if (current and (not expected.isdecimal() or int(expected) != current['decision_id'])) or (not current and expected):
                raise ValueError('Current item changed; review the on-air song before crossfading')
            request_takeover(station,current_admin(),track.uuid,current['decision_id'] if current else None,request.form.get('nonce'));clear_cue(station,current_admin());message='Crossfade to cue requested.'
        elif action == 'repeat':
            current=status(station).get('current')
            if not current or current.get('kind')!='track':raise ValueError('No song is currently playing')
            queue_playable(station,current_admin(),'track',current['uuid'],request.form.get('nonce'));message='One repeat queued at the end of the real queue.'
        elif action=='assign-cart':
            assign_cart(station, current_admin(), request.form.get('role'),
                int(request.form.get('position', '0')), request.form.get('identifier'),
                request.form.get('label', ''),request.form.get('description',''),request.form.get('playback_mode','OVER'),int(request.form.get('duck_percent','50')))
            message='Cart position assigned.'
        elif action in ('hold', 'resume'):
            set_hold(station, current_admin(), action == 'hold')
            message = 'Automation refill held; items already queued may still play.' if action == 'hold' else 'Automation resumed using the current schedule.'
        elif action in ('queue-track', 'queue-imaging'):
            if station.automation and station.automation.operator_mode == 'DJ_BOOTH':
                raise ValueError('Load songs onto a deck in DJ mode. The queue is available in AUTO.')
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
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(ok=True, message=message)
        flash(message, 'success')
    except ValueError as error:
        db.session.rollback()
        if request.accept_mimetypes.best == 'application/json':
            return jsonify(ok=False, message=str(error)), 409
        flash(str(error), 'error')
    return redirect(url_for('.page', slug=slug, q=request.form.get('q', '')[:100]))


@admin_live_blueprint.get('/admin/api/stations/<slug>/cart-search')
@admin_required
def cart_search(slug):
    station=station_for_operator(slug)
    pattern=search_term()
    tracks=tracks_for(station.id).filter_by(enabled=True,ingest_status='accepted',decommissioned_at=None).filter(or_(Track.title.ilike(pattern,escape='\\'),Track.artist.ilike(pattern,escape='\\'))).order_by(Track.title).limit(50).all()
    assets=ImagingAsset.query.filter_by(station_id=station.id,enabled=True,ingest_status='accepted',decommissioned_at=None).filter(or_(ImagingAsset.name.ilike(pattern,escape='\\'),ImagingAsset.cart_code.ilike(pattern,escape='\\'))).order_by(ImagingAsset.name).limit(50).all()
    return jsonify([{'uuid':x.uuid,'label':f'Song · {x.artist} · {x.title}'} for x in tracks]+[{'uuid':x.uuid,'label':f'{x.asset_type.replace("_"," ")} · {x.name}'} for x in assets])
