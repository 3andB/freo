"""Authenticated microphone signaling and worker-owned broadcast intent."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.stations import validate_slug


def enabled():
    return os.environ.get('FREO_LIVE_MIC', '0') == '1'


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


def sync_live_mic(station):
    """Called only by the automation worker. Returns whether mic owns program."""
    if not enabled():
        return False
    from app.services.playout_queue import _command
    try:
        parts = _command(station.slug, 'freo_mic.state').split('|')
        if len(parts) != 3:
            return False
        token, phase, ready = parts
        engine = dict(token=token, phase=phase, ready=ready == 'true')
        try:
            session = gateway(station.slug, 'worker', token=token, engine=engine, timeout=.7)
        except ValueError:
            session = {}
        if phase == 'FAILED':
            from app.services.live_assist import return_to_schedule
            if station.automation.operator_mode != 'AUTO':
                return_to_schedule(station, reason='Microphone disconnected. Returning to Auto.')
            if not session or session.get('token') == token:
                return False
        if not session:
            return phase in ('FADING', 'LIVE', 'RETURNING')  # Engine lease expires independently.
        new_token = session['token']
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
        return False
