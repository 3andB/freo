"""Manage local MP3 recordings without granting the web process file writes."""
import unicodedata

from app.extensions import db
from app.models import AdminUser, ShowRecording, Station
from app.services.admin_auth import can_access_station
from app.services.admin_media import audit
from app.services.live_sessions import now
from app.services.media_storage import LocalMediaStorage


def filename(value):
    value = unicodedata.normalize('NFC', value.strip())
    if not value.lower().endswith('.mp3'):
        value += '.mp3'
    value = value[:-4] + '.mp3'
    if (not value[:-4].strip(' .') or len(value) > 160 or
            any(c in value for c in '/\\:') or
            any(unicodedata.category(c).startswith('C') for c in value)):
        raise ValueError('Enter a name of at most 160 characters, without paths or control characters.')
    return value


def editable(row):
    return (row.status in ('complete', 'partial', 'failed') and
            not row.session.active_station_id and not row.deleted_at and
            not row.deletion_requested_at)


def process_deletions():
    # The worker also handles stopped stations. Locks serialize retries with UI
    # actions; a missing file is success after a crash between unlink and commit.
    rows = (ShowRecording.query.filter(ShowRecording.deletion_requested_at.isnot(None),
            ShowRecording.deleted_at.is_(None)).order_by(ShowRecording.deletion_requested_at)
            .limit(30).with_for_update(skip_locked=True).all())
    for row in rows:
        station = db.session.get(Station, row.station_id)
        user = db.session.get(AdminUser, row.deletion_requested_by) if row.deletion_requested_by else None
        allowed = can_access_station(user, station) and (user.role == 'ADMIN' or row.admin_user_id == user.id)
        if not allowed or row.session.active_station_id or row.status not in ('complete', 'partial', 'failed'):
            row.deletion_error = 'Deletion cancelled: access changed or show is still active.'
            row.deletion_requested_at = None
        else:
            try:
                storage = LocalMediaStorage()
                try:
                    path = storage.recording_file(station.slug, row.storage_key)
                except FileNotFoundError:
                    pass
                else:
                    path.unlink()
                row.deleted_at = now()
                row.deletion_error = None
                audit('recording_deleted', user_id=user.id, station_id=station.id,
                      target_type='show_recording', target_id=row.id, summary='Local MP3 removed')
            except (OSError, ValueError):
                row.deletion_requested_at = None
                row.deletion_error = 'Unable to delete the local MP3. Check storage permissions and retry.'
        row.revision += 1
    db.session.commit()
