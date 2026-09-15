"""Narrow Liquidsoap socket adapter: queue depth and approved request push only."""
from pathlib import Path
import re
import socket
import unicodedata

from app.services.media_storage import LocalMediaStorage
from app.services.stations import validate_slug

SOCKET_ROOT = Path('/run/freo/playout')
REQUEST_ID = re.compile(r'^\d+$')


def _metadata(value, fallback):
    """Reduce untrusted labels to an ASCII subset safe in Liquidsoap's annotate URI."""
    ascii_value = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'[^A-Za-z0-9 ._-]', ' ', ascii_value)
    return ' '.join(cleaned.split())[:120] or fallback


def _command(slug, command):
    validate_slug(slug)
    if '\n' in command or '\r' in command or len(command) > 1024:
        raise ValueError('Invalid Liquidsoap command')
    media_root = re.escape(str(LocalMediaStorage().root))
    music_pattern = rf'freo_queue\.push annotate:freo_decision=[1-9][0-9]*:{media_root}/{re.escape(slug)}/originals/[0-9a-f]{{32}}\.mp3'
    imaging_pattern = rf'freo_queue\.push annotate:freo_decision=[1-9][0-9]*,title="[A-Za-z0-9 ._-]{{1,120}}",artist="[A-Za-z0-9 ._-]{{1,120}}":{media_root}/{re.escape(slug)}/imaging/[0-9a-f]{{32}}\.mp3'
    if command not in ('freo_queue.queue', 'request.on_air', 'freo_queue.skip', 'freo_queue.flush_and_skip', 'freo_program.rms') and not re.fullmatch(r'request.metadata [0-9]+', command) and not (re.fullmatch(music_pattern, command) or re.fullmatch(imaging_pattern, command)):
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
    return set(queued_order(slug))


def queued_order(slug):
    body = _command(slug, 'freo_queue.queue')
    if not body:
        return []
    ids = body.split()
    if not all(REQUEST_ID.fullmatch(value) for value in ids):
        raise RuntimeError('Invalid Liquidsoap queue state')
    return [int(value) for value in ids]


def request_decision_id(slug, request_id):
    if not isinstance(request_id, int) or request_id < 0:
        raise ValueError('Invalid request ID')
    body = _command(slug, f'request.metadata {request_id}')
    match = re.search(r'(?m)^freo_decision="([1-9][0-9]*)"$', body)
    return int(match.group(1)) if match else None


def skip_current(slug):
    return _command(slug, 'freo_queue.skip')


def interrupt_for_event(slug):
    """Worker-only fixed operation: clear stale lookahead and advance current."""
    return _command(slug, 'freo_queue.flush_and_skip')


def program_rms(slug):
    value = float(_command(slug, 'freo_program.rms'))
    if not 0.0 <= value <= 1.0:
        raise RuntimeError('Invalid program RMS')
    return value


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
    """Build the URI solely from a committed, approved station playable."""
    track = decision.track
    imaging = decision.imaging_asset
    slug = decision.station.slug
    if (track is None) == (imaging is None):
        raise ValueError('Decision must target exactly one playable')
    if not isinstance(decision.id, int) or decision.id <= 0:
        raise ValueError('Decision must be committed before queueing')
    storage = storage or LocalMediaStorage()
    if track:
        if track.station_id != decision.station_id or not track.enabled or track.ingest_status != 'accepted':
            raise ValueError('Decision track is not approved for this station')
        path = storage.regular_file(slug, track.storage_key)
    else:
        if imaging.station_id != decision.station_id or not imaging.enabled or imaging.ingest_status != 'accepted' or imaging.decommissioned_at:
            raise ValueError('Decision imaging is not approved for this station')
        path = storage.imaging_file(slug, imaging.storage_key)
    if imaging:
        title = _metadata(imaging.name, imaging.asset_type.replace('_', ' ').title())
        artist = _metadata(decision.station.name, slug)
        command = f'freo_queue.push annotate:freo_decision={decision.id},title="{title}",artist="{artist}":{path}'
    else:
        command = f'freo_queue.push annotate:freo_decision={decision.id}:{path}'
    response = _command(slug, command)
    if not REQUEST_ID.fullmatch(response):
        raise RuntimeError('Liquidsoap did not accept the request')
    return int(response)
