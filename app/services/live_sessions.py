"""Ownership and history projected from the existing mixer/microphone engine.

This service never selects a program source. Ending a show uses the existing
microphone END and return_to_schedule paths, exclusively from the worker.
"""
from datetime import datetime, timezone
import json
import math
import shutil
import subprocess
import uuid

from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import LiveSession, ShowRecording, LiveQueueSnapshot
from app.services.admin_auth import can_control_playout


def now():
    return datetime.now(timezone.utc)


def utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc) if value else None


def iso(value):
    return utc(value).isoformat() if value else None


def active_session(station):
    return LiveSession.query.filter_by(active_station_id=station.id).first()


def require_owner(station, user, *, allow_admin_end=False):
    if not can_control_playout(user, station):
        raise ValueError('Station access is no longer available.')
    show = active_session(station)
    if show and show.admin_user_id != user.id and not (allow_admin_end and user.role == 'ADMIN'):
        raise ValueError('This show is controlled by another DJ. Wait for automation to resume.')
    return show


def claim(station, user, record=False):
    from app.services.stations import allocation_lock
    allocation_lock()
    show = require_owner(station, user)
    if show:
        if show.end_requested:
            raise ValueError('Wait for the current show to return to automation.')
        return show
    show = LiveSession(station_id=station.id, active_station_id=station.id,
                       admin_user_id=user.id, dj_name=user.username or user.email,
                       record_requested=record)
    try:
        with db.session.begin_nested():
            db.session.add(show)
            db.session.flush()
            if record:
                key = uuid.uuid4().hex
                db.session.add(ShowRecording(id=key, session=show, station_id=station.id,
                    admin_user_id=user.id, storage_key=key+'.mp3'))
                db.session.flush()
    except IntegrityError as error:
        raise ValueError('Another DJ has claimed this station. Refresh the booth.') from error
    return show


def authorized_intent(station, user):
    if not can_control_playout(user, station):
        return False
    show = active_session(station)
    return not show or (show.admin_user_id == user.id and not show.end_requested)


def authorized_command(station, command):
    if command.admin_user_id is not None:
        return authorized_intent(station, command.operator)
    # AUTO_CUE creates worker-owned commands. Its durable playback binding is
    # required; an orphaned human command must never acquire system privileges.
    from app.models import CuePlayback
    target = command.target_decision
    if (command.action != 'DECK_LOAD' or target is None or
            target.selection_method != 'cue_auto' or target.station_id != station.id):
        return False
    binding = db.session.get(CuePlayback, target.id)
    if not binding or binding.station_id != station.id:
        return False
    show = active_session(station)
    # Generation/order validation stays in process_deck_command, which also
    # handles reselecting a changed Cue after worker recovery.
    return not show or authorized_intent(station, show.operator)


def describe(station):
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    observation = snapshot.show_observation if snapshot else None
    fresh = bool(observation and observation.get('observed_at') and
        (now()-datetime.fromisoformat(observation['observed_at'])).total_seconds() < 10)
    show = active_session(station)
    last = show or LiveSession.query.filter_by(station_id=station.id).order_by(LiveSession.created_at.desc()).first()
    source = observation.get('source', 'UNKNOWN') if fresh else 'UNKNOWN'
    recording = last.recording if last else None
    return dict(source=source, fresh=fresh,
        session_id=show.id if show else None, owner_id=show.admin_user_id if show else None,
        dj=show.dj_name if show else None, started_at=iso(show.started_at) if show else None,
        ended_at=iso(last.ended_at) if last else None,
        end_reason=last.end_reason if last else None,
        returning=bool(show and show.end_requested) or source == 'RETURNING',
        recording=dict(status=recording.status, error=recording.error) if recording else None)


def engine_observation(slug):
    from app.services.playout_queue import _command
    try:
        fields = _command(slug, 'freo_show.state').split('|')
    except (RuntimeError, ValueError):
        fields = []
    if len(fields) != 3:
        return legacy_observation(slug)
    if fields[0] not in ('AUTO', 'DJ', 'MIC', 'RETURNING'):
        raise ValueError('Show observations unavailable on this engine')
    times = [float(value) for value in fields[1:]]
    if any(not math.isfinite(value) or value < 0 for value in times):
        raise ValueError('Invalid show timestamp')
    return dict(source=fields[0], started_at=times[0], ended_at=times[1], observed_at=now().isoformat())


def legacy_observation(slug):
    """Old templates retain booth operation; timestamps are observation times."""
    from app.services.playout_queue import mixer_state, _command
    from app.services.live_mic import enabled
    mixer = mixer_state(slug)
    source = 'DJ' if mixer['mode'] == 'DJ_BOOTH' and not mixer.get('auto_standby', False) else 'AUTO'
    if mixer['mode'] == 'AUTO' and (mixer.get('transition') or {}).get('progress', 1) < 1:
        source = 'RETURNING'
    if enabled():
        parts = _command(slug, 'freo_mic.state').split('|')
        if len(parts) != 3:
            raise ValueError('Microphone observation unavailable')
        if parts[1] in ('FADING', 'LIVE', 'RETURNING'):
            source = 'RETURNING' if parts[1] == 'RETURNING' else 'MIC'
    return dict(source=source, started_at=0, ended_at=0, observed_at=now().isoformat(), legacy=True)


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc) if value else None


def finalize(station, recording, *, partial=False):
    from app.services.media_storage import LocalMediaStorage
    try:
        path = LocalMediaStorage().recording_file(station.slug, recording.storage_key)
        result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'json', str(path)], check=True, capture_output=True, timeout=3)
        duration = float(json.loads(result.stdout)['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Empty recording')
        recording.duration_ms = round(duration * 1000)
        recording.file_size_bytes = path.stat().st_size
        recording.status = 'partial' if partial or recording.error else 'complete'
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        recording.status = 'failed'
        recording.error = recording.error or 'Recording is missing or could not be validated.'


def reconcile_recording(station, show, observation, identity_changed=False):
    from app.services.playout_queue import _command
    from app.services.media_storage import LocalMediaStorage
    recording = show.recording
    if not recording or recording.status in ('complete', 'partial', 'failed'):
        return
    if identity_changed:
        recording.error = 'Playout restarted; recording was interrupted.'
        finalize(station, recording, partial=True)
        return
    try:
        fields = _command(station.slug, 'freo_record.state').split('|')
        if len(fields) != 5:
            raise ValueError('Recording is not supported by this engine.')
        key, phase, start, end, error = fields
        if recording.status == 'pending' and key != recording.id:
            if not show.active_station_id:
                raise ValueError('Show ended before recording started.')
            if phase in ('RECORDING', 'ARMED', 'STOPPING'):
                return  # Let the previous output close before arming a new file.
            if show.started_at:
                # Never silently start a late recording after a worker outage.
                raise ValueError('Recording could not be armed before the show began.')
            path = LocalMediaStorage().recording_path(station.slug, recording.storage_key)
            if not path.parent.is_dir() or path.exists():
                raise ValueError('Recording storage is unavailable or the file already exists.')
            if shutil.disk_usage(path.parent).free < 256 * 1024 * 1024:
                raise ValueError('Recording storage has less than 256 MiB free.')
            _command(station.slug, 'freo_record.arm ' + recording.id)
            return
        if key != recording.id:
            recording.error = 'Recording closure observation was interrupted.'
            finalize(station, recording, partial=True)
            return
        recording.started_at = timestamp(float(start))
        recording.ended_at = timestamp(float(end))
        if phase in ('ARMED', 'RECORDING'):
            if show.active_station_id and (not show.end_requested or phase == 'RECORDING'):
                path = LocalMediaStorage().recording_path(station.slug, recording.storage_key)
                if shutil.disk_usage(path.parent).free < 256 * 1024 * 1024:
                    recording.error = 'Recording stopped: less than 256 MiB free.'
                    _command(station.slug, 'freo_record.stop ' + recording.id)
                else:
                    _command(station.slug, 'freo_record.lease ' + recording.id)
            elif phase == 'ARMED' or not show.active_station_id:
                _command(station.slug, 'freo_record.stop ' + recording.id)
            if phase == 'RECORDING':
                recording.status = 'recording'
        elif phase == 'STOPPING':
            recording.status = 'finalizing'
        elif phase in ('CLOSED', 'ERROR'):
            recording.error = recording.error or (error if error else None)
            recording.status = 'finalizing'
            finalize(station, recording, partial=phase == 'ERROR' or bool(recording.error))
    except (OSError, RuntimeError, ValueError) as error:
        # Socket loss may be temporary; lease closure happens in the engine.
        if recording.status != 'pending':
            recording.error = 'Recorder observation interrupted; awaiting reconciliation.'
        else:
            recording.status = 'failed'
            recording.error = str(error)[:160] if isinstance(error, ValueError) else 'Recorder unavailable. Check worker and storage configuration.'


def sync(station):
    """Worker-only reconciliation, before control and after queue observation."""
    from app.services.playout_queue import socket_identity, _command
    show = active_session(station)
    if show and not can_control_playout(show.operator, station):
        show.end_requested = True
        show.end_reason = 'permission_revoked'
        from app.services.live_assist import return_to_schedule
        if station.automation and station.automation.operator_mode != 'AUTO':
            return_to_schedule(station, reason='DJ access revoked. Returning to automation.')
        db.session.commit()
    try:
        observation = engine_observation(station.slug)
        identity = socket_identity(station.slug)
    except (OSError, RuntimeError, ValueError):
        # Do not invent automation return or an exact end time on loss of contact.
        if show and (not station.enabled or station.desired_state != 'running'):
            show.end_reason = 'station_stopped_unobserved'
            if show.recording and show.recording.status not in ('complete', 'partial', 'failed'):
                # Only finalize once the old engine socket has disappeared.
                try:
                    socket_identity(station.slug)
                except (OSError, RuntimeError, ValueError):
                    show.active_station_id = None
                    show.recording.error = 'Station stopped; recording was interrupted.'
                    finalize(station, show.recording, partial=True)
            else:
                show.active_station_id = None
            db.session.commit()
        return
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    if snapshot:
        snapshot.show_observation = observation
    if show:
        changed = bool(show.engine_identity and show.engine_identity != identity)
        show.engine_identity = identity
        if not can_control_playout(show.operator, station):
            show.end_requested = True
            show.end_reason = 'permission_revoked'
        if not station.enabled or station.desired_state != 'running':
            show.end_requested = True
            show.end_reason = 'station_stopped'
        if not show.started_at and (now()-utc(show.created_at)).total_seconds() > 300:
            show.end_requested = True
            show.end_reason = 'unused_claim_expired'
        if changed:
            show.active_station_id = None
            show.end_reason = 'playout_restarted'
        elif observation['source'] != 'AUTO':
            if not show.started_at:
                start = now() if observation.get('legacy') else timestamp(observation['started_at'])
                if start:
                    show.started_at = max(start, utc(show.created_at))
        elif show.started_at or show.end_requested or observation['started_at'] >= utc(show.created_at).timestamp():
            if not show.started_at and observation['started_at']:
                show.started_at = timestamp(observation['started_at'])
            end = now() if observation.get('legacy') else timestamp(observation['ended_at'])
            if show.started_at and end and end >= utc(show.started_at):
                show.ended_at = end
            show.active_station_id = None
            show.end_reason = show.end_reason or 'automation_return'
        # Arm before any microphone/deck commands are sent on this tick.
        reconcile_recording(station, show, observation, changed)
        if show.end_requested or changed:
            from app.services.live_mic import enabled, gateway
            if enabled():
                try:
                    mic = gateway(station.slug, 'status')
                    if mic.get('token') and mic.get('owner'):
                        gateway(station.slug, 'disconnect', token=mic['token'], owner=mic['owner'])
                except ValueError:
                    pass  # The existing engine microphone lease is still bounded.
            from app.services.live_assist import return_to_schedule
            if station.automation and station.automation.operator_mode != 'AUTO':
                return_to_schedule(station, reason='Show ended. Returning to automation.')
    # Retry file closure after the session itself has returned to AUTO.
    for recording in ShowRecording.query.filter_by(station_id=station.id).filter(
            ShowRecording.status.in_(('pending','recording','finalizing'))).all():
        if not show or recording.session_id != show.id:
            reconcile_recording(station, recording.session, observation,
                bool(recording.session.engine_identity and recording.session.engine_identity != identity))
    db.session.commit()
