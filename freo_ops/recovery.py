"""Encrypted recovery bundles and non-overwriting, isolated restores.

No Flask initialization, environment auto-loading, service control or shell commands.
The caller must quiesce writers before create(); the CLI checks systemd as well.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import parse_dsn


class RecoveryError(Exception):
    pass


def run(args, **kwargs):
    """Do not surface database URLs, credentials or dump contents in errors."""
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **kwargs)
    if result.returncode:
        error = RecoveryError(f'{Path(args[0]).name} failed (exit {result.returncode}); operation not completed')
        error.private_diagnostics = result.stderr[-65536:]
        raise error
    return result.stdout


def connect(url):
    inherited = {key: value for key, value in os.environ.items() if key.startswith('PG')}
    try:
        for key in inherited:
            os.environ.pop(key, None)
        return psycopg2.connect(url, connect_timeout=10,
                               options='-c timezone=UTC -c application_name=freo-recovery')
    except psycopg2.Error:
        raise RecoveryError('Cannot connect to the explicitly configured PostgreSQL database') from None
    finally:
        os.environ.update(inherited)


def pg_environment(url):
    values = parse_dsn(url)
    # Libpq parameters are passed only through a private subprocess environment.
    allowed = {'host', 'hostaddr', 'port', 'dbname', 'user', 'password', 'sslmode',
               'sslcert', 'sslkey', 'sslrootcert', 'sslcrl', 'channel_binding',
               'target_session_attrs', 'service', 'passfile', 'sslpassword'}
    if set(values) - allowed:
        raise RecoveryError('Unsupported database connection parameter')
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    names = {'dbname': 'PGDATABASE', 'channel_binding': 'PGCHANNELBINDING',
             'target_session_attrs': 'PGTARGETSESSIONATTRS'}
    env.update({names.get(k, 'PG' + k.upper()): v for k, v in values.items()})
    env.update(PGCONNECT_TIMEOUT='10', PGOPTIONS='-c timezone=UTC',
               PGAPPNAME='freo-recovery')
    return env


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def database_inventory(connection):
    """Deterministic table-content signatures, including values and duplicates."""
    result = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
        tables = [r[0] for r in cursor.fetchall()]
    for table in tables:
        checksum = hashlib.sha256()
        count = 0
        with connection.cursor(name='recovery_' + uuid.uuid4().hex) as cursor:
            cursor.itersize = 1000
            cursor.execute(sql.SQL('SELECT value FROM (SELECT row_to_json(t)::text AS value FROM public.{} t) rows ORDER BY value COLLATE "C"').format(sql.Identifier(table)))
            for (value,) in cursor:
                encoded = value.encode('utf-8')
                checksum.update(len(encoded).to_bytes(8, 'big'))
                checksum.update(encoded)
                count += 1
        result[table] = {'rows': count, 'sha256': checksum.hexdigest()}
    return result


def sequence_inventory(connection):
    result = {}
    with connection.cursor() as cursor:
        cursor.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")
        for name in [r[0] for r in cursor.fetchall()]:
            cursor.execute(sql.SQL('SELECT last_value, is_called FROM public.{}').format(sql.Identifier(name)))
            result[name] = list(cursor.fetchone())
    return result


def schema_revision(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('public.alembic_version')")
        if not cursor.fetchone()[0]:
            raise RecoveryError('Database has no Freo migration revision; refusing to guess')
        cursor.execute('SELECT version_num FROM public.alembic_version ORDER BY version_num')
        revisions = [r[0] for r in cursor.fetchall()]
        if len(revisions) != 1:
            raise RecoveryError('Expected exactly one installed migration revision')
        return revisions[0]


def validate_media_references(connection, roots, entries, media_root=None, upload_root=None):
    files = {str(root / entry['path']): entry for entry in entries
             if entry['kind'] == 'file' for root in [roots[entry['root']]]}
    def require(path, checksum=None, size=None):
        entry = files.get(str(path))
        if entry is None or (checksum and entry['sha256'] != checksum) or (size and entry['size'] != size):
            raise RecoveryError('A referenced original/upload is missing or differs from its database checksum; backup refused')
    with connection.cursor() as cursor:
        if media_root:
            for table, directory, deleted in (('tracks', 'originals', ' AND m.deleted_at IS NULL'),
                                               ('imaging_assets', 'imaging', '')):
                cursor.execute(sql.SQL('SELECT s.slug, m.storage_key, m.checksum_sha256, m.file_size_bytes '
                                       'FROM {} m JOIN stations s ON s.id=m.station_id '
                                       "WHERE m.ingest_status='accepted' AND m.decommissioned_at IS NULL{}")
                               .format(sql.Identifier(table), sql.SQL(deleted)))
                for slug, key, checksum, size in cursor:
                    require(Path(media_root) / slug / directory / key, checksum, size)
        if upload_root:
            cursor.execute("SELECT id, checksum, size_bytes FROM music_import_items WHERE status IN ('pending','preparing','ready')")
            for identifier, checksum, size in cursor:
                require(Path(upload_root) / identifier, checksum, size)
            cursor.execute("SELECT id FROM media_ingest_jobs WHERE status IN ('pending','processing') AND kind IN ('ingest','imaging')")
            for (identifier,) in cursor:
                require(Path(upload_root) / identifier)


def normalize_roots(roots):
    if not roots:
        raise RecoveryError('At least one durable filesystem root is required')
    selected = []
    for raw in sorted(set(map(str, roots)), key=lambda s: (len(Path(s).parts), s)):
        path = Path(raw).absolute()
        if path == Path('/') or not path.exists() or path.is_symlink():
            raise RecoveryError('Backup roots must be existing regular files/directories, never / or symlinks')
        if path.resolve() != path:
            raise RecoveryError('Backup root contains a symlink or non-canonical path')
        if not any(path == p or path.is_relative_to(p) for p in selected):
            selected.append(path)
    return selected


def file_inventory(roots, objects=None):
    entries = []
    def visit(path, root_index, relative):
        before = path.lstat()
        entry = dict(root=root_index, path=relative, mode=stat.S_IMODE(before.st_mode),
                     uid=before.st_uid, gid=before.st_gid, mtime_ns=before.st_mtime_ns)
        if stat.S_ISLNK(before.st_mode):
            entry.update(kind='symlink', target=os.readlink(path))
        elif stat.S_ISDIR(before.st_mode):
            entry['kind'] = 'directory'
        elif stat.S_ISREG(before.st_mode):
            entry.update(kind='file', size=before.st_size, object=f'objects/{len(entries)}')
            # Refuse a file changed to a symlink between lstat and open.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            checksum = hashlib.sha256()
            target = None
            try:
                with os.fdopen(fd, 'rb') as source:
                    if os.fstat(source.fileno()).st_ino != before.st_ino:
                        raise RecoveryError('File changed during backup')
                    if objects:
                        target = (objects.parent / entry['object']).open('xb')
                    while chunk := source.read(1024 * 1024):
                        checksum.update(chunk)
                        if target:
                            target.write(chunk)
                entry['sha256'] = checksum.hexdigest()
            finally:
                if target:
                    target.close()
        else:
            raise RecoveryError('Unsupported special file in durable storage; inventory requires review')
        if entry['kind'] != 'symlink':
            entry['xattrs'] = {k: base64.b64encode(os.getxattr(path, k, follow_symlinks=False)).decode('ascii')
                              for k in os.listxattr(path, follow_symlinks=False)}
        after = path.lstat()
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RecoveryError('Durable files changed during backup; stop all writers and retry')
        entries.append(entry)
        if entry['kind'] == 'directory':
            for child in sorted(path.iterdir()):
                visit(child, root_index, child.name if relative == '.' else relative + '/' + child.name)
    for index, root in enumerate(roots):
        visit(root, index, '.')
    return entries


def _crypto(source, target, passphrase, directory, decrypt=False):
    if not passphrase or b'\n' in passphrase or b'\r' in passphrase or b'\0' in passphrase:
        raise RecoveryError('Backup passphrase must be nonempty and contain no newline or NUL')
    home = directory / 'gnupg'
    home.mkdir(mode=0o700, exist_ok=True)
    # The passphrase travels through stdin, not argv, logs or the environment.
    args = ['gpg', '--homedir', str(home), '--no-options', '--batch', '--yes',
            '--pinentry-mode', 'loopback', '--passphrase-fd', '0', '--no-symkey-cache',
            '--output', str(target)]
    args += ['--decrypt'] if decrypt else ['--symmetric', '--cipher-algo', 'AES256']
    run(args + [str(source)], input=passphrase + b'\n')


def safe_members(archive):
    seen = set()
    for member in archive:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or '..' in path.parts or member.name in seen
                or not (member.isfile() or member.isdir())
                or not (member.name in ('manifest.json', 'database.dump', 'objects')
                        or (len(path.parts) == 2 and path.parts[0] == 'objects' and path.parts[1].isdigit()))):
            raise RecoveryError('Invalid backup archive member')
        seen.add(member.name)
        yield member


@contextmanager
def unpack(bundle, passphrase):
    with tempfile.TemporaryDirectory(prefix='freo-recovery-') as name:
        directory = Path(name)
        archive_path = directory / 'bundle.tar'
        _crypto(Path(bundle), archive_path, passphrase, directory, decrypt=True)
        payload = directory / 'payload'
        payload.mkdir(mode=0o700)
        with tarfile.open(archive_path, 'r:') as archive:
            for member in safe_members(archive):
                target = payload / member.name
                if member.isdir():
                    target.mkdir(mode=0o700, exist_ok=True)
                else:
                    target.parent.mkdir(mode=0o700, exist_ok=True)
                    with archive.extractfile(member) as source, target.open('xb') as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o600)
        try:
            manifest = json.loads((payload / 'manifest.json').read_text())
            validate_payload(payload, manifest)
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise RecoveryError('Invalid or incomplete backup manifest/payload') from error
        yield payload, manifest


def validate_payload(payload, manifest):
    if manifest['format'] != 1 or manifest['status'] != 'complete':
        raise RecoveryError('Unsupported or incomplete backup')
    if digest(payload / 'database.dump') != manifest['database_sha256']:
        raise RecoveryError('Database dump checksum mismatch')
    seen, objects = set(), {'manifest.json', 'database.dump'}
    for entry in manifest['entries']:
        index, relative = entry['root'], PurePosixPath(entry['path'])
        if (type(index) is not int or not 0 <= index < len(manifest['roots'])
                or relative.is_absolute() or '..' in relative.parts
                or (index, str(relative)) in seen):
            raise RecoveryError('Invalid filesystem entry')
        seen.add((index, str(relative)))
        if entry['kind'] == 'file':
            obj = PurePosixPath(entry['object'])
            if len(obj.parts) != 2 or obj.parts[0] != 'objects' or not obj.parts[1].isdigit():
                raise RecoveryError('Invalid file object')
            path = payload / str(obj)
            if str(obj) in objects or path.stat().st_size != entry['size'] or digest(path) != entry['sha256']:
                raise RecoveryError('File checksum/size mismatch or duplicate object')
            objects.add(str(obj))
        elif entry['kind'] not in ('directory', 'symlink'):
            raise RecoveryError('Invalid file kind')
        if not 0 <= entry['mode'] <= 0o7777:
            raise RecoveryError('Invalid file permissions')
        for value in entry.get('xattrs', {}).values():
            base64.b64decode(value, validate=True)
    kinds = {(e['root'], e['path']): e['kind'] for e in manifest['entries']}
    for entry in manifest['entries']:
        if entry['path'] != '.':
            parent = str(PurePosixPath(entry['path']).parent)
            if kinds.get((entry['root'], parent)) != 'directory':
                raise RecoveryError('File entry parent is not a directory')
    actual = {str(p.relative_to(payload)) for p in payload.rglob('*') if p.is_file()}
    if actual != objects:
        raise RecoveryError('Unlisted or missing backup object')


def create(url, roots, destination, passphrase, *, version, media_root=None, upload_root=None):
    roots = normalize_roots(roots)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise RecoveryError('Backup destination already exists')
    if any(destination.is_relative_to(root) for root in roots):
        raise RecoveryError('Backup destination must be outside captured roots')
    connection = connect(url)
    try:
        connection.set_session(isolation_level='REPEATABLE READ', readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(717304021)")
            if not cursor.fetchone()[0]:
                raise RecoveryError('Another recovery operation holds the database lock')
            cursor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'")
            if cursor.fetchone()[0]:
                raise RecoveryError('Database clients remain connected; stop all writers before backup')
            cursor.execute("SELECT pg_export_snapshot(), current_setting('server_version'), current_setting('server_encoding')")
            snapshot, server_version, database_encoding = cursor.fetchone()
        revision = schema_revision(connection)
        tables, sequences = database_inventory(connection), sequence_inventory(connection)
        with tempfile.TemporaryDirectory(prefix='freo-backup-') as name:
            work = Path(name)
            payload = work / 'payload'
            payload.mkdir(mode=0o700)
            (payload / 'objects').mkdir(mode=0o700)
            run(['pg_dump', '--format=custom', '--snapshot=' + snapshot,
                 '--file=' + str(payload / 'database.dump')], env=pg_environment(url))
            entries = file_inventory(roots, payload / 'objects')
            validate_media_references(connection, roots, entries, media_root, upload_root)
            if entries != file_inventory(roots):
                raise RecoveryError('Filesystem changed during backup; retry with all writers stopped')
            manifest = dict(format=1, status='complete', backup_id=uuid.uuid4().hex,
                            created_at=datetime.now(timezone.utc).isoformat(), version=version,
                            schema_revision=revision, postgres_version=server_version,
                            database_encoding=database_encoding,
                            roots=[str(p) for p in roots], entries=entries,
                            database_sha256=digest(payload / 'database.dump'),
                            tables=tables, sequences=sequences)
            # A fresh transaction catches changes made outside the exported snapshot.
            connection.commit()
            if tables != database_inventory(connection) or sequences != sequence_inventory(connection):
                raise RecoveryError('Database changed during backup; stop all writers and retry')
            (payload / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True))
            archive_path = work / 'bundle.tar'
            with tarfile.open(archive_path, 'w') as archive:
                for path in sorted(payload.rglob('*')):
                    archive.add(path, arcname=str(path.relative_to(payload)), recursive=False)
            # Encrypt beside destination; publish with a no-overwrite hard link.
            with tempfile.TemporaryDirectory(prefix='.freo-backup-', dir=destination.parent) as out:
                encrypted = Path(out) / 'bundle.gpg'
                _crypto(archive_path, encrypted, passphrase, work)
                encrypted.chmod(0o600)
                with encrypted.open('rb') as stream:
                    os.fsync(stream.fileno())
                with unpack(encrypted, passphrase):
                    pass
                os.link(encrypted, destination)
                fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            return {k: manifest[k] for k in ('backup_id', 'version', 'schema_revision')}
    finally:
        connection.close()


def restore_files(payload, manifest, target, preserve_ownership=False):
    target = Path(target)
    target.mkdir(mode=0o700)  # Never merge with an existing directory.
    roots = [target / f'root-{i}' for i in range(len(manifest['roots']))]
    links = []
    entries = sorted(manifest['entries'], key=lambda e: (len(PurePosixPath(e['path']).parts), e['path']))
    for entry in entries:
        path = roots[entry['root']] / entry['path']
        if entry['kind'] == 'directory':
            path.mkdir(mode=0o700)
        elif entry['kind'] == 'file':
            with (payload / entry['object']).open('rb') as source, path.open('xb') as output:
                shutil.copyfileobj(source, output)
            if digest(path) != entry['sha256']:
                raise RecoveryError('Restored file failed checksum verification')
        else:
            links.append(entry)
    # Restore links only within the recovered tree. External host links remain
    # in the report for deliberate reattachment, never point into the live host.
    unresolved = []
    for entry in links:
        source = Path(manifest['roots'][entry['root']]) / entry['path']
        resolved = Path(os.path.normpath(str(source.parent / entry['target'])))
        path = roots[entry['root']] / entry['path']
        for index, original in enumerate(map(Path, manifest['roots'])):
            if resolved == original or resolved.is_relative_to(original):
                mapped = roots[index] / resolved.relative_to(original)
                path.symlink_to(os.path.relpath(mapped, path.parent))
                break
        else:
            unresolved.append(entry)
    for entry in reversed(entries):
        if entry['kind'] == 'symlink':
            continue
        path = roots[entry['root']] / entry['path']
        if preserve_ownership:
            os.chown(path, entry['uid'], entry['gid'])
        os.chmod(path, entry['mode'])
        for key, value in entry.get('xattrs', {}).items():
            os.setxattr(path, key, base64.b64decode(value))
        os.utime(path, ns=(entry['mtime_ns'], entry['mtime_ns']))
    return unresolved


def restore(bundle, passphrase, target_url, directory, *, preserve_ownership=False):
    """Create a uniquely named DB; never drop, clean or overwrite any database."""
    directory = Path(directory).absolute()
    if directory.exists() or directory.is_symlink():
        raise RecoveryError('Restore directory must not exist')
    with unpack(bundle, passphrase) as (payload, manifest):
        encoding = manifest.get('database_encoding')
        if encoding is None:
            # Original format-1 bundles carry encoding in the custom dump rather
            # than the manifest. Read schema output without executing any SQL.
            schema = run(['pg_restore', '--schema-only', '--file=-', str(payload / 'database.dump')])
            encodings = re.findall(rb"^SET client_encoding = '([A-Za-z0-9_-]+)';$", schema, re.MULTILINE)
            if len(encodings) != 1:
                raise RecoveryError('Cannot determine source database encoding; restore refused')
            encoding = encodings[0].decode('ascii')
        if not isinstance(encoding, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', encoding):
            raise RecoveryError('Invalid source database encoding')
        unresolved = restore_files(payload, manifest, directory, preserve_ownership)
        name = 'freo_restore_' + uuid.uuid4().hex
        report = dict(backup_id=manifest['backup_id'], database=name, status='incomplete',
                      roots=manifest['roots'], unresolved_symlinks=unresolved,
                      ownership_restored=preserve_ownership, database_encoding=encoding)
        report_path = directory / 'restore-report.json'
        report_path.write_text(json.dumps(report, indent=2))
        connection = connect(target_url)
        try:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING {}').format(
                    sql.Identifier(name), sql.Literal(encoding)))
        finally:
            connection.close()
        params = parse_dsn(target_url)
        params['dbname'] = name
        from psycopg2.extensions import make_dsn
        restored_url = make_dsn(**params)
        run(['pg_restore', '--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges',
             '--dbname=' + name, str(payload / 'database.dump')], env=pg_environment(restored_url))
        connection = connect(restored_url)
        try:
            if (database_inventory(connection) != manifest['tables']
                    or sequence_inventory(connection) != manifest['sequences']
                    or schema_revision(connection) != manifest['schema_revision']):
                raise RecoveryError('Restored database differs from the recorded recovery point')
        finally:
            connection.close()
        report.update(status='verified', schema_revision=manifest['schema_revision'],
                      version=manifest['version'])
        report_path.write_text(json.dumps(report, indent=2))
        report_path.chmod(0o600)
        return report
