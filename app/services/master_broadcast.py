"""Station-wide broadcast intent; runtime changes belong to the root worker."""
from app.extensions import db
from app.models import Station, LiveControlCommand, ScheduleTransition
from app.services.admin_media import audit


def request_broadcast(station, enabled, revision, user):
    if type(enabled) is not bool or type(revision) is not int:
        raise ValueError('Choose ON or OFF and supply the current revision')
    db.session.refresh(station, with_for_update=True)
    if revision != station.broadcast_revision:
        raise ValueError('Broadcast control changed. Refresh and try again.')
    if enabled and (not station.enabled or station.lifecycle_state != 'ready' or not station.stream or not station.stream.enabled):
        raise ValueError('The station must be enabled and ready before broadcasting')
    if enabled:
        # Even an empty station needs worker observations of its tone output.
        from app.services.automation import state_for
        state_for(station)
    station.desired_state = 'running' if enabled else 'stopped'
    station.broadcast_revision += 1
    station.broadcast_status = 'pending'
    station.broadcast_error = ''
    if not enabled:
        # Commands saved before OFF must never resume unexpectedly at next ON.
        LiveControlCommand.query.filter_by(station_id=station.id, status='pending').update({'status': 'failed'})
        ScheduleTransition.query.filter_by(station_id=station.id).filter(
            ScheduleTransition.state.in_(('PENDING', 'PREPARING', 'FADING'))).update(
                {'state': 'FAILED', 'error': 'Master broadcast switched OFF'})
    audit('master_broadcast_requested', user_id=user.id, station_id=station.id,
          target_type='station', target_id=station.slug, summary='Master broadcast ' + ('ON' if enabled else 'OFF'))


def process_broadcast(station):
    from app.services import station_runtime as runtime
    runtime.require_root()
    with runtime.operation_lock():
        db.session.refresh(station, with_for_update=True)
        if station.broadcast_status not in ('pending', 'applying'):
            db.session.rollback()
            return
        revision = station.broadcast_revision
        running = station.desired_state == 'running' and station.enabled and station.lifecycle_state == 'ready'
        station.broadcast_status = 'applying'
        db.session.commit()
        error = ''
        try:
            runtime.service_action(station.slug, 'start' if running else 'stop')
            if running:
                runtime.wait_audio_online(station)
            elif runtime.service_action(station.slug, 'status'):
                raise RuntimeError('Station did not stop')
        except Exception as exception:
            from flask import current_app
            current_app.logger.error('Broadcast action failed: station=%s action=%s error_type=%s',
                                     station.slug, 'start' if running else 'stop', type(exception).__name__)
            error = 'Broadcast change failed. Check station status and retry.'
        db.session.refresh(station, with_for_update=True)
        if station.broadcast_revision == revision:
            station.broadcast_status = 'failed' if error else 'ready'
            station.broadcast_error = error
            audit('master_broadcast_failed' if error else 'master_broadcast_applied', station_id=station.id,
                  target_type='station', target_id=station.slug,
                  summary=error or 'Master broadcast ' + ('ON' if running else 'OFF'))
        # A newer request keeps its pending status and is applied on the next tick.
        db.session.commit()


def process_pending_broadcasts():
    for station in Station.query.filter(Station.broadcast_status.in_(('pending', 'applying')),
                                       Station.deleted_at.is_(None)).order_by(Station.id).all():
        process_broadcast(station)
