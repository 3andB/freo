"""Safe read-only station media metadata."""
from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from app.models import Track
from app.services.stations import get_station

media_blueprint = Blueprint('media', __name__)


def public_track(track):
    return {
        'uuid': track.uuid, 'title': track.title, 'artist': track.artist,
        'album': track.album, 'media_type': track.media_type,
        'duration_ms': track.duration_ms, 'enabled': track.enabled,
        'ingest_status': track.ingest_status,
    }


def station_or_none(slug):
    try:
        return get_station(slug)
    except ValueError:
        return None


@media_blueprint.get('/api/stations/<slug>/media')
def list_media(slug):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    query = Track.query.filter_by(station_id=station.id)
    if request.args.get('enabled') in ('true', 'false'):
        query = query.filter_by(enabled=request.args['enabled'] == 'true')
    search = request.args.get('q', '').strip()[:100]
    if search:
        pattern = '%' + search.replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(Track.title.ilike(pattern, escape='\\'), Track.artist.ilike(pattern, escape='\\'), Track.album.ilike(pattern, escape='\\')))
    return jsonify(tracks=[public_track(track) for track in query.order_by(Track.id).limit(100)])


@media_blueprint.get('/api/stations/<slug>/media/<track_uuid>')
def show_media(slug, track_uuid):
    station = station_or_none(slug)
    if station is None:
        return jsonify(status='not_found'), 404
    track = Track.query.filter_by(station_id=station.id, uuid=track_uuid).first()
    if track is None:
        return jsonify(status='not_found'), 404
    return jsonify(public_track(track))
