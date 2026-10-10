"""The Studio credential can read only approved, unchanged installation files."""
import hashlib
import json
import stat

import pytest

from freo_ops import studio_access as access
from tests.test_web import app

VERSION = '1.0.0-rc.1'
BASE = '/api/studio'


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setattr(access, 'ROOT', tmp_path)
    monkeypatch.setattr(access, 'CATALOG', tmp_path / 'approved-releases.json')
    monkeypatch.setattr(access, 'KEYS', tmp_path / 'studio-api-keys.json')
    monkeypatch.setattr(access, '_require_root', lambda: None)
    monkeypatch.setattr(access, '_freo_gid', access.os.getgid)
    monkeypatch.setattr(access.os, 'fchown', lambda *args: None)
    # /tmp is intentionally writable; keep checks below this disposable root.
    def trusted(path, *, private=False):
        for entry in (path, *path.parents):
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_mode & 0o022:
                raise access.AccessError('unsafe')
            if entry == tmp_path:
                break
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or (private and info.st_mode & 0o007):
            raise access.AccessError('unsafe')
        return info
    monkeypatch.setattr(access, '_trusted', trusted)
    directory = tmp_path / 'rc1'
    directory.mkdir(mode=0o755)
    names = {
        'kit': f'freo-v{VERSION}-install-kit.tar',
        'signature': f'freo-v{VERSION}-install-kit.tar.asc',
        'checksum': f'freo-v{VERSION}-install-kit.sha256',
        'publisher_key': 'publisher.gpg',
        'instructions': 'v1-rc1-installation.md',
    }
    files = {}
    for role, name in names.items():
        content = f'test-{role}'.encode()
        (directory / name).write_bytes(content)
        files[role] = dict(name=name, size=len(content), sha256=hashlib.sha256(content).hexdigest())
    access.CATALOG.write_text(json.dumps({'format': 1, 'releases': [
        {'version': VERSION, 'directory': 'rc1', 'files': files}]}))
    identifier, token = access.create_key()
    return directory, identifier, token


def request(client, path, token, **kwargs):
    return client.get(path, base_url='https://freo.example',
                      headers={'Authorization': 'Bearer ' + token}, **kwargs)


def test_studio_endpoints_and_hash_only_key(app, staged, caplog):
    directory, identifier, token = staged
    stored = access.KEYS.read_text()
    assert token not in stored
    assert hashlib.sha256(token.encode()).hexdigest() in stored
    assert stat.S_IMODE(access.KEYS.stat().st_mode) == 0o640
    client = app.test_client()
    assert request(client, BASE + '/health', token).json == {'status': 'ok'}
    releases = request(client, BASE + '/releases', token).json['releases']
    assert releases == [{'version': VERSION, 'manifest': f'{BASE}/releases/{VERSION}/manifest'}]
    manifest = request(client, releases[0]['manifest'], token).json
    assert set(manifest['materials']) == set(access.ROLES)
    for role, entry in manifest['materials'].items():
        response = request(client, entry['download'], token)
        assert response.status_code == 200
        assert response.data == (directory / entry['name']).read_bytes()
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert 'attachment' in response.headers['Content-Disposition']
    assert request(client, f'{BASE}/releases/{VERSION}/download', token).data == (directory / manifest['materials']['kit']['name']).read_bytes()
    assert request(client, f'{BASE}/releases/0.3.2/download', token).status_code == 404
    assert identifier in stored
    assert token not in caplog.text


def test_https_auth_revocation_and_rotation(app, staged):
    _, identifier, token = staged
    client = app.test_client()
    assert client.get(BASE + '/health', headers={'Authorization': 'Bearer ' + token}).status_code == 403
    assert client.get(BASE + '/health', base_url='https://freo.example').status_code == 401
    assert request(client, BASE + '/health', token + 'x').status_code == 401
    second_id, second = access.create_key(rotate=True)
    assert request(client, BASE + '/health', second).status_code == 200
    assert request(client, BASE + '/health', token).status_code == 200
    access.revoke_key(identifier)
    assert request(client, BASE + '/health', token).status_code == 401
    assert request(client, BASE + '/health', second).status_code == 200
    access.revoke_key(second_id)
    assert request(client, BASE + '/health', second).status_code == 401


def test_only_approved_unchanged_files_are_downloaded(app, staged):
    directory, _, token = staged
    client = app.test_client()
    path = f'{BASE}/releases/{VERSION}/download'
    for query in ('?file=../../etc/passwd', '?file=environment', '?file=kit&file=signature', '?path=/etc/passwd'):
        assert request(client, path + query, token).status_code in (400, 404)
    assert client.post(path, base_url='https://freo.example', headers={'Authorization': 'Bearer ' + token}).status_code == 405
    file = directory / f'freo-v{VERSION}-install-kit.tar'
    file.write_bytes(b'bad-kit!')
    assert request(client, path, token).status_code == 503
    file.unlink()
    file.symlink_to('/etc/passwd')
    assert request(client, path, token).status_code == 503


def test_invalid_catalog_and_rate_limit_fail_closed(app, staged, monkeypatch):
    _, _, token = staged
    client = app.test_client()
    access.CATALOG.write_text('{"format":1,"releases":[{"version":"1.0.0-rc.1","directory":"../../etc","files":{}}]}')
    assert request(client, BASE + '/releases', token).status_code == 503
    access.CATALOG.write_text('{"format":1,"releases":[]}')
    from app.routes import studio_releases
    monkeypatch.setattr(studio_releases.limits, 'rate_limit', lambda *args: (False, 30))
    response = request(client, BASE + '/health', token)
    assert response.status_code == 429 and response.headers['Retry-After'] == '30'


def test_real_trust_check_rejects_writable_tmp_parent(tmp_path):
    assert tmp_path.is_dir()
    with pytest.raises(access.AccessError):
        # /tmp itself is writable even if the leaf is root-owned.
        access._trusted(tmp_path)
