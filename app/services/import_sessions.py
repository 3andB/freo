"""Worker preparation and bounded storage for the music review workspace."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path
from flask import current_app
from app.extensions import db
from app.models import MusicImportItem, MusicImportSession
from app.services.admin_media import staged_path, upload_root
from app.services.media_probe import MediaValidationError, probe
from app.services.music_catalog import optional_int
from app.services.media import normalize

MAX_ITEMS = 500
MAX_SESSION_BYTES = 10 * 1024 ** 3
DRAFT_DAYS = 7


def utcnow():
    return datetime.now(timezone.utc)


def create_review_preview(source, target):
    from app.services.media_preview import create_preview
    create_preview(source, target)
    # Uploads belong to the web service, but previews belong to the worker.
    # Grant only the original uploader read access across that boundary.
    subprocess.run(['/usr/bin/setfacl', '-m', f'u:{source.stat().st_uid}:r--', '--', str(target)],
                   check=True, capture_output=True, timeout=10)


def stage(session, identifier, file, relative_path='', choices=None):
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError('Invalid file identifier')
    existing = db.session.get(MusicImportItem, identifier)
    if existing:
        if existing.session_id != session.id:
            raise ValueError('File identifier already used')
        return existing
    active = [i for i in session.items if i.status not in ('cancelled', 'expired')]
    if len(active) >= MAX_ITEMS:
        raise ValueError('Import up to 500 files in one workspace. Start a new import for more.')
    name = normalize(file.filename, 255)
    if not name or name in ('.', '..') or any(c in name for c in ('/', '\\')):
        raise ValueError('Choose a file with a valid filename')
    if Path(name).suffix.lower() not in ('.mp3', '.m4a', '.wav', '.flac'):
        raise ValueError('Choose MP3, M4A, WAV or FLAC audio')
    if not upload_root().is_dir():
        raise ValueError('Upload staging is unavailable')
    path = staged_path(identifier)
    # A request interrupted before its transaction committed can leave an orphan.
    # Never overwrite an unknown file; retry under a fresh client identifier.
    if path.exists():
        raise ValueError('Upload interrupted before it was saved. Retry with a fresh file identifier.')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    except FileExistsError:
        raise ValueError('Upload interrupted before it was saved. Retry with a fresh file identifier.') from None
    total, digest = 0, hashlib.sha256()
    try:
        with os.fdopen(fd, 'wb') as output:
            while chunk := file.stream.read(1024 * 1024):
                total += len(chunk)
                if total > current_app.config['MAX_MEDIA_UPLOAD_BYTES']:
                    raise ValueError('File exceeds the per-song upload limit')
                if sum(i.size_bytes for i in active) + total > MAX_SESSION_BYTES:
                    raise ValueError('This workspace has reached its 10 GB limit')
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not total:
            raise ValueError('Choose a nonempty audio file')
        item = MusicImportItem(id=identifier, session=session, original_filename=name,
                               relative_path=str(relative_path)[:1000], size_bytes=total,
                               checksum=digest.hexdigest(), choices=choices or {})
        db.session.add(item)
        session.updated_at = utcnow()
        db.session.commit()
        return item
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise


def prepare_one():
    item = (MusicImportItem.query.filter_by(status='pending')
            .order_by(MusicImportItem.created_at).with_for_update(skip_locked=True).first())
    if not item:
        db.session.rollback()
        return False
    item.status = 'preparing'
    db.session.commit()
    preview_id = None
    try:
        path = staged_path(item.id)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise MediaValidationError('Audio file is unavailable')
        if item.session.station.deleted_at or not item.session.station.enabled:
            raise MediaValidationError('Station is unavailable')
        info = probe(path)
        tags = info['tags']
        detected = dict(
            title=normalize(tags.get('title'), 200, Path(item.original_filename).stem),
            artist=normalize(tags.get('artist'), 200, 'Unknown Artist'),
            album=normalize(tags.get('album'), 200, ''),
            album_artist=normalize(tags.get('album_artist') or tags.get('albumartist'), 200, ''),
            track_number=optional_int(tags.get('track') or tags.get('tracknumber'), 1, 999),
            disc_number=optional_int(tags.get('disc') or tags.get('discnumber'), 1, 99),
            release_year=optional_int(str(tags.get('date') or tags.get('year') or '')[:4], 1000, 3000),
            duration_ms=info['duration_ms'], media_type=info['media_type'])
        art = None
        if info['has_artwork']:
            with tempfile.TemporaryDirectory(prefix='freo-import-art-') as directory:
                target = Path(directory) / 'cover.jpg'
                try:
                    result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1', '-i', str(path),
                        '-map', '0:v:0', '-frames:v', '1', '-vf', 'scale=800:800:force_original_aspect_ratio=decrease',
                        str(target)], capture_output=True, timeout=30)
                    if result.returncode == 0 and target.stat().st_size <= 2 * 1024 * 1024:
                        art = target.read_bytes()
                except (OSError, subprocess.SubprocessError):
                    pass  # Artwork is optional and must never block valid audio.
        if info['media_type'] != 'mp3':
            preview_id = str(uuid.uuid4())
            create_review_preview(path, staged_path(preview_id))
        # Use the same lock order as edits/finalization before publishing results.
        (MusicImportSession.query.filter_by(id=item.session_id).with_for_update()
         .populate_existing().one())
        db.session.refresh(item)
        # Cancellation during preparation must win over a late worker result.
        if item.status != 'preparing':
            if preview_id:
                staged_path(preview_id).unlink(missing_ok=True)
        else:
            detected['has_artwork'] = bool(art)
            item.detected, item.artwork, item.preview_id = detected, art, preview_id
            # Defaults are durable even if the browser closes during preparation.
            key = item.choices.get('group')
            if key is None:
                if item.choices.get('album_id'):
                    key = 'manual:' + str(item.choices['album_id'])
                elif detected['album']:
                    names = [' '.join(value.lower().split()) for value in
                             (detected['album_artist'] or detected['artist'], detected['album'])]
                    key = ('album:' + json.dumps(names, ensure_ascii=False, separators=(',', ':')))[:300]
                elif '/' in item.relative_path:
                    key = 'folder:' + item.relative_path.rsplit('/', 1)[0][:290]
            defaults = (item.session.groups or {}).get(key)
            if defaults and not item.choices.get('inherited_group'):
                overrides = dict(item.choices)
                inherited = {name: value for name, value in defaults.items()
                             if name not in overrides.get('file_fields', [])}
                item.choices = {**inherited, **overrides, 'inherited_group': key}
                item.revision += 1
            item.status, item.error = 'ready', ''
        db.session.commit()
    except Exception as error:
        logging.getLogger('freo.ingest').exception('Import preparation failed for item=%s session=%s', item.id, item.session_id)
        db.session.rollback()
        item = db.session.get(MusicImportItem, item.id)
        if item.status == 'preparing':
            item.status = 'failed'
            item.error = str(error)[:240] if isinstance(error, MediaValidationError) else 'Could not prepare audio. Retry preparation.'
        if preview_id:
            staged_path(preview_id).unlink(missing_ok=True)
        db.session.commit()
    return True


def cleanup_drafts():
    cutoff = utcnow() - timedelta(days=DRAFT_DAYS)
    sessions = (MusicImportSession.query.filter(MusicImportSession.updated_at < cutoff)
                .with_for_update(skip_locked=True).all())
    for session in sessions:
        for item in session.items:
            if item.status in ('pending', 'preparing', 'ready', 'failed'):
                item.status, item.error = 'expired', 'Draft expired after 7 days. Add the file again.'
    for item in MusicImportItem.query.filter(MusicImportItem.status.in_(['cancelled', 'expired', 'finalized'])).all():
        if (item.status == 'finalized' and item.job and item.job.status in ('error', 'rejected')
                and item.session.updated_at.replace(tzinfo=timezone.utc) >= cutoff):
            continue
        if item.status != 'finalized' or (item.job and item.job.status not in ('pending', 'processing')):
            staged_path(item.id).unlink(missing_ok=True)
            if item.preview_id:
                staged_path(item.preview_id).unlink(missing_ok=True)
                item.preview_id = None
            item.artwork = None
    db.session.commit()


def protected_staging_ids():
    items = MusicImportItem.query.filter(MusicImportItem.status.in_(['pending', 'preparing', 'ready', 'failed', 'finalized'])).all()
    return {identifier for item in items for identifier in (item.id, item.preview_id) if identifier}
