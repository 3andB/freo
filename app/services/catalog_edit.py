"""Validated catalog selections shared by import and editing."""
from app.services.availability import artists_for, albums_for
from app.models import Artist, Album, MusicTag, MediaCategory, MusicArtwork
from app.services.music_catalog import artist_for, album_for


def owned(model, station_id, identifier):
    if isinstance(identifier,bool) or not isinstance(identifier,(str,int)):
        raise ValueError('Invalid catalog selection')
    if model is not MusicArtwork:
        if not str(identifier).isdecimal(): raise ValueError('Invalid catalog selection')
        identifier=int(identifier)
    query = artists_for(station_id) if model is Artist else albums_for(station_id) if model is Album else model.query.filter_by(station_id=station_id)
    row = query.filter_by(id=identifier).first()
    if row is None:
        raise ValueError('That selection is unavailable for this station')
    return row


def validate_metadata(station_id, data):
    if not isinstance(data, dict):
        raise ValueError('Invalid song details')
    result = {}
    if 'available_to_all' in data:
        if not isinstance(data['available_to_all'], bool):
            raise ValueError('Choose whether this song is available to all stations')
        if data['available_to_all'] and data.get('audio_kind', 'MUSIC') != 'MUSIC':
            raise ValueError('Only music can be shared with all stations')
        result['available_to_all'] = data['available_to_all']
    if 'playlists' in data:
        from app.services.playlists import get_playlist
        values = data['playlists']
        if not isinstance(values, list) or len(values) > 500:
            raise ValueError('Choose valid playlists')
        result['playlists'] = []
        for value in values:
            playlist = get_playlist(station_id, value)
            if playlist.system_key:
                raise ValueError('Use Audio type to choose a system collection')
            if playlist.id not in result['playlists']:
                result['playlists'].append(playlist.id)
    if 'audio_kind' in data:
        from app.services.audio_classification import validate
        kind, subtype, code = validate(data['audio_kind'], data.get('audio_subtype', ''), data.get('cart_code'))
        result.update(audio_kind=kind, audio_subtype=subtype, cart_code=code)
    if "isrc" in data:
        from app.services.copyright import normalize_isrc
        result["isrc"] = normalize_isrc(data["isrc"])
    for name, limit in [('title', 200), ('artist_name', 200), ('album_name', 200), ('album_artist', 200)]:
        if name in data:
            value = data[name]
            if not isinstance(value, str) or len(value.strip()) > limit:
                raise ValueError(f'{name.replace("_", " ").title()} must be under {limit} characters')
            if value.strip(): result[name] = value.strip()
    if data.get('artist_id') and result.get('artist_name'):
        raise ValueError('Choose an artist or enter a new name')
    if data.get('album_id') and result.get('album_name'):
        raise ValueError('Choose an album or enter a new name')
    artist = None
    if data.get('artist_id'):
        artist = owned(Artist, station_id, data['artist_id']);result['artist_id'] = artist.id
    album_artist = owned(Artist, station_id, data['album_artist_id']) if data.get('album_artist_id') else artist
    if data.get('album_artist_id'): result['album_artist_id'] = album_artist.id
    if 'album_id' in data:
        result['album_id'] = None
        if data['album_id']:
            album = owned(Album, station_id, data['album_id'])
            if not album_artist or album.artist_id != album_artist.id:
                raise ValueError('Choose an album belonging to the selected artist')
            result['album_id'] = album.id
    if data.get('cover_id'):
        result['cover_id'] = owned(MusicArtwork, station_id, data['cover_id']).id
    for key, model in [('tags', MusicTag), ('categories', MediaCategory)]:
        if key in data:
            values = data[key]
            if not isinstance(values, list) or len(values) > 500:
                raise ValueError('Choose valid tags and categories')
            result[key] = list({owned(model, station_id, value).id for value in values})
    for key, minimum, maximum in [('track_number', 1, 999), ('disc_number', 1, 99), ('release_year', 1000, 3000)]:
        if key not in data: continue
        if data[key] in (None, ''):
            result[key] = None
            continue
        try:
            if isinstance(data[key], bool) or str(int(data[key])) != str(data[key]): raise ValueError()
            number = int(data[key])
        except (ValueError, TypeError): raise ValueError(f'{key.replace("_", " ").title()} must be between {minimum} and {maximum}')
        if not minimum <= number <= maximum: raise ValueError(f'{key.replace("_", " ").title()} must be between {minimum} and {maximum}')
        result[key] = number
    return result


def apply_metadata(song, data, station_id=None):
    station_id = station_id or song.station_id
    if isinstance(data, dict) and data.get('isrc') == song.isrc:
        data = {key: value for key, value in data.items() if key != 'isrc'}
    data = validate_metadata(station_id, data)
    if 'available_to_all' in data:
        from app.services.stations import allocation_lock
        allocation_lock()
    artist = owned(Artist, station_id, data['artist_id']) if data.get('artist_id') else None
    if data.get('artist_name'): artist = artist_for(song.station_id, data['artist_name'])
    if artist:
        song.catalog_artist = artist;song.artist = artist.name
        # Changing artist cannot retain an album belonging to somebody else.
        if song.catalog_album and song.catalog_album.artist_id != artist.id and not data.get('album_artist_id'):
            song.catalog_album = None;song.album = ''
    if 'album_id' in data:
        album = owned(Album, station_id, data['album_id']) if data['album_id'] else None
        song.catalog_album = album;song.album = album.title if album else ''
        if not album: song.album_artist = ''
    if data.get('album_name'):
        artist = (owned(Artist, station_id, data['album_artist_id']) if data.get('album_artist_id') else
                  artist_for(song.station_id, data['album_artist']) if data.get('album_artist') else
                  artist or song.catalog_artist or artist_for(song.station_id, song.artist))
        song.catalog_album = album_for(song.station_id, artist, data['album_name'], album_artist=artist.name, year=data.get('release_year'))
        song.album = song.catalog_album.title
    if 'isrc' in data: song.isrc = data['isrc']
    if 'title' in data: song.title = data['title']
    for key in ('track_number', 'disc_number', 'release_year'):
        if key in data: setattr(song, key, data[key])
    if song.catalog_album: song.album_artist = song.catalog_album.artist.name
    if 'cover_id' in data:
        if song.catalog_album: song.catalog_album.cover_id = data['cover_id']
        else: song.cover_id = data['cover_id']
    for key, model in [('tags', MusicTag), ('categories', MediaCategory)]:
        if key in data:
            preserved = [row for row in getattr(song, key) if row.station_id != station_id]
            setattr(song, key, preserved + [owned(model, station_id, identifier) for identifier in data[key]])
    if 'audio_kind' in data:
        from app.services.audio_classification import classify
        classify(song, data['audio_kind'], data['audio_subtype'], data['cart_code'], station_id=station_id)
    if 'available_to_all' in data and data['available_to_all'] != song.available_to_all:
        from app.extensions import db
        from app.services.availability import set_sharing
        db.session.flush()
        set_sharing(song, data['available_to_all'])
    if 'playlists' in data:
        from app.extensions import db
        from app.models import Playlist, PlaylistItem, Station
        from sqlalchemy import or_
        from sqlalchemy.orm import selectinload
        from app.services.playlists import ordered_ids, replace_order
        # Serialize membership changes with the Music organizer and ingest workers.
        db.session.query(Station.id).filter_by(id=station_id).with_for_update().first()
        wanted = set(data['playlists'])
        rows = Playlist.query.filter_by(station_id=station_id, deleted_at=None).filter(
            Playlist.system_key.is_(None), or_(Playlist.id.in_(wanted),
                Playlist.items.any(PlaylistItem.track_id == song.id))).options(
                    selectinload(Playlist.items)).order_by(Playlist.id).populate_existing().with_for_update().all()
        for row in rows:
            ids = ordered_ids(row)
            if (row.id in wanted) == (song.id in ids):
                continue
            replace_order(row, ids + [song.id] if row.id in wanted else [i for i in ids if i != song.id])
    return song
