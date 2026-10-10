"""Read-only observations of the local Phase 2 test engine."""
import json
import stat
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from flask import Blueprint, jsonify

radio_health_blueprint = Blueprint('radio_health', __name__)
_BACKEND = 'http://127.0.0.1:8001'
_SOCKET = Path('/run/freo/liquidsoap/control.sock')
_OPENER = build_opener(ProxyHandler({}))


def _icecast_stats():
    with _OPENER.open(_BACKEND + '/status-json.xsl', timeout=2) as response:
        if response.status != 200:
            raise OSError('Icecast unavailable')
        return json.load(response)['icestats']


def _test_source_present():
    sources = _icecast_stats().get('source', [])
    if isinstance(sources, dict):
        sources = [sources]
    return any(source.get('listenurl', '').endswith('/freo-test') for source in sources)


def _stream_audio_available():
    with _OPENER.open(_BACKEND + '/freo-test', timeout=3) as response:
        return response.status == 200 and response.headers.get_content_type() == 'audio/mpeg' and bool(response.read(512))


def _socket_ready():
    return stat.S_ISSOCK(_SOCKET.stat().st_mode)


def _result(available):
    return (jsonify(status='ok' if available else 'unavailable'), 200 if available else 503)


@radio_health_blueprint.get('/health/icecast')
def icecast_health():
    try:
        return _result('server_id' in _icecast_stats())
    except (OSError, ValueError, KeyError):
        return _result(False)


@radio_health_blueprint.get('/health/playout')
def playout_health():
    try:
        return _result(_socket_ready() and _test_source_present())
    except (OSError, ValueError, KeyError):
        return _result(False)


@radio_health_blueprint.get('/health/stream')
def stream_health():
    try:
        return _result(_stream_audio_available())
    except (OSError, ValueError, KeyError):
        return _result(False)
