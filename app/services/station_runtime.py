"""Root-run station rendering and narrowly scoped systemd operations."""
import json
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


def render_liquidsoap(station, password):
    slug = validate_slug(station.slug)
    frequency = 300 + zlib.crc32(slug.encode()) % 300
    values = {
        '__CONTROL_SOCKET__': json.dumps(f'/run/freo/playout/{slug}/control.sock'),
        '__PLAYLIST__': json.dumps(f'/var/lib/freo/playlists/{slug}.m3u'),
        '__EVENT_FILE__': json.dumps(f'/run/freo/playout/{slug}/events.log'),
        '__FREQUENCY__': str(frequency),
        '__TITLE__': json.dumps(f'{station.name} Engine Test'),
        '__MOUNT__': json.dumps('/' + slug),
        '__SOURCE_PASSWORD__': json.dumps(password),
        '__NAME__': json.dumps(station.name),
        '__DESCRIPTION__': json.dumps(station.description or 'Generated station test audio'),
    }
    liquidsoap = (SOURCE / 'deploy/liquidsoap/station.liq.template').read_text()
    for marker, value in values.items():
        liquidsoap = liquidsoap.replace(marker, value)
    return liquidsoap


def render(station):
    require_root()
    slug = validate_slug(station.slug)
    if not station.enabled or not station.stream or not station.stream.enabled:
        raise ValueError('Station and stream must be enabled to render')
    if station.stream.format != 'mp3' or station.stream.bitrate != 64:
        raise ValueError('Only 64 kbps MP3 is supported in Phase 3')
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
