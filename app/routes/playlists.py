"""Playlist workspace; music assignment uses the shared Music action endpoint."""
from flask import Blueprint, jsonify, render_template, request, url_for
from sqlalchemy.orm import selectinload
from app.models import Playlist, PlaylistItem, MediaCategory, Artist, Album, MusicTag, Track
from app.routes.web import station_or_404, admin_stations
from app.services.admin_auth import admin_required
from app.services.availability import available, playable, artists_for, albums_for, tracks_for
from app.services import playlists as service

playlists = Blueprint('playlists', __name__)


@playlists.get('/admin/stations/<slug>/playlists')
@admin_required
def page(slug):
    station = station_or_404(request.args.get('station', slug), require_enabled=False)
    return render_template('admin/playlists.html', selected=station, stations=admin_stations(), page='playlists')


@playlists.get('/admin/api/stations/<slug>/playlists')
@admin_required
def catalog(slug):
    station = station_or_404(slug, require_enabled=False)
    state = station.automation
    return jsonify(separation=dict(track_seconds=state.track_separation_seconds if state else 0,
        artist_seconds=state.artist_separation_seconds if state else 0),
        leaders=[dict(id=t.id, name=f'{t.title} · {t.artist} ({t.audio_kind})') for t in tracks_for(station.id).filter(
            Track.audio_kind.in_(('MUSIC','STATION')), Track.enabled.is_(True), Track.ingest_status=='accepted', Track.decommissioned_at.is_(None)).order_by(Track.title,Track.id)],
        tags=[dict(id=t.id,name=t.name) for t in MusicTag.query.filter_by(station_id=station.id).order_by(MusicTag.name)],
        playlists=[service.summary(row) for row in service.listing(station.id)],
        categories=[dict(id=row.id, name=row.name) for row in MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name)],
        artists=[dict(id=row.id, name=row.name) for row in artists_for(station.id).order_by(Artist.name)],
        albums=[dict(id=row.id, name=row.title + ' · ' + row.artist.name) for row in albums_for(station.id).order_by(Album.title)])


@playlists.get('/admin/api/stations/<slug>/playlists/<int:identifier>')
@admin_required
def detail(slug, identifier):
    from app.services.loudness import gain_for
    station = station_or_404(slug, require_enabled=False)
    row = Playlist.query.options(selectinload(Playlist.items).joinedload(PlaylistItem.track)).filter_by(station_id=station.id, id=identifier, deleted_at=None).first_or_404()
    songs = []
    from app.services.smart_playlists import members
    for position, track in enumerate(members(row), 1):
        if available(track, station.id):
            song = dict(uuid=track.uuid, title=track.title, artist=track.artist, album=track.album,
                        duration_ms=track.playback_duration_ms, playable=playable(track, station.id), gain=gain_for(track, station))
            if track.ingest_status == 'accepted' and not track.decommissioned_at:
                song['audition'] = url_for('admin_media.audition', slug=station.slug, track_uuid=track.uuid)
        else:
            song = dict(uuid=track.uuid, title='Unavailable song', artist='', album='', duration_ms=0, playable=False)
        song['position'] = position
        songs.append(song)
    return jsonify(**service.summary(row), songs=songs)
