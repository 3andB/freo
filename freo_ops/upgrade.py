"""Explicit maintenance-window upgrades. Never initialize or replace an existing DB."""
import base64
import fcntl
import grp
from http.client import HTTPException
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import time
from urllib.request import build_opener, ProxyHandler
import uuid

from psycopg2.extensions import make_dsn, parse_dsn

from . import recovery, releases


def wait_for_station_audio(opener, slug, timeout=60):
    """Allow an active Liquidsoap process time to connect its Icecast mount."""
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            with opener.open('http://127.0.0.1:8001/' + slug, timeout=min(3, remaining)) as response:
                if (response.status == 200
                        and response.headers.get_content_type().startswith('audio/')
                        and response.read(4096)):
                    return
        except (OSError, HTTPException):
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise recovery.RecoveryError('A previously active station did not deliver audio before the startup deadline: ' + slug)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_release(path):
    paths = list(path.rglob('*'))
    for entry in paths:
        if entry.is_file() and not entry.is_symlink():
            with entry.open('rb') as stream:
                os.fsync(stream.fileno())
    for entry in reversed(paths):
        if entry.is_dir() and not entry.is_symlink():
            sync_directory(entry)
    sync_directory(path)
    sync_directory(path.parent)


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.journal-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def release_environment(values, env_file):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('FREO_', 'FLASK_', 'PG', 'MAX_MEDIA_'))
           and key not in ('DATABASE_URL', 'SECRET_KEY', 'PUBLIC_BASE_URL', 'LOG_LEVEL', 'PYTHONPATH', 'PYTHONHOME')}
    env.update({key: value for key, value in values.items() if value is not None})
    env.update(FREO_ENV_FILE=str(env_file), FLASK_ENV='production', PYTHONNOUSERSITE='1')
    return env


def rewrite_unit(body):
    body = body.replace('/opt/freo/current/', '/opt/freo/').replace('WorkingDirectory=/opt/freo/current\n', 'WorkingDirectory=/opt/freo\n')
    return body.replace('EnvironmentFile=/opt/freo/.env', 'EnvironmentFile=/etc/freo/freo.env').replace(
        '--env-file /opt/freo/.env', '--env-file /etc/freo/freo.env').replace(
        '/opt/freo/', '/opt/freo/current/').replace('WorkingDirectory=/opt/freo\n', 'WorkingDirectory=/opt/freo/current\n')


def switch_pointer(root, release):
    temporary = root / ('.current-' + uuid.uuid4().hex)
    temporary.symlink_to(release)
    os.replace(temporary, root / 'current')
    sync_directory(root)


def require_root_directory(path, *, private=False):
    info = path.lstat()
    forbidden = 0o077 if private else 0o022
    if path.is_symlink() or not path.is_dir() or info.st_uid != 0 or info.st_mode & forbidden:
        raise recovery.RecoveryError('Privileged upgrade directories must be root-owned with restricted permissions')


def maintenance_guards(state):
    """A reboot during migration must not restart enabled old/new workers."""
    body = '[Unit]\nConditionPathExists=!' + str(state / 'maintenance') + '\n'
    for unit in Path('/etc/systemd/system').glob('freo*'):
        if not unit.is_file() or unit.suffix not in ('.service', '.timer'):
            continue
        directory = unit.with_name(unit.name + '.d')
        if directory.is_symlink():
            raise recovery.RecoveryError('Symlinked service overrides require adoption review')
        directory.mkdir(mode=0o755, exist_ok=True)
        require_root_directory(directory)
        guard = directory / '00-freo-upgrade-guard.conf'
        if guard.exists():
            if guard.is_symlink() or guard.read_text() != body:
                raise recovery.RecoveryError('An unmanaged maintenance guard already exists')
        else:
            with guard.open('x') as stream:
                stream.write(body)
                stream.flush()
                os.fchmod(stream.fileno(), 0o644)
                os.fsync(stream.fileno())
            sync_directory(directory)
    sync_directory(Path('/etc/systemd/system'))
    recovery.run(['systemctl', 'daemon-reload'])


def set_maintenance(state, enabled):
    marker = state / 'maintenance'
    if enabled:
        atomic_json(marker, {'maintenance': True})
    else:
        marker.unlink(missing_ok=True)


def verify_preservation(source_url, restored_url):
    old, new = recovery.connect(restored_url), recovery.connect(source_url)
    try:
        old.set_session(isolation_level='REPEATABLE READ', readonly=True)
        new.set_session(isolation_level='REPEATABLE READ', readonly=True)
        # One reviewed data migration: transform only the expected backup value,
        # never the actual upgraded row. Same-schema recovery stays byte-exact.
        primary_admin_grant = (
            recovery.schema_revision(old) == 'f39c8210b7de'
            and recovery.schema_revision(new) in ('a64f09e2b731', 'b72e19d4c603', 'c83d4e5f9012')
        )
        with old.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename!='alembic_version' ORDER BY tablename")
            tables = [row[0] for row in cursor.fetchall()]
        from psycopg2 import sql
        for table in tables:
            with old.cursor() as cursor:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (table,))
                columns = [row[0] for row in cursor.fetchall()]
            with new.cursor() as cursor:
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s", (table,))
                available = {row[0] for row in cursor.fetchall()}
            if not set(columns).issubset(available):
                raise recovery.RecoveryError('Migration removed pre-existing columns; activation refused')
            query = sql.SQL('SELECT value FROM (SELECT row_to_json(t)::text AS value FROM '
                            '(SELECT {} FROM public.{}) t) rows ORDER BY value COLLATE "C"').format(
                                sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table))
            expected_query = query
            if primary_admin_grant and table == 'admin_users' and {'username', 'installation_admin'} <= set(columns):
                expected_columns = [
                    sql.SQL("CASE WHEN username = 'admin' THEN true ELSE installation_admin END AS installation_admin")
                    if column == 'installation_admin' else sql.Identifier(column)
                    for column in columns
                ]
                expected_query = sql.SQL(
                    'SELECT value FROM (SELECT row_to_json(t)::text AS value FROM '
                    '(SELECT {} FROM public.{}) t) rows ORDER BY value COLLATE "C"'
                ).format(sql.SQL(',').join(expected_columns), sql.Identifier(table))
            # Compare the original columns as a sorted multiset. New columns,
            # tables and seed rows are allowed; every prior row must survive.
            with old.cursor(name='old_' + uuid.uuid4().hex) as prior, new.cursor(name='new_' + uuid.uuid4().hex) as current:
                prior.execute(expected_query)
                current.execute(query)
                candidate = next(current, None)
                for original in prior:
                    while candidate is not None and candidate[0] < original[0]:
                        candidate = next(current, None)
                    if candidate != original:
                        raise recovery.RecoveryError('Migration changed pre-existing records; activation refused')
                    candidate = next(current, None)
        current_sequences = recovery.sequence_inventory(new)
        for name, (value, called) in recovery.sequence_inventory(old).items():
            current_sequence = current_sequences.get(name)
            if current_sequence is None or current_sequence[0] < value or (called and not current_sequence[1]):
                raise recovery.RecoveryError('Migration regressed a database sequence; activation refused')
    finally:
        old.close()
        new.close()


def upgrade(artifact, signature, keyring, env_file, backup, passphrase, verification_env_file, verification_directory, *, check=False):
    from .__main__ import configuration, inventory, active_units
    if os.geteuid() != 0:
        raise recovery.RecoveryError('Upgrades require root; the web application cannot perform upgrades')
    os_release = platform.freedesktop_os_release()
    if os_release.get('ID') != 'ubuntu' or os_release.get('VERSION_ID') != '24.04' or platform.machine() != 'x86_64':
        raise recovery.RecoveryError('This updater supports Ubuntu 24.04 x86_64 only')
    root = Path('/opt/freo')
    # /var/lib/freo is owned by the web account; privileged journals must not
    # have a parent that account can rename or replace.
    state = Path('/var/lib/freo-updates')
    state.mkdir(mode=0o700, exist_ok=True)
    require_root_directory(state, private=True)
    sync_directory(state.parent)
    lock = (state / 'upgrade.lock').open('a')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise recovery.RecoveryError('An upgrade is already running') from None
        journal_path = state / 'journal.json'
        if journal_path.exists():
            previous = json.loads(journal_path.read_text())
            if previous['phase'] not in ('complete', 'preflight_failed', 'preflight_passed', 'failed_before_migration'):
                raise recovery.RecoveryError('Previous upgrade is unfinished; inspect the journal and recovery guide before proceeding')
        values = configuration(env_file)
        target_values = configuration(verification_env_file)
        roots = inventory(env_file, values)
        verification_directory = Path(verification_directory).absolute()
        if (root / 'current').exists() and not (root / 'current').is_symlink():
            raise recovery.RecoveryError('Release pointer is not a symlink; explicit adoption review required')
        current = (root / 'current').resolve() if (root / 'current').is_symlink() else root
        operation = uuid.uuid4().hex
        release = root / 'releases' / operation
        release.parent.mkdir(mode=0o755, exist_ok=True)
        release.parent.chmod(0o755)
        journal = dict(operation=operation, phase='preflight', release=str(release),
                       previous_release=str(current), backup=str(Path(backup).absolute()),
                       active_units=[], previous_units={})
        atomic_json(journal_path, journal)
        migrated = False
        stopped = False
        try:
            manifest = releases.extract_verified(artifact, release, signature=signature, keyring=keyring)
            if manifest['platform'] != 'ubuntu-24.04-x86_64' or manifest['python'] != '3.12':
                raise recovery.RecoveryError('Release platform is incompatible')
            connection = recovery.connect(values['DATABASE_URL'])
            try:
                revision = recovery.schema_revision(connection)
            finally:
                connection.close()
            if revision not in manifest['supported_source_revisions']:
                raise recovery.RecoveryError('Installed database revision is not a supported upgrade source')
            journal.update(source_revision=revision, target_revision=manifest['schema_head'], version=manifest['version'])
            previous_manifest = current / 'release.json'
            if previous_manifest.is_file():
                installed = json.loads(previous_manifest.read_text())
                if installed == manifest and revision == manifest['schema_head']:
                    journal['phase'] = 'complete'
                    journal['already_installed'] = True
                    atomic_json(journal_path, journal)
                    return dict(status='already_installed', version=manifest['version'])
                if installed.get('version') == manifest['version']:
                    raise recovery.RecoveryError('An installed version cannot be replaced with different release contents')
            if verification_directory.exists() or any(verification_directory.is_relative_to(p) for p in roots):
                raise recovery.RecoveryError('Verification directory must be new and outside all captured roots')
            # Version comparisons never import the staged application into this process.
            from packaging.version import Version
            old_version = releases.version_at(current)
            if Version(manifest['version']) < Version(old_version):
                raise recovery.RecoveryError('Downgrades require a separately reviewed recovery procedure')
            if old_version == manifest['version'] and revision != manifest['schema_head']:
                raise recovery.RecoveryError('Installed code and schema do not form a matched baseline; recover/adopt explicitly before upgrading')
            for directory in ('liquidsoap', 'icecast', 'nginx'):
                for path in (release / 'deploy' / directory).rglob('*'):
                    if path.is_file():
                        old = current / path.relative_to(release)
                        if not old.is_file() or recovery.digest(old) != recovery.digest(path):
                            raise recovery.RecoveryError('Radio/proxy template changes require a separately tested maintenance procedure')
            for override in Path('/etc/systemd/system').glob('freo*.service.d/*.conf'):
                if any(line.startswith(('ExecStart=', 'ExecStartPre=', 'WorkingDirectory=', 'EnvironmentFile='))
                       for line in override.read_text().splitlines()):
                    raise recovery.RecoveryError('Custom service execution overrides require explicit adoption review')
            if not (release / 'requirements.lock').is_file():
                raise recovery.RecoveryError('Release has no hashed dependency lock')
            stable_env = Path('/etc/freo/freo.env')
            if stable_env.exists() and stable_env.read_bytes() != Path(env_file).read_bytes():
                raise recovery.RecoveryError('Stable and supplied environment files differ; refusing to choose one')
            for path in (release / 'deploy/systemd').glob('freo*'):
                target = Path('/etc/systemd/system') / path.name
                old = current / 'deploy/systemd' / path.name
                if target.exists() and (not old.exists() or target.read_text() not in (old.read_text(), rewrite_unit(old.read_text()))):
                    raise recovery.RecoveryError('Customized service unit needs review before replacement')
            needed = sum(p.stat().st_size for p in release.rglob('*') if p.is_file()) * 3
            if shutil.disk_usage(root).free < needed:
                raise recovery.RecoveryError('Insufficient space to stage the release and its virtual environment')
            if Path(backup).exists():
                raise recovery.RecoveryError('Backup destination already exists')
            if check:
                journal['phase'] = 'preflight_passed'
                journal['check_only'] = True
                atomic_json(journal_path, journal)
                return dict(status='preflight_passed', version=manifest['version'], schema_revision=revision,
                            note='Backup/restore, dependency installation and service checks still run during upgrade')
            recovery.run(['python3', '-m', 'venv', str(release / 'venv')], umask=0o022)
            recovery.run([str(release / 'venv/bin/pip'), 'install', '--no-index', '--require-hashes',
                          '--find-links', str(release / 'wheels'), '-r', str(release / 'requirements.lock')], umask=0o022)
            recovery.run([str(release / 'venv/bin/pip'), 'check'])
            sync_release(release)
            # Preserve the precise active unit list; stopped stations remain stopped.
            journal['active_units'] = active_units()
            journal['phase'] = 'stopping'
            atomic_json(journal_path, journal)
            maintenance_guards(state)
            set_maintenance(state, True)
            stopped = True
            if journal['active_units']:
                recovery.run(['systemctl', 'stop', *journal['active_units']])
            if active_units():
                raise recovery.RecoveryError('Freo units remain active; refusing backup/migration')
            journal['phase'] = 'backup'
            atomic_json(journal_path, journal)
            recovery.create(values['DATABASE_URL'], roots, backup, passphrase, version=old_version,
                            media_root=values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media',
                            upload_root=values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads')
            # Verification restores never point at the current DB and never drop a DB.
            verified = recovery.restore(backup, passphrase, target_values['DATABASE_URL'], verification_directory)
            journal['verification_database'] = verified['database']
            journal['verification_directory'] = str(verification_directory)
            journal['phase'] = 'migration'
            atomic_json(journal_path, journal)
            migrated = True  # A killed/nontransactional migration must never be mistaken for no mutation.
            env = release_environment(values, env_file)
            command = ['runuser', '-u', 'freo', '--', str(release / 'venv/bin/flask'), '--app', 'wsgi:app']
            recovery.run(command + ['db', 'upgrade'], cwd=release, env=env)
            recovery.run(command + ['settings', 'import-environment'], cwd=release, env=env)
            restored_params = parse_dsn(target_values['DATABASE_URL'])
            restored_params['dbname'] = verified['database']
            verify_preservation(values['DATABASE_URL'], make_dsn(**restored_params))
            connection = recovery.connect(values['DATABASE_URL'])
            try:
                if recovery.schema_revision(connection) != manifest['schema_head']:
                    raise recovery.RecoveryError('Migration did not reach the release schema')
            finally:
                connection.close()
            stable_env = Path('/etc/freo/freo.env')
            if stable_env.exists():
                if stable_env.read_bytes() != Path(env_file).read_bytes():
                    raise recovery.RecoveryError('Stable and supplied environment files differ; refusing to choose one')
            else:
                with stable_env.open('xb') as stream:
                    stream.write(Path(env_file).read_bytes())
                os.chown(stable_env, 0, grp.getgrnam('freo').gr_gid)
                stable_env.chmod(0o640)
                with stable_env.open('rb') as stream:
                    os.fsync(stream.fileno())
                sync_directory(stable_env.parent)
            # Keep the original unit bodies in the private journal for recovery.
            for path in (release / 'deploy/systemd').glob('freo*'):
                target = Path('/etc/systemd/system') / path.name
                if target.is_file():
                    journal['previous_units'][str(target)] = base64.b64encode(target.read_bytes()).decode('ascii')
            journal['phase'] = 'activation'
            atomic_json(journal_path, journal)
            for filename in journal['previous_units']:
                target = Path(filename)
                source = release / 'deploy/systemd' / target.name
                fd, pending = tempfile.mkstemp(prefix='.freo-unit-', dir=target.parent)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(rewrite_unit(source.read_text()))
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o644)
                    os.fsync(stream.fileno())
                os.replace(pending, target)
                sync_directory(target.parent)
            switch_pointer(root, release)
            recovery.run(['systemctl', 'daemon-reload'])
            journal['phase'] = 'starting'
            atomic_json(journal_path, journal)
            set_maintenance(state, False)
            if journal['active_units']:
                recovery.run(['systemctl', 'start', *journal['active_units']])
            opener = build_opener(ProxyHandler({}))
            if 'freo.service' in journal['active_units']:
                for attempt in range(30):
                    try:
                        with opener.open('http://127.0.0.1:8000/ready', timeout=2) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(1)
                else:
                    raise recovery.RecoveryError('New application did not become ready')
            for unit in journal['active_units']:
                # Timers and long-lived processes must return; one-shot services may finish.
                if unit.endswith('.timer') or unit in ('freo.service', 'freo-automation.service', 'freo-ingest.service',
                                                        'freo-stats.service', 'freo-central-api.service', 'freo-mic.service') or unit.startswith('freo-playout'):
                    recovery.run(['systemctl', 'is-active', '--quiet', unit])
                if unit.startswith('freo-playout@'):
                    slug = unit.removeprefix('freo-playout@').removesuffix('.service')
                    import re
                    if not re.fullmatch(r'[a-z0-9-]+', slug):
                        raise recovery.RecoveryError('Unexpected playout unit identifier')
                    wait_for_station_audio(opener, slug)
            journal['phase'] = 'complete'
            atomic_json(journal_path, journal)
            return dict(status='complete', version=manifest['version'], backup=journal['backup'],
                        verification_database=verified['database'])
        except Exception as error:
            journal['failure_phase'] = journal['phase']
            journal['failure_type'] = type(error).__name__
            diagnostics = getattr(error, 'private_diagnostics', None)
            if diagnostics:
                log = state / (operation + '.stderr.log')
                fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(diagnostics)
                journal['private_diagnostics'] = str(log)
            journal['phase'] = 'recovery_required' if migrated else ('restarting_previous' if stopped else 'preflight_failed')
            atomic_json(journal_path, journal)
            if stopped and not migrated and journal['active_units']:
                set_maintenance(state, False)
                try:
                    recovery.run(['systemctl', 'start', *journal['active_units']])
                except Exception:
                    set_maintenance(state, True)
                    raise
            elif stopped and migrated:
                set_maintenance(state, True)
                if journal['active_units']:
                    recovery.run(['systemctl', 'stop', *journal['active_units']])
            if stopped and not migrated:
                set_maintenance(state, False)
                journal['phase'] = 'failed_before_migration'
                atomic_json(journal_path, journal)
            # After migration/startup, preserve all data and diagnostics. Never
            # automatically rewind a database that may have accepted new writes.
            raise
    finally:
        lock.close()
