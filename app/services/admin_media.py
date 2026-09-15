"""Station-scoped browser media operations; filesystem writes stay in the ingest worker."""
import os
from pathlib import Path
import re
import uuid

from flask import current_app

from app.extensions import db
from app.models import AuditEvent, MediaIngestJob, Track
from app.services.media import normalize
from app.services.media_probe import MediaValidationError

UPLOAD_ROOT = Path('/var/lib/freo/uploads')
MAX_WEB_UPLOAD_BYTES = 128 * 1024 * 1024
JOB_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def upload_root():
    return Path(current_app.config.get('FREO_UPLOAD_ROOT', UPLOAD_ROOT))


def staged_path(job_id):
    if not JOB_ID.fullmatch(job_id):
        raise ValueError('Invalid ingest job')
    root = upload_root()
    if root.is_symlink():
        raise ValueError('Upload staging directory is invalid')
    return root / job_id


def audit(action, *, user_id=None, station_id=None, target_type='track', target_id=None, summary=''):
    event = AuditEvent(admin_user_id=user_id, station_id=station_id,
                       action=action, target_type=target_type, target_id=target_id,
                       summary=summary[:240])
    db.session.add(event)
    return event


def stage_upload(station, user, file, *, kind='ingest', imaging_type=None, imaging_name=None, cart_code=None, import_metadata=None):
    if kind not in ('ingest', 'imaging'):
        raise MediaValidationError('Unsupported upload kind')
    if kind == 'imaging':
        from app.services.imaging import clean_type, clean_code
        imaging_type = clean_type(imaging_type)
        cart_code = clean_code(cart_code)
        imaging_name = normalize(imaging_name, 200) if imaging_name else None
    original = normalize(file.filename, 255)
    if original in ('', '.', '..') or any(ch in original for ch in ('/', '\\')):
        raise MediaValidationError('Choose a file with a valid filename')
    root = upload_root()
    if not root.is_dir() or root.is_symlink():
        raise MediaValidationError('Upload staging is unavailable')
    job_id = str(uuid.uuid4())
    path = staged_path(job_id)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    total = 0
    try:
        with os.fdopen(fd, 'wb') as output:
            while chunk := file.stream.read(1024 * 1024):
                total += len(chunk)
                if total > current_app.config.get('MAX_MEDIA_UPLOAD_BYTES', MAX_WEB_UPLOAD_BYTES):
                    raise MediaValidationError('File exceeds the web upload size limit')
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total == 0:
            raise MediaValidationError('Choose a nonempty audio file')
        job = MediaIngestJob(id=job_id, station_id=station.id, admin_user_id=user.id,
                             original_filename=original, status='pending', kind=kind,
                             imaging_type=imaging_type, imaging_name=imaging_name, cart_code=cart_code, import_metadata=import_metadata or {})
        db.session.add(job)
        audit('imaging_upload_started' if kind == 'imaging' else 'media_upload_started', user_id=user.id, station_id=station.id,
              target_type='ingest_job', target_id=job_id, summary='Upload staged for validation')
        db.session.commit()
        return job
    except Exception:
        db.session.rollback()
        path.unlink(missing_ok=True)
        raise


def track_for_station(station, track_uuid):
    if not isinstance(track_uuid, str) or len(track_uuid) != 36:
        return None
    return Track.query.filter_by(station_id=station.id, uuid=track_uuid).first()
