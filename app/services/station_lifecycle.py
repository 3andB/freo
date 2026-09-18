"""Retryable provisioning; only the root CLI/worker executes runtime changes."""
from datetime import datetime, timezone

from app.extensions import db
from app.models import Station, StationDomain, MediaIngestJob, LiveControlCommand, SelectionDecision
from app.services.admin_media import audit
from app.services.stations import allocation_lock
from app.services import station_runtime as runtime


def process_station(station):
    runtime.require_root()
    # Serialize CLI and worker operations across config files and reloads.
    with runtime.operation_lock():
        allocation_lock()
        db.session.refresh(station)
        state = station.lifecycle_state
        if state not in ('pending_create', 'create_failed', 'pending_delete', 'delete_failed'):
            db.session.rollback()
            return station
        deleting = state in ('pending_delete', 'delete_failed')
        # Release database locks before slow engine validation or service reloads.
        # Other channels must be able to keep refilling their audio queues.
        db.session.commit()
        try:
            if deleting:
                # Files and historical identities deliberately outlive the runtime.
                runtime.remove(station)
                allocation_lock()
                db.session.refresh(station)
                MediaIngestJob.query.filter_by(station_id=station.id, status='pending').update(
                    {'status': 'rejected', 'error_code': 'station_deleted'})
                LiveControlCommand.query.filter_by(station_id=station.id, status='pending').update(
                    {'status': 'failed'})
                SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
                    SelectionDecision.status.in_(('selected', 'submitting', 'queued'))).update(
                    {'status': 'failed', 'reason': 'station_deleted'})
                # Release host claims only once deletion succeeds. Re-adding a
                # hostname requires a fresh DNS token and verification.
                StationDomain.query.filter_by(station_id=station.id).delete(synchronize_session='fetch')
                station.deleted_at = datetime.now(timezone.utc)
                station.lifecycle_state = 'deleted'
                station.enabled = False
                station.desired_state = 'stopped'
                station.stream.enabled = False
            else:
                from app.services.media import _prepare_dirs
                from app.services.media_storage import LocalMediaStorage
                _prepare_dirs(LocalMediaStorage(), station.slug)
                runtime.run_checked(['/bin/bash', str(runtime.SOURCE / 'scripts/media-web-access.sh'), str(LocalMediaStorage().root)])
                runtime.render(station)
                allocation_lock()
                db.session.refresh(station)
                if station.lifecycle_state == 'pending_delete':
                    db.session.commit()
                    return station
                station.lifecycle_state = 'ready'
            station.lifecycle_error = ''
            audit('station_deleted' if deleting else 'station_provisioned',
                  station_id=station.id, target_type='station', target_id=station.slug,
                  summary='Runtime removed; media and history retained' if deleting else 'Station ready')
            db.session.commit()
        except Exception:
            db.session.rollback()
            allocation_lock()
            db.session.refresh(station)
            if not deleting and station.lifecycle_state == 'pending_delete':
                db.session.commit()
                return station
            station.lifecycle_state = 'delete_failed' if deleting else 'create_failed'
            # Never expose subprocess output: it may contain source credentials.
            station.lifecycle_error = 'Provisioning failed. Check the provisioning service journal, then retry.'
            db.session.commit()
            raise
    return station


def process_pending():
    runtime.require_root()
    from app.services.master_broadcast import process_pending_broadcasts
    process_pending_broadcasts()
    ids = [row.id for row in Station.query.filter(
        Station.lifecycle_state.in_(('pending_create', 'pending_delete'))).order_by(Station.id)]
    failures = []
    for identifier in ids:
        try:
            process_station(db.session.get(Station, identifier))
        except Exception as error:
            failures.append(identifier)
            from flask import current_app
            current_app.logger.error('Station provisioning failed: id=%s error_type=%s', identifier, type(error).__name__)
    from app.services.station_audio import process_pending_audio
    failures.extend(process_pending_audio())
    if failures:
        raise RuntimeError('One or more station operations failed')


def retry(station):
    allocation_lock()
    db.session.refresh(station)
    if station.lifecycle_state not in ('create_failed', 'delete_failed'):
        raise ValueError('This station has no failed operation to retry')
    station.lifecycle_state = 'pending_delete' if station.lifecycle_state == 'delete_failed' else 'pending_create'
    station.lifecycle_error = ''
    db.session.commit()
