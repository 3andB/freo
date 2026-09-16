"""Trusted station media ingestion and approved playlist generation."""
from app.services.availability import tracks_for
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import uuid as uuidlib

from app.extensions import db
from app.models import Track
from app.services.media_probe import MediaValidationError, probe
from app.services.media_storage import LocalMediaStorage, grant_playout_read
from app.services.stations import get_station

MAX_MEDIA_FILE_BYTES = 1024 * 1024 * 1024
PLAYLIST_ROOT = Path('/var/lib/freo/playlists')


def require_admin():
    if os.geteuid() != 0:
        raise PermissionError('This media operation requires the root-run admin CLI')


def require_ingest_identity():
    """The web user never receives approved-media write access."""
    if os.geteuid() == 0:
        return
    import pwd
    if pwd.getpwuid(os.geteuid()).pw_name != 'freo-ingest':
        raise PermissionError('Media ingestion requires the dedicated ingest worker')


def normalize(value, limit, fallback=''):
    if value is None:
        value = fallback
    if not isinstance(value, str) or '\x00' in value:
        raise MediaValidationError('Invalid metadata')
    value = ''.join(ch for ch in value.strip() if ch.isprintable())[:limit].strip()
    return value or fallback


def station_for_media(slug):
    station = get_station(slug)
    if station is None or not station.enabled:
        raise ValueError('Station does not exist or is disabled')
    return station


def _prepare_dirs(storage, slug):
    import grp
    import pwd
    gid = grp.getgrnam('freo-playout').gr_gid
    try:
        owner = pwd.getpwnam('freo-ingest').pw_uid
    except KeyError:
        owner = 0
    root = storage.root
    if root.is_symlink():
        raise ValueError('Symlink media root is forbidden')
    root.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        os.chown(root, 0, gid)
        os.chmod(root, 0o751)
    station_dir = storage.station_dir(slug)
    if station_dir.is_symlink():
        raise ValueError('Symlink station media directory is forbidden')
    originals = station_dir / 'originals'
    imaging = station_dir / 'imaging'
    staging = station_dir / 'staging'
    artwork = station_dir / 'artwork'
    for path, group, mode in ((station_dir, gid, 0o2750), (originals, gid, 0o2750),
                              (imaging, gid, 0o2750), (artwork, gid, 0o2750), (staging, gid, 0o2700)):
        path.mkdir(exist_ok=True)
        if path.is_symlink():
            raise ValueError('Symlink storage directory is forbidden')
        if os.geteuid() == 0:
            os.chown(path, owner, group)
            os.chmod(path, mode)
        elif path.stat().st_uid != os.geteuid():
            raise PermissionError('Ingest directory is not owned by the ingest worker')
    return originals, staging


def ingest(slug, source, title=None, artist=None, album=None, storage=None, *,
           original_filename=None, enabled=True, update_playlist=True, auto_enable_pending=False, import_metadata=None):
    require_ingest_identity()
    station = station_for_media(slug)
    storage = storage or LocalMediaStorage()
    originals, staging = _prepare_dirs(storage, slug)
    source = Path(source)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > MAX_MEDIA_FILE_BYTES:
        os.close(fd)
        raise MediaValidationError('Source must be a nonempty regular file within size limit')
    temp_fd, temp_name = tempfile.mkstemp(prefix='.ingest-', dir=staging)
    temp = Path(temp_name)
    final = None
    committed = False
    try:
        total = 0
        with os.fdopen(fd, 'rb') as source_stream, os.fdopen(temp_fd, 'wb') as target:
            checksum = hashlib.sha256()
            while chunk := source_stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_MEDIA_FILE_BYTES:
                    raise MediaValidationError('File exceeds size limit')
                checksum.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        digest = checksum.hexdigest()
        existing = Track.query.filter_by(station_id=station.id, checksum_sha256=digest).first()
        if existing:
            return existing, True
        details = probe(temp)
        tags = details['tags']
        original_name = normalize(original_filename or source.name, 255, 'unnamed')
        display_title = normalize(title if title is not None else tags.get('title'), 200, normalize(Path(original_name).stem, 200, 'Untitled'))
        display_artist = normalize(artist if artist is not None else tags.get('artist'), 200, 'Unknown Artist')
        display_album = normalize(album if album is not None else tags.get('album'), 200, '')
        track_uuid = uuidlib.uuid4()
        key = track_uuid.hex + details['extension']
        final = storage.approved_path(slug, key)
        playout_gid = __import__('grp').getgrnam('freo-playout').gr_gid
        if os.geteuid() == 0:
            os.chown(temp, 0, playout_gid)
        elif temp.stat().st_gid != playout_gid:
            raise PermissionError('Staged media does not have the playout-read group')
        grant_playout_read(temp)
        os.replace(temp, final)
        track = Track(
            station_id=station.id, uuid=str(track_uuid), title=display_title,
            artist=display_artist, album=display_album, original_filename=original_name,
            storage_key=key, media_type=details['media_type'], duration_ms=details['duration_ms'],
            bitrate_kbps=details['bitrate_kbps'], sample_rate_hz=details['sample_rate_hz'],
            channels=details['channels'], file_size_bytes=total, checksum_sha256=digest,
            enabled=enabled, auto_enable_pending=auto_enable_pending, ingest_status='accepted',
        )
        db.session.add(track)
        db.session.flush()
        from app.services.music_catalog import organize_song
        organize_song(track, tags)
        if import_metadata is not None:
            from app.services.catalog_edit import apply_metadata
            choices=dict(import_metadata)
            if choices.get('artist_id') and 'album_id' not in choices and not choices.get('album_name') and track.album:
                choices['album_name']=track.album
            apply_metadata(track,choices)
        db.session.commit()
        committed = True
        if update_playlist:
            refresh_playlist(slug, storage)
        return track, False
    except Exception:
        db.session.rollback()
        if final is not None and not committed:
            final.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def approved_tracks(slug):
    station = station_for_media(slug)
    return tracks_for(station.id).filter_by(ingest_status='accepted', enabled=True, decommissioned_at=None).order_by(Track.id).all()


def refresh_playlist(slug, storage=None):
    require_admin()
    storage = storage or LocalMediaStorage()
    tracks = approved_tracks(slug)
    paths = []
    for track in tracks:
        try:
            paths.append(str(storage.regular_file(track.station.slug, track.storage_key)))
        except (OSError, ValueError):
            continue
    import grp
    gid = grp.getgrnam('freo-playout').gr_gid
    PLAYLIST_ROOT.mkdir(parents=True, exist_ok=True)
    os.chown(PLAYLIST_ROOT, 0, gid)
    os.chmod(PLAYLIST_ROOT, 0o750)
    fd, name = tempfile.mkstemp(prefix='.' + slug + '.', dir=PLAYLIST_ROOT)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('\n'.join(paths) + ('\n' if paths else ''))
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temp, 0, gid)
        os.chmod(temp, 0o640)
        os.replace(temp, PLAYLIST_ROOT / (slug + '.m3u'))
    finally:
        temp.unlink(missing_ok=True)
    return len(paths)


def verify(track, storage=None):
    storage = storage or LocalMediaStorage()
    path = storage.regular_file(track.station.slug, track.storage_key)
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            checksum.update(chunk)
    if checksum.hexdigest() != track.checksum_sha256:
        raise MediaValidationError('Stored checksum mismatch')
    details = probe(path)
    if details['media_type'] != track.media_type:
        raise MediaValidationError('Stored audio type changed')
    return True


def set_enabled(track, enabled):
    require_admin()
    set_enabled_db(track, enabled)
    db.session.commit()
    refresh_playlist(track.station.slug)


def set_enabled_db(track, enabled):
    if track.ingest_status != 'accepted':
        raise ValueError('Only accepted tracks can be enabled')
    if enabled and track.decommissioned_at:
        raise ValueError('Decommissioned tracks cannot be enabled')
    track.auto_enable_pending = False
    track.enabled = bool(enabled)
