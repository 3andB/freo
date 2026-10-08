"""Reviewed 0.3.2-to-V1 host adoption, called only by the offline updater."""
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from . import recovery, releases


def transition(current, release, revision, version):
    return (releases.version_at(current) == '0.3.2' and revision == 'c83d4e5f9012'
            and version.startswith('1.0.0'))


def check_legacy_templates(current):
    expected = json.loads(Path(__file__).with_name('legacy_032.json').read_text())
    for name, checksum in expected.items():
        path = current / name
        if not path.is_file() or path.is_symlink() or recovery.digest(path) != checksum:
            raise recovery.RecoveryError('Customized legacy template requires review: ' + name)


def check_space(url, roots, release, backup, verification):
    """Conservative full-copy budget, summed when destinations share a device."""
    size = 0
    for root in roots:
        paths = [root] if not root.is_dir() else root.rglob('*')
        for path in paths:
            if stat.S_ISREG(path.lstat().st_mode):
                size += path.stat().st_size
    connection = recovery.connect(url)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_database_size(current_database())')
            size += cursor.fetchone()[0]
            database_path = Path('/var/lib/postgresql')
    finally:
        connection.close()
    code = sum(p.stat().st_size for p in release.rglob('*') if p.is_file())
    budgets = {}
    for path, needed in ((release, code * 4), (Path(tempfile.gettempdir()), size * 4),
                         (Path(backup).parent, size * 2), (Path(verification).parent, size * 2),
                         (database_path, size * 2)):
        while not path.exists():
            path = path.parent
        device = path.stat().st_dev
        previous = budgets.get(device, (path, 0))[1]
        budgets[device] = (path, previous + needed)
    for path, needed in budgets.values():
        if shutil.disk_usage(path).free < needed + 512 * 1024 * 1024:
            raise recovery.RecoveryError('Insufficient space for verified backup, restore and staging on ' + str(path))


def prepare_icecast(release, state):
    """Build from pinned upstream source without replacing the package executable."""
    archive = state / 'icecast-2.5.0.tar.gz'
    if not archive.exists():
        recovery.run(['curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                      '--output', str(archive), 'https://downloads.xiph.org/releases/icecast/icecast-2.5.0.tar.gz'])
    if recovery.digest(archive) != 'd9aa07c7429aec19d950ff6fd425c371f77158cd34ff220fc191b2c186c67c7a':
        raise recovery.RecoveryError('Unexpected Icecast source checksum')
    # Called only after a verified recovery point; package output stays private.
    recovery.run(['apt-get', 'install', '--no-remove', '-y', 'build-essential', 'pkg-config', 'patch',
                  'libigloo-dev', 'libxml2-dev', 'libxslt1-dev', 'libvorbis-dev', 'libogg-dev',
                  'libcurl4-openssl-dev', 'librhash-dev', 'libssl-dev', 'libtheora-dev', 'libspeex-dev'],
                 env=dict(os.environ, DEBIAN_FRONTEND='noninteractive'))
    build = state / ('icecast-build-' + release.name)
    recovery.run(['bash', str(release / 'scripts/build-icecast-2.5.sh'), str(archive), str(build)])
    binary = build / 'src/icecast'
    destination = Path('/opt/freo/engines') / recovery.digest(binary) / 'icecast'
    destination.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    destination.parent.parent.chmod(0o755)
    destination.parent.chmod(0o755)
    shutil.copyfile(binary, destination)
    destination.chmod(0o755)
    return destination


def activate_icecast(binary, replacing=False):
    directory = Path('/etc/systemd/system/icecast2.service.d')
    directory.mkdir(mode=0o755, exist_ok=True)
    target = directory / 'freo-patched.conf'
    if target.exists() or target.is_symlink():
        import re
        if (not replacing or target.is_symlink() or not re.fullmatch(r'\[Service\]\nExecStart=\nExecStart=/opt/freo/engines/[a-f0-9]{64}/icecast -c /etc/freo/radio/icecast.xml\n', target.read_text())):
            raise recovery.RecoveryError('Existing Icecast patch override requires review')
    target.write_text('[Service]\nExecStart=\nExecStart=' + str(binary) + ' -c /etc/freo/radio/icecast.xml\n')
    target.chmod(0o644)
    recovery.run(['systemctl', 'daemon-reload'])
    recovery.run(['systemctl', 'restart', 'icecast2.service'])


def configure_environment(values, destination):
    from cryptography.fernet import Fernet
    key = values.get('FREO_PROVIDER_ENCRYPTION_KEY')
    if key:
        try:
            Fernet(key.encode())
        except (ValueError, TypeError) as error:
            raise recovery.RecoveryError('Invalid existing provider encryption key') from error
    else:
        key = Fernet.generate_key().decode()
        with destination.open('a') as stream:
            stream.write('\nFREO_PROVIDER_ENCRYPTION_KEY=' + key + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        values['FREO_PROVIDER_ENCRYPTION_KEY'] = key


def provision(release, values, env):
    python = str(release / 'venv/bin/python')
    # Existing offline converter retains original files/identities and translates
    # Imaging references to V1 station audio. All writers are already guarded.
    recovery.run([python, '-c', """
from app import create_app
from app.models import Station
from app.services.imaging_migration import convert
app=create_app()
with app.app_context():
    for station in Station.query.order_by(Station.id):
        result=convert(station,maintenance=True)
        if any(result['references'].values()):
            raise RuntimeError('Legacy imaging references remain: '+station.slug)
"""], cwd=release, env=env)
    recovery.run(['install', '-d', '-o', 'freo-automation', '-g', 'freo-playout', '-m', '2750',
                  '/var/lib/freo/bulletins'])
    root = Path(values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads') / 'production'
    if any(c in str(root) for c in '\n\r%"\\') or not root.is_absolute():
        raise recovery.RecoveryError('Production storage must be an absolute systemd-safe path')
    if root.is_symlink():
        raise recovery.RecoveryError('Symlinked production storage requires review')
    recovery.run(['install', '-d', '-o', 'freo', '-g', 'freo', '-m', '2770', str(root)])
    override = Path('/etc/systemd/system/freo-production.service.d/storage.conf')
    body = '[Service]\nReadWritePaths=\nReadWritePaths="' + str(root.parent) + '"\n'
    if override.is_symlink() or (override.exists() and override.read_text() != body):
        raise recovery.RecoveryError('Custom production storage override requires review')
    override.parent.mkdir(mode=0o755, exist_ok=True)
    override.write_text(body)
    override.chmod(0o644)
    connection = recovery.connect(values['DATABASE_URL'])
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT s.slug, s.enabled AND t.enabled FROM stations s JOIN stream_mounts t ON t.station_id=s.id WHERE s.deleted_at IS NULL ORDER BY s.id')
            slugs = cursor.fetchall()
            cursor.execute('SELECT values FROM installation_settings WHERE id=1')
            microphone = bool(cursor.fetchone()[0].get('FREO_LIVE_MIC'))
    finally:
        connection.close()
    for slug, enabled in slugs:
        recovery.run([python, str(release / 'scripts/recording-storage.py'),
                      values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media', slug])
        if enabled:
            recovery.run([str(release / 'venv/bin/flask'), '--app', 'wsgi:app', 'station', 'render', slug],
                         cwd=release, env=env)
    recovery.run(['systemctl', 'daemon-reload'])
    return microphone


def check_runtime(current, env):
    # Read-only comparison using the matched source interpreter/model. Do not
    # import either release into the updater process or rewrite operator edits.
    program = """
from pathlib import Path
import json
from app import create_app
from app.models import Station, MediaIngestJob
from app.services.station_runtime import render_liquidsoap
app=create_app()
with app.app_context():
    if MediaIngestJob.query.filter(MediaIngestJob.kind.in_(('imaging','img_verify','img_enable')), MediaIngestJob.status.in_(('pending','processing'))).first():
        raise SystemExit('Finish pending Imaging jobs before upgrading')
    for station in Station.query.filter_by(deleted_at=None).all():
        path=Path('/etc/freo/radio/stations')/(station.slug+'.liq')
        if not path.exists():
            continue
        secret=Path('/etc/freo/secrets/stations')/(station.slug+'.json')
        expected=render_liquidsoap(station,json.loads(secret.read_text())['source'])
        if path.read_text()!=expected:
            raise SystemExit('Customized station runtime requires review: '+station.slug)
"""
    recovery.run([str(current / 'venv/bin/python'), '-c', program], cwd=current, env=env)


def verify_permanent_files(backup, passphrase, values):
    permanent = [Path(values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media'),
                 Path(values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads')]
    with recovery.unpack(backup, passphrase) as (_, manifest):
        roots = list(map(Path, manifest['roots']))
        for entry in manifest['entries']:
            path = roots[entry['root']] / entry['path']
            if entry['kind'] == 'file' and any(path.is_relative_to(root) for root in permanent):
                if not path.is_file() or path.is_symlink() or recovery.digest(path) != entry['sha256']:
                    raise recovery.RecoveryError('Permanent file preservation failed: '+str(path))


def check_services():
    rows = json.loads(recovery.run(['systemctl', 'list-units', '--all', '--no-pager', '--output=json',
                                   '--type=service', 'freo*', 'icecast2.service']))
    for row in rows:
        if row['active'] == 'failed' or row['sub'] in ('auto-restart', 'failed'):
            raise recovery.RecoveryError('Repair the failing baseline service before upgrading: ' + row['unit'])


def hosting_transition(current, release, revision):
    """The reviewed Phase A -> hosted-capable V1 bridge, not a general bypass."""
    if (releases.version_at(current) != '1.0.0-dev.1' or revision != 'fc06a1b2c3d4'
            or (current / 'freo_ops/hosting.py').exists() or not (release / 'freo_ops/hosting.py').exists()):
        return False
    expected = json.loads(Path(__file__).with_name('legacy_v1_phase_a.json').read_text())
    for name, checksum in expected.items():
        path = current / name
        if not path.is_file() or path.is_symlink() or recovery.digest(path) != checksum:
            raise recovery.RecoveryError('Customized Phase A template requires review: ' + name)
    return True
