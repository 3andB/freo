"""Music catalog identity layered under station-specific song programming."""
from app.services.availability import available
import re
from app.extensions import db
from app.models import Album, Artist, MusicTag, Track
from app.services.media import normalize


def identity(value):
    return ' '.join((value or '').casefold().split())


def optional_int(value, minimum, maximum):
    if value in (None, ''): return None
    text=str(value).split('/',1)[0].strip()
    try: number=int(text)
    except (TypeError,ValueError): return None
    return number if minimum <= number <= maximum else None


def artist_for(station_id, name):
    name=normalize(name,200,'Unknown Artist');key=identity(name)
    row=Artist.query.filter_by(station_id=station_id,normalized_name=key).first()
    if not row:
        row=Artist(station_id=station_id,name=name,normalized_name=key);db.session.add(row);db.session.flush()
    return row


def album_for(station_id, artist, title, album_artist='', year=None, genre=''):
    title=normalize(title,200,'')
    if not title: return None
    key=identity(title);row=Album.query.filter_by(station_id=station_id,artist_id=artist.id,normalized_title=key).first()
    if not row:
        row=Album(station_id=station_id,artist_id=artist.id,title=title,normalized_title=key,
                  album_artist=normalize(album_artist,200,''),release_year=year,genre=normalize(genre,100,''));db.session.add(row);db.session.flush()
    else:
        if album_artist and not row.album_artist: row.album_artist=normalize(album_artist,200,'')
        if year and not row.release_year: row.release_year=year
        if genre and not row.genre: row.genre=normalize(genre,100,'')
    return row


def organize_song(song, tags=None):
    """Create/reuse catalog parents while keeping legacy display snapshots current."""
    tags=tags or {};artist=artist_for(song.station_id,song.artist)
    album_artist=normalize(tags.get('album_artist') or song.album_artist,200,'')
    year=optional_int(tags.get('date') or tags.get('year') or song.release_year,1000,3000)
    genre=normalize(tags.get('genre') or song.genre,100,'')
    album=album_for(song.station_id,artist,song.album,album_artist,year,genre)
    song.artist_id=artist.id;song.album_id=album.id if album else None;song.album_artist=album_artist
    song.track_number=optional_int(tags.get('track') or tags.get('tracknumber') or song.track_number,1,999)
    song.disc_number=optional_int(tags.get('disc') or tags.get('discnumber') or song.disc_number,1,99)
    song.release_year=year;song.genre=genre
    if 'isrc' in tags and tags['isrc'] != song.isrc:
        from app.services.copyright import normalize_isrc
        song.isrc = normalize_isrc(tags['isrc'])
    return song


def tag_for(station_id,name):
    name=normalize(name,80);slug=re.sub(r'[^a-z0-9]+','-',name.casefold()).strip('-')
    if not slug: raise ValueError('Invalid tag')
    row=MusicTag.query.filter_by(station_id=station_id,slug=slug).first()
    if not row: row=MusicTag(station_id=station_id,name=name,slug=slug);db.session.add(row);db.session.flush()
    return row


def bulk_categories(station, songs, category, assign=True):
    if category.station_id!=station.id or any(not available(song,station.id) for song in songs): raise ValueError('Music belongs to another station')
    for song in songs:
        if assign and category not in song.categories: song.categories.append(category)
        if not assign and category in song.categories: song.categories.remove(category)
    return len(songs)
