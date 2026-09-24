"""Complete, immutable release bundles. No runtime state enters an artifact."""
import ast
import json
import os
import platform
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from email.parser import BytesParser

from .recovery import RecoveryError, digest, run

DIRECTORIES = ('app', 'freo_ops', 'migrations', 'deploy', 'scripts', 'docs', 'tests', '.github')
FILES = ('wsgi.py', 'requirements.txt', 'requirements-dev.txt', 'requirements-live-mic.txt', 'pytest.ini', '.env.example',
         'README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'LICENSE')


def version_at(root):
    for node in ast.parse((Path(root) / 'app/version.py').read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?', value):
                return value
    raise RecoveryError('Release lacks a valid application version')


def migration_head(root):
    revisions = {}
    for path in (Path(root) / 'migrations/versions').glob('*.py'):
        values = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('revision', 'down_revision'):
                        values[target.id] = ast.literal_eval(node.value)
        if values['revision'] in revisions:
            raise RecoveryError('Duplicate migration revision')
        revisions[values['revision']] = values['down_revision']
    heads = set(revisions) - set(revisions.values())
    if len(heads) != 1:
        raise RecoveryError('Release must contain one migration head')
    head = current = heads.pop()
    seen = set()
    while current is not None:
        if current in seen or current not in revisions:
            raise RecoveryError('Broken migration chain')
        seen.add(current)
        current = revisions[current]
    if len(seen) != len(revisions):
        raise RecoveryError('Disconnected migration chain')
    return head


def source_files(root):
    root = Path(root)
    result = []
    tracked = run(['git', '-C', str(root), 'ls-files', '--cached', '--others', '--exclude-standard',
                   '-z', '--', *DIRECTORIES, *FILES]).decode().split('\0')
    for name in sorted(set(tracked) - {''}):
        path = root / name
        if path.is_symlink():
            raise RecoveryError('Release source must not contain symlinks')
        if (path.name.startswith('.env') and name != '.env.example') or path.name.endswith('.license.json') or path.suffix in ('.key', '.pem', '.dump', '.db', '.sqlite', '.gpg'):
            raise RecoveryError('Private runtime material must not enter release source')
        if path.is_file() and '__pycache__' not in path.parts and not path.name.endswith(('.pyc', '.bak', '.previous', '.log')):
            result.append(path)
    return result


def lock_wheels(directory):
    locked = []
    names = set()
    for wheel in sorted(directory.glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            metadata = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
            if len(metadata) != 1:
                raise RecoveryError('Invalid wheel metadata')
            record = BytesParser().parsebytes(archive.read(metadata[0]))
        name, version = record['Name'], record['Version']
        if not name or not version or not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or not re.fullmatch(r'[A-Za-z0-9_.+!-]+', version):
            raise RecoveryError('Invalid wheel package name/version')
        normalized = re.sub(r'[-_.]+', '-', name).lower()
        if normalized in names:
            raise RecoveryError('Multiple versions/builds of one dependency in wheelhouse')
        names.add(normalized)
        locked.append(f'{name}=={version} --hash=sha256:{digest(wheel)}')
    if not locked:
        raise RecoveryError('Release wheelhouse is empty')
    return '\n'.join(locked) + '\n'


def build(root, destination, *, development=False, wheelhouse=None):
    root, destination = Path(root).resolve(), Path(destination).absolute()
    if destination.exists():
        raise RecoveryError('Release output already exists')
    version = version_at(root)
    commit = run(['git', '-C', str(root), 'rev-parse', 'HEAD']).decode().strip()
    if not development:
        if platform.machine() != 'x86_64' or platform.python_version_tuple()[:2] != ('3', '12'):
            raise RecoveryError('Build public artifacts with Python 3.12 on the supported x86_64 target')
        os_release = platform.freedesktop_os_release()
        if os_release.get('ID') != 'ubuntu' or os_release.get('VERSION_ID') != '24.04':
            raise RecoveryError('Build public artifacts on Ubuntu 24.04')
        if not (root / 'LICENSE').is_file():
            raise RecoveryError('Select and commit a project LICENSE before building a public release')
        if run(['git', '-C', str(root), 'status', '--porcelain']).strip():
            raise RecoveryError('Public releases require a clean source checkout')
        tag = run(['git', '-C', str(root), 'describe', '--exact-match', '--tags', 'HEAD']).decode().strip()
        if tag != 'v' + version:
            raise RecoveryError('Release tag must match app/version.py')
    with tempfile.TemporaryDirectory(prefix='freo-release-build-') as name:
        work = Path(name)
        payload = work / 'payload'
        payload.mkdir()
        for source in source_files(root):
            relative = source.relative_to(root)
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        wheels = payload / 'wheels'
        wheels.mkdir()
        if wheelhouse:
            for wheel in Path(wheelhouse).glob('*.whl'):
                shutil.copyfile(wheel, wheels / wheel.name)
        elif not development:
            run([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
                 '--dest', str(wheels), '-r', str(root / 'requirements-live-mic.txt')])
        if list(wheels.iterdir()):
            (payload / 'requirements.lock').write_text(lock_wheels(wheels))
        elif not development:
            raise RecoveryError('A public release must include locked dependency wheels')
        manifest = dict(format=1, version=version, commit=commit, development=development,
                        platform='ubuntu-24.04-x86_64', python='3.12',
                        schema_head=migration_head(root),
                        supported_source_revisions=['a71d25b609ef', 'd02f9a41c830', 'e83b9204c6af', 'f39c8210b7de', 'a64f09e2b731'],
                        files={})
        for path in sorted(payload.rglob('*')):
            if path.is_file():
                manifest['files'][str(path.relative_to(payload))] = dict(
                    sha256=digest(path), size=path.stat().st_size,
                    mode=stat.S_IMODE(path.stat().st_mode))
        (payload / 'release.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')
        with tempfile.TemporaryDirectory(prefix='.freo-release-', dir=destination.parent) as output:
            archive_path = Path(output) / 'release.tar.gz'
            with tarfile.open(archive_path, 'w:gz') as archive:
                for path in sorted(payload.rglob('*')):
                    if path.is_file():
                        archive.add(path, arcname=str(path.relative_to(payload)))
            os.link(archive_path, destination)
        return {'version': version, 'sha256': digest(destination), 'development': development}


def extract_verified(archive_path, directory, *, signature, keyring):
    """Verify a publisher signature before interpreting any archive content."""
    directory = Path(directory)
    if directory.exists():
        raise RecoveryError('Release directory already exists')
    with tempfile.TemporaryDirectory(prefix='freo-release-trust-') as home:
        private_archive = Path(home) / 'release.tar.gz'
        private_signature = Path(home) / 'release.sig'
        private_keyring = Path(home) / 'release-trust.gpg'
        for source, target in ((archive_path, private_archive), (signature, private_signature), (keyring, private_keyring)):
            shutil.copyfile(source, target)
        run(['gpgv', '--homedir', home, '--keyring', str(private_keyring),
             str(private_signature), str(private_archive)])
        return _extract_trusted(private_archive, directory)


def _extract_trusted(archive_path, directory):
    directory.mkdir(mode=0o755, parents=True)
    seen = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or '..' in path.parts
                    or member.name in seen or not path.parts
                    or (path.parts[0] not in (*DIRECTORIES, 'wheels')
                        and member.name not in (*FILES, 'requirements.lock', 'release.json'))):
                raise RecoveryError('Invalid release archive entry')
            seen.add(member.name)
            target = directory / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    manifest = json.loads((directory / 'release.json').read_text())
    if not isinstance(manifest, dict) or manifest.get('format') != 1 or manifest.get('development') is not False:
        raise RecoveryError('Only public release-format artifacts may be installed')
    if not isinstance(manifest.get('files'), dict) or not isinstance(manifest.get('supported_source_revisions'), list):
        raise RecoveryError('Invalid release manifest')
    if seen != set(manifest['files']) | {'release.json'}:
        raise RecoveryError('Release file inventory differs from its manifest')
    for relative, info in manifest['files'].items():
        path = directory / relative
        if digest(path) != info['sha256'] or path.stat().st_size != info['size']:
            raise RecoveryError('Release file checksum mismatch')
        if stat.S_IMODE(path.stat().st_mode) != info['mode']:
            raise RecoveryError('Release file permissions mismatch')
    if version_at(directory) != manifest['version'] or migration_head(directory) != manifest['schema_head']:
        raise RecoveryError('Release identity differs from its manifest')
    # The management CLI uses umask 077 for secrets. Public code directories
    # must nevertheless be traversable by the non-root service accounts.
    directory.chmod(0o755)
    for path in directory.rglob('*'):
        if path.is_dir():
            path.chmod(0o755)
    return manifest
