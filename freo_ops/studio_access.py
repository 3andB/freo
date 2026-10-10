"""Root-approved Studio release handoff. No runtime or backup paths are served."""
import hashlib
import hmac
import json
import os
import grp
from pathlib import Path
import re
import secrets
import stat
import tempfile
from datetime import datetime, timezone

ROOT = Path('/srv/freo-studio')
CATALOG = ROOT / 'approved-releases.json'
KEYS = ROOT / 'studio-api-keys.json'
NAME = 'Freo Studio Hosting Manager'
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-rc\.\d+)?\Z')
TOKEN = re.compile(r'freo_studio_([0-9a-f]{32})\.([A-Za-z0-9_-]{43})\Z')
ROLES = ('kit', 'signature', 'checksum', 'publisher_key', 'instructions')
FILES = {
    'kit': re.compile(r'freo-v\d+\.\d+\.\d+(?:-rc\.\d+)?-install-kit\.tar\Z'),
    'signature': re.compile(r'freo-v\d+\.\d+\.\d+(?:-rc\.\d+)?-install-kit\.tar\.asc\Z'),
    'checksum': re.compile(r'freo-v\d+\.\d+\.\d+(?:-rc\.\d+)?-install-kit\.sha256\Z'),
    'publisher_key': re.compile(r'publisher\.gpg\Z'),
    'instructions': re.compile(r'v\d+(?:-rc\d+)?-installation\.md\Z'),
}


class AccessError(ValueError):
    pass


def _require_root():
    if os.geteuid() != 0:
        raise AccessError('Root is required to manage Studio keys')


def _freo_gid():
    return grp.getgrnam('freo').gr_gid


def _trusted(path, *, private=False):
    """Reject symlinks and writable parents, including the final path."""
    for entry in (path, *path.parents):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise AccessError('Unsafe release handoff permissions')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or (private and info.st_mode & 0o007):
        raise AccessError('Unsafe release handoff file')
    return info


def _load(path, *, private=False):
    try:
        if _trusted(path, private=private).st_size > 65536:
            raise AccessError('Release handoff metadata is too large')
        return json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as error:
        raise AccessError('Release handoff metadata is unavailable') from error


def _save_keys(value):
    _trusted(CATALOG)
    directory = KEYS.parent
    fd, name = tempfile.mkstemp(prefix='.studio-keys-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchown(output.fileno(), 0, _freo_gid())
            os.fchmod(output.fileno(), 0o640)
            json.dump(value, output, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, KEYS)
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def keys():
    if not KEYS.exists():
        return {'format': 1, 'keys': []}
    value = _load(KEYS, private=True)
    if (not isinstance(value, dict) or set(value) != {'format', 'keys'}
            or value['format'] != 1 or not isinstance(value['keys'], list)):
        raise AccessError('Invalid Studio key inventory')
    seen = set()
    for row in value['keys']:
        if (not isinstance(row, dict) or set(row) != {'id', 'name', 'digest', 'created_at', 'revoked_at'}
                or not isinstance(row['id'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['id'])
                or row['name'] != NAME or not isinstance(row['digest'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', row['digest'])
                or not isinstance(row['created_at'], str)
                or row['revoked_at'] is not None and not isinstance(row['revoked_at'], str)
                or row['id'] in seen):
            raise AccessError('Invalid Studio key inventory')
        seen.add(row['id'])
    return value


def create_key(*, rotate=False):
    _require_root()
    value = keys()
    if not rotate and any(row['revoked_at'] is None for row in value['keys']):
        raise AccessError('An active Studio key exists; use rotate')
    identifier = secrets.token_hex(16)
    token = f'freo_studio_{identifier}.{secrets.token_urlsafe(32)}'
    value['keys'].append(dict(id=identifier, name=NAME,
        digest=hashlib.sha256(token.encode('ascii')).hexdigest(),
        created_at=datetime.now(timezone.utc).isoformat(), revoked_at=None))
    _save_keys(value)
    return identifier, token


def revoke_key(identifier):
    _require_root()
    value = keys()
    row = next((row for row in value['keys'] if row['id'] == identifier), None)
    if row is None:
        raise AccessError('Studio key not found')
    if row['revoked_at'] is None:
        row['revoked_at'] = datetime.now(timezone.utc).isoformat()
        _save_keys(value)


def authenticate(header):
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != 'bearer' or not TOKEN.fullmatch(parts[1]):
        return None
    identifier = TOKEN.fullmatch(parts[1]).group(1)
    digest = hashlib.sha256(parts[1].encode('ascii')).hexdigest()
    row = next((row for row in keys()['keys'] if row['id'] == identifier), None)
    if hmac.compare_digest(row['digest'] if row else '0' * 64, digest) and row and row['revoked_at'] is None:
        return identifier
    return None


def catalog():
    value = _load(CATALOG)
    if (not isinstance(value, dict) or set(value) != {'format', 'releases'}
            or value['format'] != 1 or not isinstance(value['releases'], list)):
        raise AccessError('Invalid Studio release inventory')
    found = {}
    for row in value['releases']:
        if (not isinstance(row, dict) or set(row) != {'version', 'directory', 'files'}
                or not isinstance(row['version'], str) or not VERSION.fullmatch(row['version'])
                or not isinstance(row['directory'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', row['directory'])
                or not isinstance(row['files'], dict) or set(row['files']) != set(ROLES)
                or row['version'] in found):
            raise AccessError('Invalid Studio release inventory')
        for role, entry in row['files'].items():
            if (not isinstance(entry, dict) or set(entry) != {'name', 'size', 'sha256'}
                    or not isinstance(entry['name'], str) or not FILES[role].fullmatch(entry['name'])
                    or type(entry['size']) is not int or entry['size'] < 1
                    or not isinstance(entry['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])):
                raise AccessError('Invalid Studio release inventory')
        expected = f"freo-v{row['version']}-install-kit.tar"
        if row['files']['kit']['name'] != expected or row['files']['signature']['name'] != expected + '.asc':
            raise AccessError('Invalid Studio release inventory')
        found[row['version']] = row
    return found


def artifact(row, role):
    if role not in ROLES:
        raise AccessError('Installation material is not approved')
    entry = row['files'][role]
    path = ROOT / row['directory'] / entry['name']
    try:
        info = _trusted(path)
    except OSError as error:
        raise AccessError('Approved installation material is unavailable') from error
    if info.st_size != entry['size']:
        raise AccessError('Approved installation material changed')
    return path, entry


def verified_artifact(row, role):
    path, entry = artifact(row, role)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if not hmac.compare_digest(digest.hexdigest(), entry['sha256']):
        raise AccessError('Approved installation material changed')
    return path, entry
