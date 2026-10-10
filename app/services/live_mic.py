"""Authenticated microphone signaling and worker-owned broadcast intent."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.stations import validate_slug


def enabled():
    from flask import has_app_context
    if not has_app_context():
        # Standalone engine validation has no database application context.
        return os.environ.get('FREO_LIVE_MIC', '0') == '1'
    from app.services.installation_settings import get_setting
    return get_setting('FREO_LIVE_MIC')


def gateway(slug, action, *, timeout=2, **data):
    validate_slug(slug)
    if not enabled():
        raise ValueError('LIVE MIC audio service has not been enabled on this server.')
    request = Request('http://127.0.0.1:8091/control/' + slug,
                      data=json.dumps(dict(action=action, **data)).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(error.read(300).decode(errors='replace')) from error
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError('Microphone audio service is unavailable. Check the connection before going live.') from error


def _pending():
    from flask import current_app, has_app_context
    return current_app.extensions.setdefault('pending_microphones', set()) if has_app_context() else set()


def pending_microphones():
    return bool(_pending())


def sync_pending_microphones(states, *, exclude):
    """Renew prepared sessions between stations, using the same worker authority."""
    pending = _pending()
    for state in states:
        station = state.station
        if station.id not in pending or station.id == exclude:
            continue
        if not station.enabled or station.desired_state != 'running':
            pending.discard(station.id)
            continue
        sync_live_mic(station)


def sync_live_mic(station):
    """Called only by the automation worker. Returns whether mic owns program."""
    pending = _pending()
    identifier = getattr(station, 'id', None)
    if not enabled():
        pending.discard(identifier)
        return False
    from app.services.playout_queue import _command
    try:
        parts = _command(station.slug, 'freo_mic.state').split('|')
        if len(parts) != 3:
            pending.discard(identifier)
            return False
        token, phase, ready = parts
        engine = dict(token=token, phase=phase, ready=ready == 'true')
        try:
            session = gateway(station.slug, 'worker', token=token, engine=engine, timeout=.7)
        except ValueError:
            session = {}
        if phase == 'FAILED':
            from hashlib import sha256
            from app.extensions import db
            from app.models import AuditEvent
            from app.services.admin_media import audit
            from app.services.live_assist import return_to_schedule
            # FAILED remains latched in the engine until a new mic session.
            # Persist its acknowledgement with the fallback so a later DJ
            # session survives repeated polls and automation worker restarts.
            failure_id = sha256(token.encode()).hexdigest()
            handled = AuditEvent.query.filter_by(station_id=station.id,
                action='live_mic_failure_handled', target_id=failure_id).first()
            if handled is None:
                audit('live_mic_failure_handled', station_id=station.id,
                      target_type='mic_session', target_id=failure_id,
                      summary='Disconnected microphone session returned to Auto.')
                if station.automation.operator_mode != 'AUTO':
                    return_to_schedule(station, reason='Microphone disconnected. Returning to Auto.')
                else:
                    db.session.commit()
            if not session or session.get('token') == token:
                pending.discard(identifier)
                return False
        if not session:
            pending.discard(identifier)
            return phase in ('FADING', 'LIVE', 'RETURNING')  # Engine lease expires independently.
        pending.add(identifier)
        new_token = session['token']
        from flask import has_app_context
        if has_app_context() and session.get('owner') is not None:
            from app.models import AdminUser
            from app.extensions import db
            from app.services.live_sessions import authorized_intent
            if not authorized_intent(station, db.session.get(AdminUser, session['owner'])):
                pending.discard(identifier)
                try:
                    gateway(station.slug, 'disconnect', owner=session['owner'], token=session['token'])
                except ValueError:
                    pass
                if token == new_token and phase in ('LIVE', 'FADING'):
                    _command(station.slug, f'freo_mic.end {token} 3.000')
                return phase in ('FADING', 'LIVE', 'RETURNING')
        if token != new_token:
            if phase in ('FADING', 'LIVE', 'RETURNING'):
                return True  # Wait for old engine lease before admitting replacement.
            _command(station.slug, 'freo_mic.prepare ' + new_token)
            return False
        if session['healthy']:
            _command(station.slug, 'freo_mic.lease ' + token)
        if session['desired'] == 'LIVE' and session['healthy'] and phase == 'READY' and ready == 'true':
            _command(station.slug, f'freo_mic.take {token} {session["fade"]:.3f}')
            return True
        if session['desired'] == 'END' and phase in ('LIVE', 'FADING'):
            _command(station.slug, f'freo_mic.end {token} {session["fade"]:.3f}')
            return True
        return phase in ('FADING', 'LIVE', 'RETURNING')
    except (OSError, RuntimeError, ValueError):
        pending.discard(identifier)
        return False
