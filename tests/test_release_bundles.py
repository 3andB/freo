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
