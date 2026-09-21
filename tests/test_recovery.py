"""Recovery must never initialize Flask or inherit production database settings."""
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn
import pytest

from freo_ops import recovery
from freo_ops.__main__ import configuration, passphrase


def test_configuration_uses_only_explicit_file(tmp_path, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'production-must-not-be-used')
    path = tmp_path / 'env'
    path.write_text('DATABASE_URL=postgresql://fixture@localhost/fixture\nOTHER=${DATABASE_URL}\n')
    values = configuration(path)
    assert values['DATABASE_URL'] == 'postgresql://fixture@localhost/fixture'
    assert values['OTHER'] == '${DATABASE_URL}'
    path.write_text('SECRET_KEY=private\n')
    with pytest.raises(recovery.RecoveryError, match='lacks DATABASE_URL'):
        configuration(path)


def test_pg_environment_cannot_inherit_production(monkeypatch):
    monkeypatch.setenv('PGDATABASE', 'live')
    monkeypatch.setenv('PGPASSWORD', 'live-password')
    monkeypatch.setenv('PGSERVICE', 'production')
    values = recovery.pg_environment('postgresql://fixture@/isolated?host=/tmp/test')
    assert values['PGDATABASE'] == 'isolated'
    assert values['PGHOST'] == '/tmp/test'
    assert 'PGPASSWORD' not in values and 'PGSERVICE' not in values


def test_passphrase_file_must_be_private_and_not_a_link(tmp_path):
    path = tmp_path / 'secret'
    path.write_text('private-passphrase\n')
    path.chmod(0o644)
    with pytest.raises(recovery.RecoveryError):
        passphrase(path)
    path.chmod(0o600)
    assert passphrase(path) == b'private-passphrase'
    link = tmp_path / 'link'
    link.symlink_to(path)
    with pytest.raises(OSError):
        passphrase(link)


@pytest.mark.parametrize('name,kind', [('../escape', 'file'), ('/escape', 'file'),
                                      ('objects/1', 'symlink'), ('objects/1', 'hardlink'),
                                      ('unknown', 'file')])
def test_archive_cannot_escape_or_create_links(name, kind):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w') as archive:
        member = tarfile.TarInfo(name)
        if kind != 'file':
            member.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
            member.linkname = '/etc/passwd'
        archive.addfile(member)
    data.seek(0)
    with tarfile.open(fileobj=data, mode='r') as archive:
        with pytest.raises(recovery.RecoveryError):
            list(recovery.safe_members(archive))


def test_inventory_records_links_without_reading_their_targets(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'link').symlink_to('/does/not/exist')
    result = recovery.file_inventory([source])
    assert result[1]['target'] == '/does/not/exist'
    with pytest.raises(recovery.RecoveryError):
        recovery.normalize_roots([source / 'link'])


@pytest.fixture
def postgres():
    url = os.environ.get('FREO_TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Run scripts/test-recovery-postgres.sh for an isolated cluster')
    created = []
    connection = recovery.connect(url)
    connection.autocommit = True
    def new_database(encoding=None):
        name = 'recovery_test_' + uuid.uuid4().hex
        with connection.cursor() as cursor:
            query = sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name))
            if encoding:
                query += sql.SQL(' ENCODING {}').format(sql.Literal(encoding))
            cursor.execute(query)
        created.append(name)
        values = parse_dsn(url)
        values['dbname'] = name
        return make_dsn(**values)
    yield url, new_database, created
    with connection.cursor() as cursor:
        for name in created:
            assert name.startswith(('recovery_test_', 'freo_restore_'))
            cursor.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    connection.close()


def populated(url):
    connection = recovery.connect(url)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE alembic_version (version_num text NOT NULL)')
            cursor.execute("INSERT INTO alembic_version VALUES ('fixture-revision')")
            cursor.execute('CREATE TABLE stations (id serial PRIMARY KEY, uuid text, name text, settings jsonb)')
            cursor.execute("INSERT INTO stations (uuid,name,settings) VALUES ('stable-id','Original station',%s)",
                           (json.dumps({'enabled': False, 'timezone': 'Australia/Perth', 'name': 'Freo'}),))
            cursor.execute('CREATE TABLE artwork (id serial PRIMARY KEY, image bytea NOT NULL)')
            cursor.execute('INSERT INTO artwork (image) VALUES (%s)', (psycopg2.Binary(b'\x00\xfforiginal-image'),))
            cursor.execute('CREATE TABLE pending_imports (id text PRIMARY KEY, station_id int REFERENCES stations(id), status text)')
            cursor.execute("INSERT INTO pending_imports VALUES ('pending-job',1,'ready')")
    connection.close()


def test_encrypted_backup_restore_preserves_database_files_and_metadata(postgres, tmp_path):
    target_url, new_database, created = postgres
    source_url = new_database()
    populated(source_url)
    root = tmp_path / 'state'
    root.mkdir()
    audio = root / 'original.wav'
    audio.write_bytes(b'RIFF' + bytes(range(256)) * 100)
    audio.chmod(0o640)
    os.setxattr(audio, 'user.freo-test', b'preserved')
    (root / 'internal').symlink_to(audio)
    (root / 'external').symlink_to('/etc/never-follow-this')
    output = tmp_path / 'recovery.gpg'
    result = recovery.create(source_url, [root], output, b'fixture-secret', version='0.1.0')
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert b'Original station' not in output.read_bytes()
    with recovery.unpack(output, b'fixture-secret') as (_, manifest):
        assert manifest['backup_id'] == result['backup_id']
        assert manifest['tables']['stations']['rows'] == 1
    restored = tmp_path / 'restored'
    report = recovery.restore(output, b'fixture-secret', target_url, restored)
    created.append(report['database'])
    assert report['status'] == 'verified'
    assert report['schema_revision'] == 'fixture-revision'
    assert (restored / 'root-0/original.wav').read_bytes() == audio.read_bytes()
    assert stat.S_IMODE((restored / 'root-0/original.wav').stat().st_mode) == 0o640
    assert os.getxattr(restored / 'root-0/original.wav', 'user.freo-test') == b'preserved'
    assert (restored / 'root-0/internal').resolve() == restored / 'root-0/original.wav'
    assert not (restored / 'root-0/external').exists()
    assert len(report['unresolved_symlinks']) == 1
    connection = recovery.connect(source_url)
    with connection.cursor() as cursor:
        cursor.execute('SELECT name FROM stations')
        assert cursor.fetchone()[0] == 'Original station'
    connection.close()
    with pytest.raises(recovery.RecoveryError, match='already exists'):
        recovery.create(source_url, [root], output, b'fixture-secret', version='0.1.0')
    with pytest.raises(recovery.RecoveryError, match='must not exist'):
        recovery.restore(output, b'fixture-secret', target_url, restored)
    with pytest.raises(recovery.RecoveryError, match='gpg failed'):
        with recovery.unpack(output, b'incorrect'):
            pass
    with recovery.unpack(output, b'fixture-secret') as (payload, manifest):
        (payload / 'database.dump').write_bytes(b'corrupted')
        with pytest.raises(recovery.RecoveryError, match='checksum'):
            recovery.validate_payload(payload, manifest)


@pytest.mark.parametrize('legacy_manifest', [False, True])
def test_restore_retains_unicode_when_target_template_uses_different_encoding(postgres, tmp_path, monkeypatch, legacy_manifest):
    from contextlib import contextmanager
    target_url, new_database, created = postgres
    source_url = new_database(encoding='UTF8')
    populated(source_url)
    title = 'Beyoncé — 東京 🎵'
    connection = recovery.connect(source_url)
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('UPDATE stations SET name=%s', (title,))
    connection.close()
    root = tmp_path / 'state'
    root.mkdir()
    bundle = tmp_path / 'unicode.gpg'
    recovery.create(source_url, [root], bundle, b'fixture-secret', version='0.1.0')
    unpack = recovery.unpack
    if legacy_manifest:
        @contextmanager
        def old_manifest(*args, **kwargs):
            with unpack(*args, **kwargs) as (payload, manifest):
                manifest.pop('database_encoding')
                yield payload, manifest
        monkeypatch.setattr(recovery, 'unpack', old_manifest)
    report = recovery.restore(bundle, b'fixture-secret', target_url, tmp_path / 'restored')
    created.append(report['database'])
    assert report['status'] == 'verified' and report['database_encoding'] == 'UTF8'
    params = parse_dsn(target_url)
    params['dbname'] = report['database']
    connection = recovery.connect(make_dsn(**params))
    with connection.cursor() as cursor:
        cursor.execute('SELECT name FROM stations')
        assert cursor.fetchone()[0] == title
        cursor.execute('SHOW server_encoding')
        assert cursor.fetchone()[0] == 'UTF8'
    connection.close()


def test_connected_clients_prevent_backup(postgres, tmp_path):
    _, new_database, _ = postgres
    url = new_database()
    populated(url)
    source = tmp_path / 'state'
    source.mkdir()
    connection = recovery.connect(url)
    try:
        with pytest.raises(recovery.RecoveryError, match='clients remain connected'):
            recovery.create(url, [source], tmp_path / 'backup.gpg', b'private', version='0.1.0')
        assert not (tmp_path / 'backup.gpg').exists()
    finally:
        connection.close()
