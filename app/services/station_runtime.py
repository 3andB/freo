"""Root-run station rendering and narrowly scoped systemd operations."""
import json
import fcntl
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import zlib

from app.services.stations import validate_slug

ROOT = Path('/etc/freo')
SECRETS = ROOT / 'secrets/stations'
CONFIGS = ROOT / 'radio/stations'
SNIPPETS = Path('/etc/nginx/snippets/freo-stations')
SOURCE = Path(__file__).resolve().parents[2]
PLAYLISTS = Path('/var/lib/freo/playlists')


_runtime_locked = ContextVar('freo_runtime_locked', default=False)


@contextmanager
def operation_lock():
    require_root()
    if _runtime_locked.get():
        yield
        return
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'station-provision.lock'
    if path.is_symlink():
        raise ValueError('Symlink provisioning lock is forbidden')
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        token = _runtime_locked.set(True)
        try:
            yield
        finally:
            _runtime_locked.reset(token)


def serialized(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        with operation_lock():
            return operation(*args, **kwargs)
    return guarded


def require_root():
    if os.geteuid() != 0:
        raise PermissionError('Station lifecycle commands require root; the web app cannot perform them')


def unit_name(slug):
    validate_slug(slug)
    return f'freo-playout@{slug}.service'


def run_checked(args):
    subprocess.run(args, check=True, capture_output=True, timeout=90)


def credential(slug):
    require_root()
    validate_slug(slug)
    SECRETS.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(SECRETS, 0o700)
    path = SECRETS / f'{slug}.json'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'source': secrets.token_hex(32)}, stream)
    if path.stat().st_mode & 0o077:
        raise PermissionError('Station credential permissions are unsafe')
    value = json.loads(path.read_text()).get('source')
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError('Station credential is invalid')
    return value


def atomic_install(path, data, mode, user, group):
    import pwd, grp
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.chmod(temp, mode)
        os.chown(temp, pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid)
        return temp
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def install_staged(path, temp):
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + '.previous'))
    os.replace(temp, path)


def render_liquidsoap(station, password, audio_settings=None):
    from app.services.station_audio import active_settings, validate_settings, processing_liquidsoap
    audio = validate_settings(audio_settings) if audio_settings is not None else active_settings(station.stream)
    slug = validate_slug(station.slug)
    frequency = 300 + zlib.crc32(slug.encode()) % 300
    values = {
        '__BITRATE__': str(audio['bitrate']),
        '__AUDIO_PROCESSING__': processing_liquidsoap(audio),
        '__MIC_ENABLED__': 'true' if os.environ.get('FREO_LIVE_MIC') == '1' else 'false',
        '__MIC_INPUT__': (f'input.http(id="freo_mic_input", max_buffer=0.25, poll_delay=0.5, timeout=2.0, format="wav", int_args=[("probesize",4096),("analyzeduration",0)], {{"http://127.0.0.1:8091/audio/{slug}?token=" ^ mic_token()}})' if os.environ.get('FREO_LIVE_MIC') == '1' else 'blank()'),
        '__CONTROL_SOCKET__': json.dumps(f'/run/freo/playout/{slug}/control.sock'),
        '__PLAYLIST__': json.dumps(f'/var/lib/freo/playlists/{slug}.m3u'),
        '__EVENT_FILE__': json.dumps(f'/run/freo/playout/{slug}/events.log'),
        '__FREQUENCY__': str(frequency),
        '__OPERATOR_MODE__': json.dumps('DJ_BOOTH' if station.automation and station.automation.operator_mode == 'DJ_BOOTH' else 'AUTO'),
        '__TITLE__': json.dumps(f'{station.name} · Broadcast tone'),
        '__MOUNT__': json.dumps('/' + slug),
        '__SOURCE_PASSWORD__': json.dumps(password),
        '__NAME__': json.dumps(station.name),
        '__DESCRIPTION__': json.dumps(station.description or 'Generated station test audio'),
    }
    liquidsoap = (SOURCE / 'deploy/liquidsoap/station.liq.template').read_text()
    for marker, value in values.items():
        liquidsoap = liquidsoap.replace(marker, value)
    return liquidsoap


@serialized
def render(station):
    require_root()
    slug = validate_slug(station.slug)
    if not station.enabled or not station.stream or not station.stream.enabled:
        raise ValueError('Station and stream must be enabled to render')
    if station.stream.format != 'mp3' or station.stream.bitrate not in (64, 96, 128):
        raise ValueError('Choose a supported MP3 bitrate')
    from app.services.media import refresh_playlist
    refresh_playlist(slug)
    password = credential(slug)
    liquidsoap = render_liquidsoap(station, password)
    snippet = (SOURCE / 'deploy/nginx/station-location.conf.template').read_text().replace('__SLUG__', slug)
    config_path = CONFIGS / f'{slug}.liq'
    snippet_path = SNIPPETS / f'{slug}.conf'
    CONFIGS.mkdir(parents=True, exist_ok=True, mode=0o755)
    SNIPPETS.mkdir(parents=True, exist_ok=True, mode=0o755)
    config_tmp = atomic_install(config_path, liquidsoap, 0o640, 'root', 'freo-playout')
    snippet_tmp = atomic_install(snippet_path, snippet, 0o644, 'root', 'root')
    prior_icecast = (ROOT / 'radio/icecast.xml').read_bytes()
    snippet_existed = snippet_path.exists()
    try:
        run_checked(['/usr/bin/liquidsoap', '--check', str(config_tmp)])
        install_staged(config_path, config_tmp)
        install_staged(snippet_path, snippet_tmp)
    finally:
        config_tmp.unlink(missing_ok=True)
        snippet_tmp.unlink(missing_ok=True)
    # The root-owned renderer retains prior Icecast config and credentials.
    run_checked(['/opt/freo/venv/bin/python', str(SOURCE / 'scripts/render-radio-config.py')])
    if (ROOT / 'radio/icecast.xml').read_bytes() != prior_icecast:
        try:
            run_checked(['/bin/systemctl', 'reload', 'icecast2.service'])
        except Exception:
            (ROOT / 'radio/icecast.xml').write_bytes(prior_icecast)
            raise
    try:
        run_checked(['/usr/sbin/nginx', '-t'])
    except Exception:
        if snippet_existed:
            shutil.copy2(snippet_path.with_suffix('.conf.previous'), snippet_path)
        else:
            snippet_path.unlink(missing_ok=True)
        raise
    run_checked(['/bin/systemctl', 'reload', 'nginx.service'])


def service_action(slug, action):
    require_root()
    if action not in {'start', 'stop', 'restart', 'status'}:
        raise ValueError('Unsupported station action')
    unit = unit_name(slug)
    if action == 'status':
        result = subprocess.run(['/bin/systemctl', 'is-active', unit], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() == 'active'
    if action == 'start':
        run_checked(['/bin/systemctl', 'enable', unit])
    if action == 'stop':
        run_checked(['/bin/systemctl', 'disable', unit])
    run_checked(['/bin/systemctl', action, unit])


class AudioRecoveryError(RuntimeError):
    pass


def audio_backup(station):
    slug = validate_slug(station.slug)
    return CONFIGS / f'{slug}.liq.audio-{station.stream.audio_revision}.previous'


def wait_audio_online(station, timeout=60):
    import time
    from app.routes.stations import observed_status
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        from app.extensions import db
        db.session.refresh(station)
        if station.desired_state != 'running':
            raise RuntimeError('Master broadcast is OFF')
        status = observed_status(station)
        if status['playout'] == 'running' and status['stream'] == 'online':
            return
        time.sleep(1)
    raise RuntimeError('Station did not resume streaming')


def restore_audio(station):
    backup = audio_backup(station)
    if not backup.exists():
        return
    if backup.is_symlink():
        raise AudioRecoveryError('Invalid audio backup')
    try:
        target = CONFIGS / f'{validate_slug(station.slug)}.liq'
        staged = atomic_install(target, backup.read_text(), 0o640, 'root', 'freo-playout')
        os.replace(staged, target)
        from app.extensions import db
        db.session.refresh(station)
        if station.desired_state == 'running':
            service_action(station.slug, 'restart')
            wait_audio_online(station)
        backup.unlink()
    except Exception as error:
        raise AudioRecoveryError('Could not restore station audio') from error


@serialized
def apply_audio(station, values):
    """Only the station encoder changes; Icecast and other stations stay online.

    Keep a revision-specific backup until the database records success. A worker
    interrupted after installing the candidate can retry without replacing it.
    """
    require_root()
    slug = validate_slug(station.slug)
    target = CONFIGS / f'{slug}.liq'
    if target.is_symlink() or not target.is_file():
        raise ValueError('Station configuration is unavailable')
    backup = audio_backup(station)
    if backup.is_symlink():
        raise ValueError('Invalid audio backup')
    staged = atomic_install(target, render_liquidsoap(station, credential(slug), values), 0o640, 'root', 'freo-playout')
    try:
        run_checked(['/usr/bin/liquidsoap', '--check', str(staged)])
        from app.extensions import db
        db.session.refresh(station)
        if not station.enabled or station.lifecycle_state != 'ready':
            raise ValueError('Station is no longer ready for audio changes')
        if not backup.exists():
            saved = atomic_install(backup, target.read_text(), 0o640, 'root', 'freo-playout')
            os.replace(saved, backup)
        running = station.desired_state == 'running'
        os.replace(staged, target)
        if running:
            service_action(slug, 'restart')
            wait_audio_online(station)
    except Exception:
        restore_audio(station)
        raise
    finally:
        staged.unlink(missing_ok=True)


def finish_audio(station):
    audio_backup(station).unlink(missing_ok=True)


@serialized
def remove(station):
    """Remove only this station's runtime; each step is safe to repeat.

    On reload failure keep the station disabled and retain a retryable operation.
    No other playout process is stopped or restarted.
    """
    require_root()
    slug = validate_slug(station.slug)
    service_action(slug, 'stop')
    if service_action(slug, 'status'):
        raise RuntimeError('Station is still running')
    for parent, suffix in ((SNIPPETS, '.conf'), (CONFIGS, '.liq'), (SECRETS, '.json')):
        if parent.is_symlink():
            raise ValueError('Symlink runtime directory is forbidden')
        for ending in (suffix, suffix + '.previous'):
            path = parent / (slug + ending)
            if path.is_symlink():
                raise ValueError('Symlink runtime file is forbidden')
            path.unlink(missing_ok=True)
    for backup in CONFIGS.glob(slug + '.liq.audio-*.previous'):
        if backup.is_symlink():
            raise ValueError('Symlink audio backup is forbidden')
        backup.unlink(missing_ok=True)
    run_checked(['/opt/freo/venv/bin/python', str(SOURCE / 'scripts/render-radio-config.py')])
    run_checked(['/usr/sbin/nginx', '-t'])
    run_checked(['/bin/systemctl', 'reload', 'icecast2.service'])
    run_checked(['/bin/systemctl', 'reload', 'nginx.service'])
    playlist = PLAYLISTS / (slug + '.m3u')
    if playlist.is_symlink():
        raise ValueError('Symlink playlist is forbidden')
    playlist.unlink(missing_ok=True)
    # systemd owns the runtime directory; stopping its unit removes it.
