"""Dedicated non-root worker that calls the same trusted ingest service as the CLI."""
import logging
import stat
import time
from datetime import datetime, timezone

from app import create_app
from app.extensions import db
from app.models import MediaIngestJob
from app.services.analysis_queue import process_analysis, recover_analysis
from app.services.admin_media import JOB_ID, audit, staged_path, upload_root
from app.services.media import ingest, set_enabled_db, verify
from app.services.media_probe import MediaValidationError
from app.services.imaging import ingest_imaging, verify_imaging, set_asset_enabled

logger = logging.getLogger('freo.ingest')


def cleanup_staging():
    """Remove only old, unneeded UUID-named upload files; never follow links."""
    root = upload_root()
    if not root.is_dir() or root.is_symlink():
        return
    cutoff = time.time() - 86400
    for index, path in enumerate(root.iterdir()):
        if index >= 1000:
            break
        if not JOB_ID.fullmatch(path.name):
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mtime >= cutoff:
            continue
        job = db.session.get(MediaIngestJob, path.name)
        if job is None or job.status not in ('pending', 'processing'):
            path.unlink(missing_ok=True)


def process_one():
    job = (MediaIngestJob.query.filter_by(status='pending')
           .order_by(MediaIngestJob.created_at, MediaIngestJob.id)
           .with_for_update(skip_locked=True).first())
    if job is None:
        db.session.rollback()
        return False
    job.status = 'processing'
    job.started_at = datetime.now(timezone.utc)
    db.session.commit()
    path = staged_path(job.id) if job.kind in ('ingest', 'imaging') else None
    try:
        if job.kind not in ('ingest', 'verify', 'enable', 'imaging', 'img_verify', 'img_enable', 'delete'):
            raise MediaValidationError('Unsupported media operation')
        if job.kind == 'delete':
            from app.services.music_delete import delete_audio
            delete_audio(job.track);job.status='accepted'
        elif job.kind in ('img_verify', 'img_enable'):
            verify_imaging(job.imaging_asset)
            if job.kind == 'img_enable':
                set_asset_enabled(job.imaging_asset, True)
            job.status = 'accepted'
            audit('imaging_enabled' if job.kind == 'img_enable' else 'imaging_verified',
                  user_id=job.admin_user_id, station_id=job.station_id,
                  target_type='imaging_asset', target_id=job.imaging_asset.uuid,
                  summary='Imaging verified and enabled' if job.kind == 'img_enable' else 'Imaging integrity verified')
        elif job.kind in ('verify', 'enable'):
            verify(job.track)
            if job.kind == 'enable':
                set_enabled_db(job.track, True)
            job.status = 'accepted'
            audit('media_enabled' if job.kind == 'enable' else 'media_verified',
                  user_id=job.admin_user_id, station_id=job.station_id,
                  target_id=job.track.uuid, summary='File verified and enabled' if job.kind == 'enable' else 'File checksum and audio probe verified')
        elif job.kind == 'imaging':
            asset, duplicate = ingest_imaging(job.station.slug, path, job.imaging_type,
                name=job.imaging_name, cart_code=job.cart_code,
                original_filename=job.original_filename, enabled=False)
            job.status = 'duplicate' if duplicate else 'accepted'
            job.imaging_asset_id = asset.id
            audit('imaging_ingest_accepted', user_id=job.admin_user_id, station_id=job.station_id,
                  target_type='imaging_asset', target_id=asset.uuid,
                  summary='Existing imaging reused' if duplicate else 'Imaging validated and accepted disabled')
        else:
            track, duplicate = ingest(job.station.slug, path,
                                      original_filename=job.original_filename,
                                      enabled=False, update_playlist=False)
            job.status = 'duplicate' if duplicate else 'accepted'
            job.track_id = track.id
            if not duplicate:
                from app.services.audio_analysis import analyze_song,extract_artwork
                extract_artwork(track)
                # Commit ingest promptly; the idle analysis queue picks this up.
                track.analysis_status='pending'
            audit('media_ingest_accepted', user_id=job.admin_user_id, station_id=job.station_id,
                  target_id=track.uuid, summary='Existing file reused' if duplicate else 'Audio validated and accepted disabled')
    except MediaValidationError as error:
        job.status = 'rejected'
        job.error_code = {
            'Unsupported audio codec or container': 'unsupported_format',
            'Audio probe failed': 'invalid_audio',
            'Stored checksum mismatch': 'checksum_mismatch',
            'Stored audio type changed': 'media_changed',
        }.get(str(error), 'invalid_audio')
        audit('imaging_ingest_rejected' if job.kind.startswith('img') or job.kind == 'imaging' else 'media_ingest_rejected', user_id=job.admin_user_id, station_id=job.station_id,
              target_type='ingest_job', target_id=job.id, summary=str(error)[:120])
    except Exception:
        db.session.rollback()
        job = db.session.get(MediaIngestJob, job.id)
        job.status = 'error'
        job.error_code = 'processing_failed'
        audit('imaging_ingest_rejected' if job.kind.startswith('img') or job.kind == 'imaging' else 'media_ingest_rejected', user_id=job.admin_user_id, station_id=job.station_id,
              target_type='ingest_job', target_id=job.id, summary='Processing failed')
        logger.exception('Media ingest failed for job=%s station=%s', job.id, job.station_id)
    finally:
        if path:
            path.unlink(missing_ok=True)
    job.finished_at = datetime.now(timezone.utc)
    db.session.commit()
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    with app.app_context():
        # A crash can leave processing rows; re-check staged bytes after restart.
        MediaIngestJob.query.filter_by(status='processing').update({'status': 'pending'})
        db.session.commit()
        recover_analysis()
        last_cleanup = 0
        while True:
            try:
                if time.monotonic() - last_cleanup > 3600:
                    cleanup_staging()
                    last_cleanup = time.monotonic()
                if not (process_analysis(requested=True) or process_one() or process_analysis()):
                    time.sleep(2)
            except Exception:
                db.session.rollback()
                logger.exception('Ingest worker tick failed')
                time.sleep(5)


if __name__ == '__main__':
    main()
