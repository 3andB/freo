"""Station-owned nonmusic audio and its persistent default collections."""
import re
from app.extensions import db
from app.models import Playlist, Track

KINDS = ('MUSIC', 'STATION', 'COMMERCIALS')
SUBTYPES = ('', 'station_id', 'promo', 'announcement', 'jingle', 'sweeper', 'liner', 'cart', 'generic')


def migrated_audio(station_id, identifier):
    """Resolve an old identity without creating any new Imaging references."""
    from app.models import ImagingAsset
    track = Track.query.join(ImagingAsset, Track.legacy_imaging_id == ImagingAsset.id).filter(
        Track.station_id == station_id, ImagingAsset.station_id == station_id,
        ImagingAsset.uuid == identifier, Track.deleted_at.is_(None)).first()
    if track is None:
        raise ValueError('Imaging is retired or unavailable/cross-station. Migrate this audio and select it from STATION or COMMERCIALS.')
    return track


def validate(kind, subtype='', code=None):
    if kind not in KINDS or subtype not in SUBTYPES:
        raise ValueError('Choose Music, STATION or COMMERCIALS and a valid station audio label')
    if subtype and kind != 'STATION':
        raise ValueError('Station audio labels require STATION')
    code = (code or '').strip()
    if code and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', code):
        raise ValueError('Cart code must use at most 40 letters, numbers, underscores or hyphens')
    return kind, subtype, code or None


def defaults(station_id):
    # Callers hold the station lock. The unique key also protects concurrent seeds.
    result = {}
    for kind in KINDS[1:]:
        row = Playlist.query.filter_by(station_id=station_id, system_key=kind).first()
        if row is None:
            row = Playlist(station_id=station_id, name=kind, purpose=kind, system_key=kind,
                           description=f'All {kind.lower()} audio for this station')
            db.session.add(row)
            db.session.flush()
        result[kind] = row
    return result


def classify(track, kind, subtype='', code=None, *, station_id=None):
    from app.services.playlists import ordered_ids, replace_order
    from app.models import SelectionDecision, Station
    if station_id is not None and station_id != track.station_id:
        raise ValueError('Only the owning station can classify this audio')
    kind, subtype, code = validate(kind, subtype, code)
    db.session.query(Station.id).filter_by(id=track.station_id).with_for_update().first()
    if kind != 'MUSIC' and (track.audio_kind or 'MUSIC') == 'MUSIC':
        if SelectionDecision.query.filter(SelectionDecision.track_id == track.id,
                SelectionDecision.station_id != track.station_id,
                SelectionDecision.status.in_(('selected','submitting','queued','started'))).first():
            raise ValueError('This shared audio is in use by another station')
    track.audio_kind, track.audio_subtype, track.cart_code = kind, subtype, code
    if kind != 'MUSIC':
        track.available_to_all = False
    for purpose, playlist in defaults(track.station_id).items():
        ids = ordered_ids(playlist)
        wanted = ids + [track.id] if purpose == kind and track.id not in ids else [i for i in ids if i != track.id] if purpose != kind else ids
        if wanted != ids:
            replace_order(playlist, wanted)
    return track
