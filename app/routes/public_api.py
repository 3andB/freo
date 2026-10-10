"""Versioned, bearer-authenticated read API in the existing Flask application."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, g, jsonify, request
from sqlalchemy import or_
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.models import ApiCredentialStation, Station, Track
from app.services import public_api as service
from app.services.admin_auth import can_access_station

public_api = Blueprint('public_api', __name__, url_prefix='/api/v1')
ERRORS = {
    400: ('invalid_request', 'Invalid request parameters.'),
    401: ('unauthorized', 'A valid API bearer token is required.'),
    403: ('forbidden', 'This credential cannot access that station.'),
    404: ('not_found', 'Resource not found.'),
    405: ('method_not_allowed', 'Method not allowed.'),
    429: ('rate_limited', 'Too many requests. Try again later.'),
    500: ('internal_error', 'The request could not be completed.'),
    503: ('unavailable', 'The service is temporarily unavailable.'),
}


def is_api_request():
    return request.path == '/api/v1' or request.path.startswith('/api/v1/')


def error_response(status, headers=None):
    code, message = ERRORS.get(status, ('request_failed', 'The request could not be completed.'))
    response = jsonify(error=dict(code=code, message=message))
    response.status_code = status
    if headers:
        response.headers.update(headers)
    if status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer realm="Freo API v1"'
    return response


def init_api(app):
    # Install before browser-session maintenance; API auth never depends on cookies.
    @app.before_request
    def authenticate_api():
        if not is_api_request():
            return None
        allowed, retry = service.rate_limit('network', service.network_key(), 300)
        if not allowed:
            return error_response(429, {'Retry-After': str(retry)})
        credential = service.authenticate(request.headers.get('Authorization', ''))
        if credential is None:
            return error_response(401)
        allowed, retry = service.rate_limit('credential', credential.id, 120)
        if not allowed:
            return error_response(429, {'Retry-After': str(retry)})
        g.api_credential = credential

    @app.after_request
    def api_headers(response):
        if is_api_request():
            if request.method == 'OPTIONS' and response.status_code == 200 and not response.is_json:
                # Flask's automatic OPTIONS response otherwise has an HTML type.
                response.set_data(current_app.json.dumps({'data': None}))
                response.mimetype = 'application/json'
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.errorhandler(HTTPException)
    def api_http_error(error):
        if not is_api_request():
            return error
        headers = {key: value for key, value in error.get_headers()
                   if key.lower() not in ('content-type', 'content-length')}
        return error_response(error.code, headers)

    @app.errorhandler(500)
    def api_server_error(error):
        return error_response(500) if is_api_request() else error

    app.register_blueprint(public_api)


@public_api.errorhandler(Exception)
def unexpected_error(error):
    db.session.rollback()
    if isinstance(error, HTTPException):
        headers = {k: v for k, v in error.get_headers() if k.lower() not in ('content-type', 'content-length')}
        return error_response(error.code, headers)
    from app.services.installation_settings import SettingsUnavailable
    if isinstance(error, SettingsUnavailable):
        g.freo_cookie_secure = current_app.config['SESSION_COOKIE_SECURE']
        return error_response(503)
    # Never log request headers, token values, or exception payloads.
    current_app.logger.error('Public API request failed (%s)', type(error).__name__)
    return error_response(500)


def integer(name, default, maximum):
    supplied = request.args.get(name, str(default))
    if not supplied.isascii() or not supplied.isdecimal() or len(supplied) > 9:
        abort(400)
    value = int(supplied)
    if not 1 <= value <= maximum:
        abort(400)
    return value


def parameters(*names):
    if any(key not in names or len(request.args.getlist(key)) != 1 for key in request.args):
        abort(400)


def pagination():
    return integer('page', 1, 1000000), integer('per_page', 50, 100)


def collection(query, serialize):
    page, size = pagination()
    total = query.count()
    rows = query.offset((page - 1) * size).limit(size).all()
    return jsonify(data=[serialize(row) for row in rows], meta=dict(page=page, per_page=size, total=total))


def station_for(slug):
    station = service.station_query().filter_by(slug=slug).first()
    if station is None:
        abort(404)
    credential = g.api_credential
    if (db.session.get(ApiCredentialStation, (credential.id, station.id)) is None
            or not can_access_station(credential.creator, station)):
        abort(403)
    return station


def station_data(station):
    return {key: getattr(station, key) for key in ('id', 'slug', 'name', 'description', 'timezone')}


@public_api.get('/stations')
def stations():
    parameters('page', 'per_page')
    # Active ADMIN is the only issuer role; it has access to every current station.
    query = service.station_query().join(ApiCredentialStation).filter(
        ApiCredentialStation.credential_id == g.api_credential.id).order_by(Station.slug, Station.id)
    return collection(query, station_data)


@public_api.get('/stations/<slug>')
def station(slug):
    station = station_for(slug)
    parameters()
    return jsonify(data=station_data(station))


@public_api.get('/stations/<slug>/now-playing')
def now_playing(slug):
    station = station_for(slug)
    parameters()
    from app.services.player import now_playing as state
    result = state(station)
    data = {key: result[key] for key in ('program', 'mode', 'fresh', 'observed_at', 'stream_online', 'timezone')}
    data['observed_at'] = utc_timestamp(data['observed_at'])
    data['current'] = [{key: row[key] for key in ('track', 'freo_track_id', 'title', 'artist', 'started_at')}
                       for row in result['current']]
    for row in data['current']:
        row['started_at'] = utc_timestamp(row['started_at'])
    return jsonify(data=data)


def utc_timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, timezone.utc)
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


@public_api.get('/stations/<slug>/schedule')
def schedule(slug):
    station = station_for(slug)
    parameters('days', 'page', 'per_page')
    days = integer('days', 7, 7)
    page, size = pagination()
    now = datetime.now(timezone.utc)
    from app.services.player import automatic_entries, timestamp
    try:
        entries = automatic_entries(station, now.astimezone(ZoneInfo(station.timezone)).date(), days)
    except ValueError:
        return error_response(503)
    entries = [{key: row[key] for key in ('start', 'end', 'title', 'source')}
               for row in entries if timestamp(row['end']) > now]
    return jsonify(data=entries[(page - 1) * size:page * size],
        meta=dict(page=page, per_page=size, total=len(entries), timezone=station.timezone, days=days))


@public_api.get('/stations/<slug>/listeners')
def listeners(slug):
    station = station_for(slug)
    parameters('range')
    period = request.args.get('range', '24h')
    if period not in ('24h', '7d', '30d'):
        abort(400)
    from app.services.broadcast_status import cached_status
    from app.services.statistics import aggregate, window
    now = int(datetime.now(timezone.utc).timestamp())
    bounds = window({'range': period}, station.timezone, now)
    observed = cached_status([station], now)[station.slug]
    stats = aggregate(station.id, bounds['start'], bounds['end'], now)
    return jsonify(data=dict(current=observed['listeners'], online=observed['online'],
        fresh=observed['observed_at'] is not None, observed_at=utc_timestamp(observed['observed_at']),
        summary={key: stats['total'][key] for key in ('average', 'peak', 'listener_hours', 'coverage')},
        timeline=[dict(at=utc_timestamp(row['at']), average=row['average'],
                       peak=row['peak'] if row['observed'] else None) for row in stats['timeline']]),
        meta=dict(range=period, start=utc_timestamp(bounds['start']), end=utc_timestamp(bounds['end']),
                  timezone=station.timezone, resolution_seconds=stats['resolution_seconds']))


def library_query(station):
    from app.services.availability import tracks_for
    return tracks_for(station.id).filter_by(audio_kind='MUSIC', enabled=True,
        ingest_status='accepted', decommissioned_at=None)


def track_data(track):
    return {key: getattr(track, key) for key in ('uuid', 'freo_track_id', 'title', 'artist', 'album',
        'genre', 'release_year', 'isrc', 'duration_ms')}


@public_api.get('/stations/<slug>/library/tracks')
def tracks(slug):
    station = station_for(slug)
    parameters('page', 'per_page', 'q')
    term = request.args.get('q', '').strip()
    if len(term) > 100:
        abort(400)
    query = library_query(station)
    if term:
        pattern = '%' + term.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Track.title.ilike(pattern, escape='\\'), Track.artist.ilike(pattern, escape='\\')))
    return collection(query.order_by(Track.artist, Track.title, Track.id), track_data)


@public_api.get('/stations/<slug>/library/tracks/<uuid>')
def track(slug, uuid):
    station = station_for(slug)
    parameters()
    row = library_query(station).filter_by(uuid=uuid).first()
    if row is None:
        abort(404)
    return jsonify(data=track_data(row))
