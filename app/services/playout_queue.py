"""Narrow Liquidsoap socket adapter: queue depth and approved request push only."""
from pathlib import Path
import re
import socket

from app.services.media_storage import LocalMediaStorage
from app.services.stations import validate_slug

SOCKET_ROOT = Path('/run/freo/playout')
REQUEST_ID = re.compile(r'^\d+$')


def _command(slug, command):
    validate_slug(slug)
    if '\n' in command or '\r' in command or len(command) > 1024:
        raise ValueError('Invalid Liquidsoap command')
    media_root = re.escape(str(LocalMediaStorage().root))
    push_pattern = rf'freo_queue\.push annotate:freo_decision=[1-9][0-9]*:{media_root}/{re.escape(slug)}/originals/[0-9a-f]{{32}}\.mp3'
    if command not in ('freo_queue.queue', 'request.on_air') and not re.fullmatch(push_pattern, command):
        raise ValueError('Liquidsoap command is not allowlisted')
    path = SOCKET_ROOT / slug / 'control.sock'
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(8)
        connection.connect(str(path))
        connection.sendall((command + '\n').encode('ascii'))
        response = bytearray()
        while b'END\r\n' not in response:
            chunk = connection.recv(4096)
            if not chunk or len(response) + len(chunk) > 65536:
                raise RuntimeError('Invalid Liquidsoap response')
            response.extend(chunk)
    body = response.split(b'END\r\n', 1)[0].decode('utf-8', errors='replace').strip()
    if body.startswith('ERROR'):
        raise RuntimeError('Liquidsoap queue operation failed')
    return body


def queue_depth(slug):
    return len(queued_ids(slug))


def queued_ids(slug):
    body = _command(slug, 'freo_queue.queue')
    if not body:
        return set()
    ids = body.split()
    if not all(REQUEST_ID.fullmatch(value) for value in ids):
        raise RuntimeError('Invalid Liquidsoap queue state')
    return {int(value) for value in ids}


def active_ids(slug):
    body = _command(slug, 'request.on_air')
    if not body:
        return set()
    ids = body.split()
    if not all(REQUEST_ID.fullmatch(value) for value in ids):
        raise RuntimeError('Invalid Liquidsoap active request state')
    return {int(value) for value in ids}


def socket_identity(slug):
    validate_slug(slug)
    info = (SOCKET_ROOT / slug / 'control.sock').stat()
    return f'{info.st_dev}:{info.st_ino}'


def push_decision(decision, storage=None):
    """Build the URI solely from a committed, approved station Track record."""
    track = decision.track
    slug = decision.station.slug
    if track is None or track.station_id != decision.station_id or not track.enabled or track.ingest_status != 'accepted':
        raise ValueError('Decision track is not approved for this station')
    if not isinstance(decision.id, int) or decision.id <= 0:
        raise ValueError('Decision must be committed before queueing')
    storage = storage or LocalMediaStorage()
    path = storage.regular_file(slug, track.storage_key)
    command = f'freo_queue.push annotate:freo_decision={decision.id}:{path}'
    response = _command(slug, command)
    if not REQUEST_ID.fullmatch(response):
        raise RuntimeError('Liquidsoap did not accept the request')
    return int(response)
