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
            cursor.execute('SHOW data_directory')
            database_path = Path(cursor.fetchone()[0])
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


def activate_icecast(binary):
    directory = Path('/etc/systemd/system/icecast2.service.d')
    directory.mkdir(mode=0o755, exist_ok=True)
    target = directory / 'freo-patched.conf'
    if target.exists() or target.is_symlink():
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
    root = Path(values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads') / 'production'
    if root.is_symlink():
        raise recovery.RecoveryError('Symlinked production storage requires review')
    recovery.run(['install', '-d', '-o', 'freo', '-g', 'freo', '-m', '2770', str(root)])
    connection = recovery.connect(values['DATABASE_URL'])
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT s.slug FROM stations s JOIN streams t ON t.station_id=s.id WHERE s.enabled AND t.enabled ORDER BY s.id')
            slugs = [row[0] for row in cursor.fetchall()]
    finally:
        connection.close()
    for slug in slugs:
        recovery.run([python, str(release / 'scripts/recording-storage.py'),
                      values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media', slug])
        recovery.run([str(release / 'venv/bin/flask'), '--app', 'wsgi:app', 'station', 'render', slug],
                     cwd=release, env=env)
    recovery.run(['systemctl', 'daemon-reload'])
