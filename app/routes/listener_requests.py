"""Public request catalog plus station-scoped operator moderation."""
from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import uuid
from flask import Blueprint, abort, current_app, jsonify, render_template, request, redirect, url_for, flash
from itsdangerous import URLSafeTimedSerializer, BadSignature
from sqlalchemy import or_
from app.extensions import db
from app.models import ListenerRequest
from app.services import listener_requests as service
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.routes.web import admin_stations, station_or_404

listener_requests = Blueprint('listener_requests', __name__)


def public_station(slug):
    from app.services.stations import public_station_for
    try:
        station = public_station_for(slug)
    except ValueError:
        station = None
    if not station or not station.enabled or station.deleted_at or station.lifecycle_state in ('pending_delete', 'delete_failed'):
        abort(404)
    return station


def serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='listener-requests-v1')


def token_identity(station, required=False):
    token = request.headers.get('X-Request-Token', '')
    try:
        data = serializer().loads(token, max_age=172800)
        if data['station'] != station.id or not isinstance(data['key'], str) or len(data['key']) != 64:
            raise BadSignature('Wrong station')
        return data['key'], token
    except (BadSignature, KeyError, TypeError):
        if required:
            abort(400, 'Reopen the request page and try again.')
        key = secrets.token_hex(32)
        return key, serializer().dumps(dict(station=station.id, key=key))


def public_limit(station, kind, limit):
    now = datetime.now(timezone.utc)
    service.lock(station)
    address = request.remote_addr or 'unknown'
    key = hmac.new(current_app.secret_key.encode(), f'{now.date()}:{address}'.encode(), hashlib.sha256).hexdigest()
    allowed = service.rate_limit(station, key, kind, limit, now)
    db.session.commit()
    if not allowed:
        return jsonify(error='Please wait a minute before trying again.'), 429, {'Retry-After': '60'}


@listener_requests.after_request
def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@listener_requests.get('/requests/<slug>')
def page(slug):
    station = public_station(slug)
    return render_template('listener_requests.html', station=station, enabled=service.settings(station)['enabled'])


@listener_requests.route('/api/stations/<slug>/requests', methods=['GET', 'POST'])
def public_api(slug):
    station = public_station(slug)
    limited = public_limit(station, 'submit' if request.method == 'POST' else 'catalog', 30 if request.method == 'POST' else 120)
    if limited:
        return limited
    if not service.settings(station)['enabled']:
        return jsonify(error='Requests are currently disabled.'), 403
    if request.method == 'POST':
        origin = request.headers.get('Origin')
        if (origin and origin.rstrip('/') != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
            abort(403)
        key, _ = token_identity(station, required=True)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            abort(400)
        try:
            nonce = str(uuid.UUID(data.get('nonce', '')))
            track = str(uuid.UUID(data.get('track', '')))
            row = service.submit(station, track, key, nonce)
            db.session.commit()
            return jsonify(message='Request received. Playback depends on programming and recent plays; requests expire after 24 hours.', status=row.status), 202
        except (ValueError, TypeError, AttributeError) as error:
            db.session.rollback()
            return jsonify(error=str(error) if isinstance(error, ValueError) else 'Invalid request.'), 400
    _, token = token_identity(station)
    term = request.args.get('q', '').strip()[:100]
    query = service.catalog(station)
    if term:
        from app.models import Track
        pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Track.title.ilike(pattern, escape='\\'), Track.artist.ilike(pattern, escape='\\')))
    from app.models import Track
    offset = max(0, min(request.args.get('offset', 0, type=int), 100000))
    rows = query.order_by(Track.artist, Track.title, Track.id).offset(offset).limit(26).all()
    from app.services.automation import _exists
    from app.services.media_storage import LocalMediaStorage
    storage = LocalMediaStorage()
    return jsonify(token=token, tracks=[dict(uuid=t.uuid, title=t.title, artist=t.artist) for t in rows[:25]
        if _exists(storage, t.station.slug, t.storage_key)], more=len(rows) > 25)


def inbox_rows(station):
    tracks, fixed = service.programming_tracks(station)
    rows = ListenerRequest.query.filter_by(station_id=station.id)
    status = request.args.get('status', 'outstanding')
    if status in (*service.OUTSTANDING, *service.TERMINAL):
        rows = rows.filter_by(status=status)
    else:
        rows = rows.filter(ListenerRequest.status.in_(service.OUTSTANDING))
    offset = max(0, request.args.get('offset', 0, type=int))
    rows = rows.order_by(ListenerRequest.created_at, ListenerRequest.id).offset(offset).limit(50).all()
    result = []
    history = service.eligibility_history(station, datetime.now(timezone.utc)) if rows else None
    for row in rows:
        waiting = service.reason(row, station, tracks, history=history) if row.status != 'queued' else row.reason
        if fixed and not waiting:
            waiting = 'Waiting for flexible music programming'
        result.append(dict(row=row, waiting=waiting, eligible=not waiting and row.status in ('pending', 'eligible')))
    return result


@listener_requests.get('/admin/stations/<slug>/requests')
@admin_required
def inbox(slug):
    station = station_or_404(slug, require_enabled=False)
    return render_template('admin/listener_requests.html', selected=station, stations=admin_stations(),
        page='requests', rows=inbox_rows(station), nonce=str(uuid.uuid4()))


@listener_requests.post('/admin/stations/<slug>/requests/<int:identifier>/reject')
@admin_required
def reject(slug, identifier):
    require_csrf()
    if current_admin().role != 'ADMIN':
        abort(403)
    station = station_or_404(slug, require_enabled=False)
    service.lock(station)
    row = ListenerRequest.query.filter_by(id=identifier, station_id=station.id).first_or_404()
    if row.status in service.OUTSTANDING:
        row.status, row.reason = 'rejected', 'Removed by administrator'
        from app.services.admin_media import audit
        audit('listener_request_rejected', user_id=current_admin().id, station_id=station.id,
              target_type='listener_request', target_id=str(row.id), summary='Request removed from queue')
        db.session.commit()
    return redirect(url_for('.inbox', slug=slug), code=303)


@listener_requests.post('/admin/stations/<slug>/requests/<int:identifier>/load')
@admin_required
def load(slug, identifier):
    require_csrf()
    station = station_or_404(slug, require_enabled=False)
    service.lock(station)
    row = ListenerRequest.query.filter_by(id=identifier, station_id=station.id).first_or_404()
    try:
        from app.services.live_sessions import require_owner
        from app.services.live_assist import request_deck, require_mixer, deck_item
        require_owner(station, current_admin())
        tracks, fixed = service.programming_tracks(station)
        waiting = service.reason(row, station, tracks)
        if row.status not in ('pending', 'eligible') or fixed or waiting:
            raise ValueError(waiting or 'This request is not currently eligible.')
        deck = request.form.get('deck')
        if deck not in ('A', 'B'):
            raise ValueError('Choose deck A or B.')
        mixer = require_mixer(station)
        if mixer.get(deck.lower() + '_playing'):
            raise ValueError('Choose a stopped deck.')
        current = deck_item(station, mixer, deck)
        request_deck(station, current_admin(), deck, 'LOAD', row.track.uuid,
            str(current.id) if current else '', request.form.get('nonce'), play_on_load=False, listener_request=row)
        flash('Request loaded for the worker. Use the deck controls to start it.', 'success')
    except (ValueError, RuntimeError, OSError) as error:
        db.session.rollback()
        flash(str(error), 'error')
    return redirect(url_for('.inbox', slug=slug), code=303)
