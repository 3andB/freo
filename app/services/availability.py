"""One availability rule for library discovery and broadcast selection.

station_id remains the immutable catalog/storage owner, not an access rule.
"""
from sqlalchemy import or_
from app.models import Track, Artist, Album


def shared(track):
    return bool((track.audio_kind or 'MUSIC') == 'MUSIC' and (track.available_to_all or
                (track.catalog_artist and track.catalog_artist.available_to_all) or
                (track.catalog_album and track.catalog_album.available_to_all)))


def available(track, station_id):
    return bool(not track.deleted_at and
                (track.station_id == station_id or shared(track)))


def playable(track, station_id):
    return bool(available(track, station_id) and track.enabled and
                track.ingest_status == 'accepted' and not track.decommissioned_at)


def track_scope(station_id):
    return Track.deleted_at.is_(None) & or_(
        Track.station_id == station_id, (Track.audio_kind == 'MUSIC') & or_(Track.available_to_all.is_(True),
        Track.catalog_artist.has(Artist.available_to_all.is_(True)),
        Track.catalog_album.has(Album.available_to_all.is_(True))))


def tracks_for(station_id):
    return Track.query.filter(track_scope(station_id))


def artists_for(station_id):
    return Artist.query.filter(or_(Artist.station_id == station_id,
        Artist.available_to_all.is_(True), Artist.albums.any(Album.available_to_all.is_(True)),
        Artist.songs.any(track_scope(station_id))))


def albums_for(station_id):
    return Album.query.filter(or_(Album.station_id == station_id,
        Album.available_to_all.is_(True), Album.artist.has(Artist.available_to_all.is_(True)),
        Album.songs.any(track_scope(station_id))))


def set_sharing(row, enabled, user_id=None):
    """Apply inheritance; do not revoke audio already handed to an engine."""
    from app.extensions import db
    from app.models import Station, SelectionDecision
    from app.services.admin_media import audit
    from app.services.stations import allocation_lock
    if isinstance(row, Track) and row.audio_kind != 'MUSIC' and enabled:
        raise ValueError('STATION and COMMERCIALS audio belongs to its station')
    if not isinstance(enabled, bool):
        raise ValueError('Choose enabled or disabled')
    allocation_lock()
    db.session.refresh(row)
    songs = [row] if isinstance(row, Track) else list(row.songs)
    previously_shared = {song.id for song in songs if shared(song)}
    row.available_to_all = enabled
    db.session.flush()
    removed = [song for song in songs if song.id in previously_shared and not shared(song)]
    for song in removed:
        pending = SelectionDecision.query.filter(
            SelectionDecision.track_id == song.id,
            SelectionDecision.station_id != song.station_id,
            SelectionDecision.status.in_(('selected', 'submitting', 'queued'))).first()
        # An engine may have a loaded/paused deck that is absent from the AUTO
        # queue. Require consuming stations to stop before removing their access.
        active = SelectionDecision.query.join(Station).filter(
            SelectionDecision.track_id == song.id,
            SelectionDecision.station_id != song.station_id,
            Station.enabled.is_(True), Station.desired_state == 'running').first()
        if pending or active:
            raise ValueError('This music is in use by another channel. Stop that channel and clear its queued selections before removing sharing.')
    audit('music_sharing_updated', user_id=user_id, station_id=row.station_id,
          target_type=type(row).__name__.lower(), target_id=str(row.id),
          summary='Available to all channels' if enabled else 'Direct sharing removed; inherited sharing still applies')
    return row
