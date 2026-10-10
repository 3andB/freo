import io
import json
import os
import stat
from pathlib import Path
import tarfile
import zipfile

import pytest

from freo_ops import releases, recovery


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'source'
    (root / 'app').mkdir(parents=True)
    (root / 'migrations/versions').mkdir(parents=True)
    (root / 'app/version.py').write_text("VERSION = '0.2.0'\n")
    (root / 'app/main.py').write_text('print("fixture")\n')
    (root / 'migrations/versions/first.py').write_text("revision = 'head'\ndown_revision = None\n")
    (root / 'wsgi.py').write_text('# fixture\n')
    (root / '.env.example').write_text('DATABASE_URL=REPLACE_ME\n')
    (root / '.gitignore').write_text('.env\n__pycache__/\n*.pyc\n')
    recovery.run(['git', 'init', '--quiet', str(root)])
    recovery.run(['git', '-C', str(root), 'add', '.'])
    recovery.run(['git', '-C', str(root), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                  'commit', '--quiet', '-m', 'Fixture'])
    (root / '.env').write_text('SECRET_KEY=must-never-be-shipped\n')
    (root / 'app/.env').write_text('PRIVATE=must-never-be-shipped\n')
    return root


def test_bundle_contains_complete_manifest_without_ignored_runtime_state(source, tmp_path):
    target = tmp_path / 'review.tar.gz'
    result = releases.build(source, target, development=True)
    assert result['development'] is True and result['sha256'] == recovery.digest(target)
    with tarfile.open(target) as archive:
        names = archive.getnames()
        assert '.env' not in names and 'app/.env' not in names and '.env.example' in names
        manifest = json.load(archive.extractfile('release.json'))
        assert set(names) == set(manifest['files']) | {'release.json'}
        assert manifest['schema_head'] == 'head'
        assert {'f39c8210b7de', 'a64f09e2b731', 'b72e19d4c603', 'c83d4e5f9012', 'fc06a1b2c3d4'} <= set(manifest['supported_source_revisions'])
    with pytest.raises(recovery.RecoveryError, match='already exists'):
        releases.build(source, target, development=True)


def test_release_blocks_private_tracked_files_and_symlinks(source):
    (source / 'app/private.key').write_text('private')
    with pytest.raises(recovery.RecoveryError, match='Private runtime'):
        releases.source_files(source)
    (source / 'app/private.key').unlink()
    (source / 'app/link').symlink_to('/etc/passwd')
    with pytest.raises(recovery.RecoveryError, match='symlinks'):
        releases.source_files(source)


def test_customer_archive_excludes_development_files_without_removing_source(source, tmp_path):
    excluded = ['tests/test_fixture.py', 'tests/data/audio.wav', '.github/workflows/ci.yml',
                'requirements-dev.txt', 'pytest.ini', 'CONTRIBUTING.md',
                'app/__pycache__/module.pyc', 'app/.pytest_cache/state',
                'scripts/test-install-postgres.py', 'scripts/build-release.py',
                'scripts/license-issuer.py', 'docs/audits/private-review.md', 'docs/rc5-acceptance.md']
    retained = ['scripts/install.sh', 'scripts/install-python.sh', 'scripts/validate-install.sh',
                'scripts/validate-admin-login.py', 'docs/installation.md', 'docs/recovery-and-upgrades.md',
                'deploy/nginx/freo.conf.template', 'app/static/workspace.js', 'LICENSE']
    for name in excluded + retained:
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture\n')
    target = tmp_path / 'customer.tar.gz'
    releases.build(source, target, development=True)
    with tarfile.open(target) as archive:
        names = set(archive.getnames())
        assert not names.intersection(excluded)
        assert set(retained) <= names
    assert all((source / name).is_file() for name in excluded)


def test_wheel_lock_hashes_all_dependencies_and_rejects_duplicate_versions(tmp_path):
    for version in ('1.0',):
        path = tmp_path / f'fixture-{version}-py3-none-any.whl'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(f'fixture-{version}.dist-info/METADATA', f'Name: fixture\nVersion: {version}\n')
    assert releases.lock_wheels(tmp_path) == f'fixture==1.0 --hash=sha256:{recovery.digest(path)}\n'
    duplicate = tmp_path / 'fixture-2.0-py3-none-any.whl'
    with zipfile.ZipFile(duplicate, 'w') as archive:
        archive.writestr('fixture-2.0.dist-info/METADATA', 'Name: fixture\nVersion: 2.0\n')
    with pytest.raises(recovery.RecoveryError, match='Multiple versions'):
        releases.lock_wheels(tmp_path)


def test_disconnected_migrations_are_rejected(source):
    (source / 'migrations/versions/broken.py').write_text("revision = 'broken'\ndown_revision = 'missing'\n")
    with pytest.raises(recovery.RecoveryError):
        releases.migration_head(source)


@pytest.mark.parametrize('failure', ['missing-driver', 'generated-bytecode'])
def test_public_build_validates_supplied_wheels_before_writing_archive(source, tmp_path, monkeypatch, failure):
    (source / 'LICENSE').write_text('Fixture license\n')
    recovery.run(['git', '-C', str(source), 'add', 'LICENSE'])
    recovery.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                  'commit', '--quiet', '-m', 'License'])
    recovery.run(['git', '-C', str(source), 'tag', 'v0.2.0'])
    monkeypatch.setattr(releases.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(releases.platform, 'python_version_tuple', lambda: ('3', '12', '3'))
    monkeypatch.setattr(releases.platform, 'freedesktop_os_release', lambda: {'ID': 'ubuntu', 'VERSION_ID': '24.04'})
    wheelhouse = tmp_path / 'wheels'
    wheelhouse.mkdir()
    with zipfile.ZipFile(wheelhouse / 'fixture-1.0-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('fixture-1.0.dist-info/METADATA', 'Name: fixture\nVersion: 1.0\n')
    original = releases.run
    checks = []
    def run(command, **kwargs):
        if command[0] == 'bash':
            assert command[1].endswith('/scripts/install-python.sh')
            assert command[-1] == '--offline'
            assert not Path(command[-2]).exists()
            assert (Path(command[2]) / 'requirements.lock').is_file()
            assert kwargs['env']['PYTHONDONTWRITEBYTECODE'] == '1'
            checks.append(command)
            if failure == 'missing-driver':
                raise recovery.RecoveryError('Incomplete runtime dependencies')
            cache = Path(command[2]) / 'app/__pycache__'
            cache.mkdir()
            (cache / 'fixture.pyc').write_bytes(b'unexpected bytecode')
            return b''
        return original(command, **kwargs)
    monkeypatch.setattr(releases, 'run', run)
    target = tmp_path / 'rejected.tar.gz'
    with pytest.raises(recovery.RecoveryError, match='Incomplete runtime dependencies|modified release payload'):
        releases.build(source, target, wheelhouse=wheelhouse)
    assert len(checks) == 1 and not target.exists()


def test_real_signature_verification_rejects_tampering_before_extraction(source, tmp_path):
    review = tmp_path / 'review.tar.gz'
    releases.build(source, review, development=True)
    public = tmp_path / 'signed-fixture.tar.gz'
    # A tiny publisher fixture, not a distributable Freo artifact.
    with tarfile.open(review) as old, tarfile.open(public, 'w:gz') as new:
        for member in old:
            data = old.extractfile(member).read()
            if member.name == 'release.json':
                manifest = json.loads(data)
                manifest['development'] = False
                data = json.dumps(manifest).encode()
                member.size = len(data)
            new.addfile(member, io.BytesIO(data))
    home = tmp_path / 'gpg'
    home.mkdir(mode=0o700)
    signature, keyring = tmp_path / 'release.asc', tmp_path / 'publisher.gpg'
    try:
        recovery.run(['gpg', '--homedir', str(home), '--batch', '--pinentry-mode', 'loopback',
                      '--passphrase', '', '--quick-generate-key', 'Fixture <fixture@example.test>', 'ed25519', 'sign', '0'])
        keyring.write_bytes(recovery.run(['gpg', '--homedir', str(home), '--export']))
        recovery.run(['gpg', '--homedir', str(home), '--batch', '--armor', '--detach-sign',
                      '--output', str(signature), str(public)])
        destination = tmp_path / 'release'
        previous_umask = os.umask(0o077)
        try:
            manifest = releases.extract_verified(public, destination, signature=signature, keyring=keyring)
        finally:
            os.umask(previous_umask)
        assert manifest['version'] == '0.2.0' and (destination / 'app/main.py').is_file()
        assert stat.S_IMODE((destination / 'app').stat().st_mode) == 0o755
        with public.open('ab') as stream:
            stream.write(b'tampered')
        with pytest.raises(recovery.RecoveryError, match='gpgv failed'):
            releases.extract_verified(public, tmp_path / 'rejected', signature=signature, keyring=keyring)
        assert not (tmp_path / 'rejected').exists()
    finally:
        recovery.run(['gpgconf', '--homedir', str(home), '--kill', 'gpg-agent'])
