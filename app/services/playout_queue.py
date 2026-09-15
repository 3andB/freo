"""Narrow Liquidsoap socket adapter: queue depth and approved request push only."""
from app.services.availability import playable
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
    music_pattern = rf'(?:freo_queue\.(?:push|insert)|freo_(?:a|b|cart)\.push) annotate:freo_decision=(?P<decision>[1-9][0-9]*)(?:,freo_gain="-?[0-9]{{1,2}}\.[0-9]{{3}} dB")?:{media_root}/(?P<owner>[a-z0-9](?:[a-z0-9-]{{0,62}}[a-z0-9])?)/originals/(?P<key>[0-9a-f]{{32}}\.mp3)'
    imaging_pattern = rf'(?:freo_queue\.(?:push|insert)|freo_(?:a|b|cart)\.push) annotate:freo_decision=[1-9][0-9]*,title="[A-Za-z0-9 ._-]{{1,120}}",artist="[A-Za-z0-9 ._-]{{1,120}}":{media_root}/{re.escape(slug)}/imaging/[0-9a-f]{{32}}\.mp3'
    if command not in ('freo_queue.queue', 'request.on_air', 'freo_queue.skip', 'freo_queue.flush_and_skip', 'freo_program.rms', 'freo_program.current', 'freo_deck.requests') and not re.fullmatch(r'(?:freo_deck\.(?:take|fade)_[ab](?: (?:[0-9]\.[0-9]{3}|10\.000))?|freo_deck\.(?:pause|clear|future)_[ab]|request.metadata [0-9]+|freo_(?:a|b|cart)\.queue|freo_mixer\.(?:state|fade_a|clear_future|mode (?:AUTO|DJ_BOOTH)|crossfader (?:0\.[0-9]{3}|1\.000)|(?:a_play|b_play) (?:true|false)|cart_mode (?:OVER|TAKEOVER)|duck (?:0\.[0-9]{3}|1\.000)))', command) and not (re.fullmatch(music_pattern, command) or re.fullmatch(imaging_pattern, command)):
        raise ValueError('Liquidsoap command is not allowlisted')
    music = re.fullmatch(music_pattern, command)
    if music and music['owner'] != slug:
        from app.extensions import db
        from app.models import SelectionDecision
        row = db.session.get(SelectionDecision, int(music['decision']))
        if (row is None or row.station.slug != slug or not row.station.enabled or
                row.station.deleted_at or not row.track or not playable(row.track, row.station_id) or
                row.track.station.slug != music['owner'] or row.track.storage_key != music['key']):
            raise ValueError('Shared audio is not approved for this station decision')
        LocalMediaStorage().regular_file(music['owner'], music['key'])
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
    try:
        body += ' ' + _command(slug, 'freo_deck.requests')
    except (OSError,RuntimeError,ValueError):
        pass  # Older engines do not expose prepared deck requests.
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
    if not decision.station.enabled or decision.station.deleted_at or decision.station.lifecycle_state in ('pending_delete', 'delete_failed'):
        raise ValueError('Station is unavailable')
    from app.services.stations import allocation_lock
    from app.services.availability import tracks_for
    from app.models import Station
    allocation_lock()
    # Serialize handoff with sharing/deletion changes, and query current access
    # rather than trusting an ORM object cached by a long-lived worker.
    if not Station.query.filter_by(id=decision.station_id, enabled=True, deleted_at=None).filter(
            ~Station.lifecycle_state.in_(('pending_delete', 'delete_failed'))).first():
        raise ValueError('Station is unavailable')
    track = decision.track
    if track and not tracks_for(decision.station_id).filter_by(id=track.id, enabled=True,
            ingest_status='accepted', decommissioned_at=None).first():
        raise ValueError('Decision track is not approved for this station')
    imaging = decision.imaging_asset
    slug = decision.station.slug
    if (track is None) == (imaging is None):
        raise ValueError('Decision must target exactly one playable')
    if not isinstance(decision.id, int) or decision.id <= 0:
        raise ValueError('Decision must be committed before queueing')
    storage = storage or LocalMediaStorage()
    if track:
        if not playable(track, decision.station_id):
            raise ValueError('Decision track is not approved for this station')
        path = storage.regular_file(track.station.slug, track.storage_key)
    else:
        if imaging.station_id != decision.station_id or not imaging.enabled or imaging.ingest_status != 'accepted' or imaging.decommissioned_at:
            raise ValueError('Decision imaging is not approved for this station')
        path = storage.imaging_file(slug, imaging.storage_key)
    bus = getattr(decision, 'playback_bus', None) or 'A'
    queue_name = {'A':'freo_queue','B':'freo_b','CART':'freo_cart'}.get(bus)
    if bus=='A' and decision.reason in ('deck_load','deck_repeat'):
        queue_name='freo_a'
    if not queue_name:
        raise ValueError('Invalid broadcast bus')
    occurrence = getattr(decision, 'timed_event_occurrence', None)
    item = getattr(decision, 'block_item_execution', None)
    if item and item.execution.timed_event_occurrence:
        occurrence = item.execution.timed_event_occurrence
    operation = 'insert' if queue_name == 'freo_queue' and occurrence and occurrence.event.timing_mode == 'SOFT' else 'push'
    if imaging:
        title = _metadata(imaging.name, imaging.asset_type.replace('_', ' ').title())
        artist = _metadata(decision.station.name, slug)
        command = f'{queue_name}.{operation} annotate:freo_decision={decision.id},title="{title}",artist="{artist}":{path}'
    else:
        from app.services.loudness import gain_for
        gain = gain_for(track, decision.station)['db']
        command = f'{queue_name}.{operation} annotate:freo_decision={decision.id},freo_gain="{gain:.3f} dB":{path}'
    response = _command(slug, command)
    if not REQUEST_ID.fullmatch(response):
        raise RuntimeError('Liquidsoap did not accept the request')
    return int(response)


def program_decision_id(slug):
    """Final-output metadata, after crossfade buffering; None means no managed audio."""
    body = _command(slug, "freo_program.current")
    if not body:
        return None
    if not REQUEST_ID.fullmatch(body):
        raise RuntimeError("Invalid program decision")
    return int(body)


def mixer_state(slug):
    import math
    parts = _command(slug, 'freo_mixer.state').split('|')
    if len(parts) not in (9,13,16) or parts[0] not in ('AUTO','DJ_BOOTH') or any(value not in ('true','false') for value in parts[2:4]):
        raise RuntimeError('Invalid mixer state')
    numeric = [float(parts[index]) for index in (1,7,8)]
    if not all(math.isfinite(value) for value in numeric) or not 0 <= numeric[0] <= 1:
        raise RuntimeError('Invalid mixer levels')
    if any(value and not REQUEST_ID.fullmatch(value) for value in parts[4:7]):
        raise RuntimeError('Invalid mixer identity')
    transition = {}
    if len(parts) >= 13:
        levels = [float(value) for value in parts[10:13]]
        if parts[9] not in ('','A','B') or not all(math.isfinite(value) and 0 <= value <= 1 for value in levels):
            raise RuntimeError('Invalid deck transition')
        transition = dict(incoming=parts[9] or None,progress=levels[0],a_gain=levels[1],b_gain=levels[2])
    extra={}
    if len(parts)==16:
        gain=float(parts[15])
        if parts[13] not in ('true','false') or (parts[14] and not REQUEST_ID.fullmatch(parts[14])) or not math.isfinite(gain) or not 0<=gain<=1:
            raise RuntimeError('Invalid Auto source state')
        extra=dict(auto_standby=parts[13]=='true',auto_id=int(parts[14]) if parts[14] else None,auto_gain=gain)
    return dict(**extra,transition=transition,mode=parts[0],crossfader=numeric[0],a_playing=parts[2]=='true',b_playing=parts[3]=='true',
                a_id=int(parts[4]) if parts[4] else None,b_id=int(parts[5]) if parts[5] else None,
                cart_id=int(parts[6]) if parts[6] else None,a_elapsed=max(0,numeric[1]),b_elapsed=max(0,numeric[2]))


def sync_mixer(station):
    state = station.automation
    observed = mixer_state(station.slug)
    _command(station.slug, 'freo_mixer.mode ' + state.operator_mode)
    return observed


def channel_queue(slug, bus):
    name = {'A':'freo_a','B':'freo_b','CART':'freo_cart'}.get(bus)
    if not name:
        raise ValueError('Invalid broadcast bus')
    value = _command(slug, name + '.queue')
    if any(not REQUEST_ID.fullmatch(part) for part in value.split()):
        raise RuntimeError('Invalid channel queue')
    return [int(part) for part in value.split()]


def prepare_cart(decision):
    if decision.cart_mode not in ('OVER','TAKEOVER') or not 0 <= decision.duck_percent <= 100:
        raise ValueError('Invalid cart behavior')
    _command(decision.station.slug, 'freo_mixer.cart_mode ' + decision.cart_mode)
    _command(decision.station.slug, f'freo_mixer.duck {decision.duck_percent/100:.3f}')


def fade_current(slug):
    try:
        mixer_state(slug)
    except (OSError, RuntimeError, ValueError):
        return skip_current(slug)
    return _command(slug, 'freo_mixer.fade_a')


def clear_future(slug):
    return _command(slug, 'freo_mixer.clear_future')


def deck_control(slug, deck, action, fade_seconds=None):
    if deck not in ('A','B') or action not in ('take','pause','clear','fade','future'):
        raise ValueError('Invalid deck control')
    argument = ''
    if fade_seconds is not None:
        if action not in ('take','fade') or not 0 <= float(fade_seconds) <= 10:
            raise ValueError('Invalid fade duration')
        argument = f' {float(fade_seconds):.3f}'
    return _command(slug, f'freo_deck.{action}_{deck.lower()}{argument}')
