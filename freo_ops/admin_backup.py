"""Lifecycle coordination around Phase A's encrypted recovery engine."""
from datetime import datetime, timezone
from contextlib import contextmanager
import base64
import tempfile
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from . import admin as a, hosting as h, recovery
from .upgrade import maintenance_guards, set_maintenance, switch_pointer


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):
        raise h.HostingError('invalid_arguments','Backup IDs must contain 32 lowercase hexadecimal characters.')
    return value


def catalog():
    return a.private_directory(a.STATE/'backups')


def record(value):
    path = catalog()/identifier(value)/'metadata.json'
    if not path.exists():
        raise h.HostingError('backup_not_found','No approved backup has that ID.')
    data = a.read_json(path)
    if data['id'] != value:
        raise h.HostingError('invalid_configuration','Backup metadata identity mismatch.')
    return data, path.parent/'bundle.gpg'


def roots():
    from .__main__ import inventory
    from .inventory import DIRECTORIES, FILES
    env, values = a.settings()
    current = a.source()
    paths = inventory(env,values)+[p for p in map(Path,a.media_roots(values)) if p.exists()]
    paths += [current/name for name in (*DIRECTORIES,*FILES,'venv','release.json','wheels','requirements.lock') if (current/name).exists()]
    if Path('/opt/freo/engines').exists(): paths.append(Path('/opt/freo/engines'))
    return recovery.normalize_roots(paths)


def disk_check(paths, *, extra_bytes=0):
    # Phase A uses full copies for encrypt/decrypt/restore. Budget conservatively.
    total = sum(path.stat().st_size for root in paths for path in ([root] if root.is_file() else root.rglob('*')) if path.is_file() and not path.is_symlink())
    _, values = a.settings()
    connection = recovery.connect(values['DATABASE_URL'])
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT pg_database_size(current_database())');total+=cur.fetchone()[0]
    finally: connection.close()
    required = (total+extra_bytes)*6+1_000_000_000
    for path in (a.STATE,Path('/tmp')):
        if shutil.disk_usage(path).free < required:
            raise h.HostingError('insufficient_space','Insufficient free space for full backup/recovery staging.',required_bytes=required)


def freeze(operation):
    if 'active_units' not in operation:
        active = [unit for unit,row in a.units().items() if row['active'] not in ('inactive','failed')]
        if 'freo-updater.service' in active:
            raise h.HostingError('operation_busy','An updater is running; do not interrupt it for a backup.')
        a.checkpoint(operation, active_units=active, was_inhibited=(h.STATE/'inhibit').exists(), phase='stopping')
    a.private_directory(a.UPDATES)
    from .admin_identity import install_maintenance_guards
    install_maintenance_guards()
    maintenance_guards(a.UPDATES)
    # Icecast is independent of Freo units and also needs reboot protection.
    directory=Path('/etc/systemd/system/icecast2.service.d');directory.mkdir(exist_ok=True)
    guard=directory/'00-freo-upgrade-guard.conf'
    body='[Unit]\nConditionPathExists=!/var/lib/freo-updates/maintenance\n'
    if guard.exists() and (guard.is_symlink() or guard.read_text()!=body):
        raise h.HostingError('invalid_configuration','Unmanaged Icecast maintenance guard requires review.')
    guard.write_text(body);guard.chmod(0o644)
    a.run(['systemctl','daemon-reload'])
    set_maintenance(a.UPDATES,True)
    if h.read()['hosted']: h.atomic(h.STATE/'inhibit',True)
    # Timers first so a stop cannot race a new worker start.
    active=a.units()
    timers=[unit for unit in active if unit.endswith('.timer')]
    if timers:a.run(['systemctl','stop',*timers])
    services=[unit for unit in a.units() if unit!='freo-updater.service' and unit.endswith('.service')]
    if services:a.run(['systemctl','stop',*services])
    if any(row['active'] not in ('inactive','failed') for row in a.units().values()):
        raise h.HostingError('verification_failed','Writers did not stop.')
    a.checkpoint(operation,phase='frozen')


def thaw(operation, *, reconcile=False):
    policy=h.read()
    restricted=policy.get('hosted') and (policy['status'] in ('suspended','maintenance') or operation.get('was_inhibited'))
    if policy.get('hosted') and not restricted:
        (h.STATE/'inhibit').unlink(missing_ok=True)
    set_maintenance(a.UPDATES,False)
    selected=[]
    for unit in operation.get('active_units',[]):
        if restricted and (unit=='icecast2.service' or unit=='freo-mic.service' or unit.startswith('freo-playout')): continue
        if unit=='freo-updater.service': continue
        if not re.fullmatch(r'(freo[a-z0-9@_.-]*|icecast2)\.(service|timer)',unit):
            raise h.HostingError('invalid_configuration','Unexpected recorded service.')
        selected.append(unit)
    if reconcile:
        selected.extend(a.required_core())
        for unit in ('freo-central-api.service', *a.GROUPS['scheduled-workers']):
            if subprocess.run(['systemctl','is-enabled','--quiet',unit],capture_output=True,timeout=5).returncode==0:
                selected.append(unit)
        if not restricted:
            selected.append('icecast2.service')
            selected.extend('freo-playout@'+s['slug']+'.service' for s in a.station_rows() if s['enabled'] and s['desired_state']=='running')
            if subprocess.run(['systemctl','is-enabled','--quiet','freo-mic.service'],capture_output=True,timeout=5).returncode==0:
                selected.append('freo-mic.service')
        selected=list(dict.fromkeys(selected))
    a.checkpoint(operation,phase='starting')
    a.run(['systemctl','daemon-reload'])
    if selected:a.run(['systemctl','start',*selected])
    verification=a.verified_health()
    a.checkpoint(operation,phase='complete')
    return verification


def create_frozen(operation, *, role='backup'):
    value=uuid.uuid4().hex
    directory=a.private_directory(catalog()/value)
    env, values=a.settings()
    from .releases import version_at
    metadata=dict(id=value,installation_id=a.read_json(a.STATE/'identity.json')['installation_id'],
                  created_at=datetime.now(timezone.utc).isoformat(),version=version_at(a.source()),
                  source=str(a.source()),env_file=str(env),roots=[str(p) for p in roots()],
                  active_units=operation['active_units'],role=role,status='creating')
    a.write(directory/'metadata.json',metadata)
    a.checkpoint(operation,phase='backup',backup_id=value)
    result=recovery.create(values['DATABASE_URL'],list(map(Path,metadata['roots'])),directory/'bundle.gpg',a.key(),
        version=metadata['version'],media_root=values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media',
        upload_root=values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads')
    metadata.update(status='integrity_verified_restore_not_tested',bundle_id=result['backup_id'],uncompressed_bytes=result['uncompressed_bytes'],sha256=recovery.digest(directory/'bundle.gpg'))
    a.write(directory/'metadata.json',metadata)
    return metadata


def backup_space(metadata):
    size=metadata.get('uncompressed_bytes')
    if type(size) is not int or size<0:
        raise h.HostingError('invalid_configuration','Backup lacks verified expansion-size metadata; use reviewed offline recovery.')
    required=size*6+1_000_000_000
    for path in (a.STATE,Path('/tmp')):
        if shutil.disk_usage(path).free<required:
            raise h.HostingError('insufficient_space','Insufficient space to expand the selected backup.',required_bytes=required)
    return size


def verify(value):
    metadata,bundle=record(value)
    h.trusted(bundle)
    if metadata.get('sha256') != recovery.digest(bundle):
        raise h.HostingError('backup_integrity_failed','Backup checksum does not match.')
    backup_space(metadata)
    with recovery.unpack(bundle,a.key()) as (_,manifest):
        if manifest['backup_id']!=metadata['bundle_id'] or manifest['roots']!=metadata['roots']:
            raise h.HostingError('backup_integrity_failed','Backup manifest does not match its approved inventory.')
    return dict(id=value,status='integrity_verified_restore_not_tested',version=metadata['version'])


def pg(statement):
    return a.run(['runuser','-u','postgres','--','psql','-X','-tA','-v','ON_ERROR_STOP=1','-d','postgres'],input=statement)


def quote(value):
    return '"'+value.replace('"','""')+'"'


def local_database():
    from psycopg2.extensions import parse_dsn
    _,values=a.settings()
    params=parse_dsn(values['DATABASE_URL'])
    if params.get('host') not in (None,'','localhost','127.0.0.1','/var/run/postgresql') or params.get('port','5432')!='5432':
        raise h.HostingError('unsupported_environment','Live restore requires the supported local PostgreSQL installation.')
    return values['DATABASE_URL'],params['dbname'],params['user']


def ensure_no_clients(url):
    connection=recovery.connect(url)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'")
            if cur.fetchone()[0]:raise h.HostingError('operation_busy','Database clients remain connected.')
    finally:
        # A psycopg2 connection context commits but does NOT close the session.
        connection.close()


def isolated_restore(metadata,bundle,directory):
    url,_,role=local_database()
    def create(name,encoding):
        if not re.fullmatch('[A-Za-z0-9_-]{1,32}',encoding):raise ValueError('encoding')
        pg('CREATE DATABASE '+quote(name)+' OWNER '+quote(role)+" TEMPLATE template0 ENCODING '"+encoding+"';")
    return recovery.restore(bundle,a.key(),url,directory,preserve_ownership=True,create_database=create)


def restored_path(restored,directory,wanted):
    wanted=Path(wanted)
    for index,root in enumerate(map(Path,restored['roots'])):
        if wanted==root or wanted.is_relative_to(root):
            return directory/f'root-{index}'/wanted.relative_to(root)
    raise h.HostingError('incompatible_backup','The backup lacks required installation files.')


def validate_restored_code(metadata,restored,directory):
    from .releases import migration_head,version_at
    with tempfile.TemporaryDirectory(prefix='code-check-',dir=directory.parent) as name:
        projection=Path(name)
        for part in ('app','migrations'):
            (projection/part).symlink_to(restored_path(restored,directory,Path(metadata['source'])/part))
        if migration_head(projection)!=restored['schema_revision'] or version_at(projection)!=metadata['version']:
            raise h.HostingError('incompatible_backup','Recovery code and database schema do not match.')
        if h.read()['hosted'] and not (projection/'app/services/hosting_web.py').exists():
            raise h.HostingError('incompatible_backup','Hosted recovery requires hosting-capable code.')


def retain_newer_units(operation,restored):
    """Retain, rather than run, services absent from the matched older backup."""
    base=Path('/etc/systemd/system')
    expected=set(restored['roots'])
    for path in sorted(base.glob('freo*')):
        if '.freo-' in path.name or str(path) in expected:continue
        name=path.name.removesuffix('.d')
        if not re.fullmatch(r'freo[a-z0-9@_.-]*\.(service|timer)',name):continue
        if path.is_symlink():continue
        if not path.is_file() and not (path.is_dir() and path.name.endswith('.d')):continue
        # Global /usr/local guards remain present throughout these renames.
        if path.is_file():
            a.run(['systemctl','disable',name])
        retained=base/('.freo-retained-'+operation['operation_id']+'-'+path.name)
        if retained.exists():
            raise h.HostingError('recovery_required','An unexpected retained service already exists.')
        os.rename(path,retained)
        a.checkpoint(operation,retained_units=[*operation.get('retained_units',[]),name])


def restored_service_selection(metadata):
    selected=[u for u in metadata['active_units'] if not u.startswith('freo-playout') and u not in ('icecast2.service','freo-mic.service')]
    selected.extend(a.required_core())
    selected.append('icecast2.service')
    selected.extend('freo-playout@'+s['slug']+'.service' for s in a.station_rows() if s['enabled'] and s['desired_state']=='running')
    if 'freo-mic.service' in metadata['active_units']:selected.append('freo-mic.service')
    return list(dict.fromkeys(selected))


def validate_backup_database(metadata,restored,directory):
    from .__main__ import configuration
    wanted=Path(metadata['env_file'])
    for index,root in enumerate(map(Path,restored['roots'])):
        if wanted==root or wanted.is_relative_to(root):
            saved=configuration(directory/f'root-{index}'/wanted.relative_to(root))
            _,current=a.settings()
            if saved['DATABASE_URL']!=current['DATABASE_URL']:
                raise h.HostingError('incompatible_backup','Database connection mapping changed; use reviewed offline recovery.')
            return
    raise h.HostingError('incompatible_backup','The approved backup lacks its application configuration.')


def validate_restored_capacity(restored):
    policy=h.read()
    if not policy['hosted']:return
    from psycopg2.extensions import parse_dsn,make_dsn
    url,_,_=local_database()
    values=parse_dsn(url);values['dbname']=restored['database']
    connection=recovery.connect(make_dsn(**values))
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT count(*) FROM stations WHERE deleted_at IS NULL')
            count=cur.fetchone()[0]
            if count>policy['limits']['stations']:
                raise h.HostingError('incompatible_backup','Backup stations exceed destination capacity.',current_stations=count,requested_limit=policy['limits']['stations'])
            cur.execute('SELECT s.id,m.bitrate,m.pending_audio FROM stations s JOIN stream_mounts m ON m.station_id=s.id WHERE s.deleted_at IS NULL')
            for station,bitrate,pending in cur.fetchall():
                if max(bitrate,(pending or {}).get('bitrate',0))>policy['limits']['bitrate_kbps']:
                    raise h.HostingError('incompatible_backup','Backup bitrate exceeds destination capacity.',station_id=station,requested_limit=policy['limits']['bitrate_kbps'])
    finally:connection.close()


def restore_start(args):
    expected=a.read_json(a.STATE/'identity.json')['installation_id']
    if args.confirm_installation != expected:
        raise h.HostingError('confirmation_required','Live restore requires the destination installation ID.')
    metadata,bundle=record(args.id)
    if metadata['installation_id']!=expected:
        raise h.HostingError('incompatible_backup','Only this installation’s approved backups can be attached.')
    verify(args.id)
    local_database()
    disk_check(roots(),extra_bytes=backup_space(metadata))
    # Explicit restore authorization permits superseding an unfinished upgrade.
    old=a.current_operation()
    if old and old['phase'] not in a.TERMINAL:
        if old['operation']=='backup.restore':
            if old['restore_id']!=args.id:
                raise h.HostingError('recovery_required','Resume the already authorized restore before choosing another backup.')
            return resume(old)
        a.write(a.private_directory(a.STATE/'history')/(old['operation_id']+'.json'),old)
    operation=dict(operation_id=uuid.uuid4().hex,operation='backup.restore',phase='preparing',
                   restore_id=args.id,previous_state=h.read(),was_inhibited=(h.STATE/'inhibit').exists())
    upgrade=a.read_json(a.UPDATES/'journal.json') if (a.UPDATES/'journal.json').exists() else None
    if upgrade and upgrade['phase'] not in ('complete','preflight_passed','preflight_failed','failed_before_migration'):
        operation['interrupted_upgrade']=upgrade['operation']
        operation['active_units']=upgrade.get('active_units',[])
    a.checkpoint(operation)
    a.audit('backup.restore',dict(event='authorized',installation_id=expected,backup_id=args.id))
    return restore_live(operation)


@contextmanager
def administrative_authority(operation):
    """Destination trust and policy survive customer configuration attachment."""
    names=('/etc/freo/hosting.json','/etc/freo/hosting-storage.json',
           '/etc/freo/publisher.gpg','/etc/freo/admin-upgrades.json')
    if 'authority_files' not in operation:
        saved={}
        for name in names:
            path=Path(name)
            if path.exists():
                h.trusted(path)
                saved[name]=dict(data=base64.b64encode(path.read_bytes()).decode(),mode=path.stat().st_mode & 0o777)
            else:saved[name]=None
        a.checkpoint(operation,authority_files=saved)
    def restore():
        if set(operation['authority_files'])!=set(names):
            raise h.HostingError('invalid_configuration','Administrative authority journal is invalid.')
        for name,entry in operation['authority_files'].items():
            path=Path(name);path.parent.mkdir(parents=True,exist_ok=True)
            if entry is None:
                path.unlink(missing_ok=True)
            else:
                fd,temporary=tempfile.mkstemp(prefix='.freo-authority-',dir=path.parent)
                try:
                    os.fchmod(fd,entry['mode'])
                    with os.fdopen(fd,'wb') as stream:
                        stream.write(base64.b64decode(entry['data']));stream.flush();os.fsync(stream.fileno())
                    os.replace(temporary,path)
                    from .upgrade import sync_directory
                    sync_directory(path.parent)
                finally:Path(temporary).unlink(missing_ok=True)
    restore()
    try:yield
    finally:restore()


def adopt_restored_release(metadata,release):
    """Use Phase A's canonical deployment paths for a restored direct installation."""
    if metadata['source']!='/opt/freo':return
    from .upgrade import rewrite_unit,sync_directory
    environment=Path(metadata['env_file'])
    recovered_env=release/environment.relative_to('/opt/freo') if environment.is_relative_to('/opt/freo') else environment
    destination=Path('/etc/freo/freo.env')
    if recovered_env!=destination:
        shutil.copy2(recovered_env,destination)
        destination.chmod(0o600)
    for target in Path('/etc/systemd/system').glob('freo*.service'):
        if not target.is_file() or target.is_symlink():continue
        body=target.read_text()
        rewritten=rewrite_unit(body)
        if body!=rewritten:
            target.write_text(rewritten);target.chmod(0o644)
    sync_directory(destination.parent)


def restore_live(operation, *, reconcile=False):
    metadata,bundle=record(operation['restore_id'])
    work=a.private_directory(a.STATE/'restores'/operation['operation_id'])
    # Reentrant authority context and journal survive even a kill between roots.
    from .hosting_recovery import preserve_authority,restore_authority
    if (h.STATE/'recovery-authority.json').exists() and operation.get('authority_saved'):
        restore_authority()
    if not operation.get('restored'):
        directory=work/('payload-'+uuid.uuid4().hex)
        try:
            backup_space(metadata)
            restored=isolated_restore(metadata,bundle,directory)
            validate_restored_code(metadata,restored,directory)
            validate_backup_database(metadata,restored,directory)
            validate_restored_capacity(restored)
        except Exception:
            a.checkpoint(operation,phase='failed_before_changes')
            raise
        a.checkpoint(operation,restored=restored,restore_directory=str(directory),phase='verified_restore')
    freeze(operation)
    if not operation.get('recovery_point'):
        saved=create_frozen(operation,role='before_restore')
        a.checkpoint(operation,recovery_point=saved['id'])
    restored=operation['restored']
    # Only trusted own inventory can map live destinations. Never accept paths from argv.
    if restored['roots']!=metadata['roots']:
        raise h.HostingError('backup_integrity_failed','Restored inventory differs from approved inventory.')
    release=Path('/opt/freo/releases')/('recovered-'+operation['operation_id'])
    release.mkdir(parents=True,exist_ok=True)
    release.chmod(0o755)
    with administrative_authority(operation), preserve_authority():
        a.checkpoint(operation,authority_saved=True,phase='attaching')
        retain_newer_units(operation,restored)
        skipped=('/etc/postgresql','/etc/letsencrypt')
        completed=operation.setdefault('attached',[])
        ordered=sorted(enumerate(restored['roots']),key=lambda item:not Path(item[1]).is_relative_to(metadata['source']))
        code_checked=False
        for index,root in ordered:
            if not Path(root).is_relative_to(metadata['source']) and not code_checked:
                from .releases import migration_head,version_at
                if migration_head(release)!=restored['schema_revision'] or version_at(release)!=metadata['version']:
                    raise h.HostingError('incompatible_backup','Recovery code and database schema do not match.')
                if h.read()['hosted'] and not (release/'app/services/hosting_web.py').exists():
                    raise h.HostingError('incompatible_backup','Hosted recovery requires hosting-capable code.')
                code_checked=True
            original=Path(root)
            if root in skipped or index in completed:continue
            if original.is_relative_to(Path(metadata['source'])):
                target=release/original.relative_to(metadata['source'])
            else:
                target=original
            if target==Path('/') or target.is_relative_to(a.STATE) or target.is_relative_to(h.STATE) or target.is_relative_to(a.UPDATES):
                raise h.HostingError('incompatible_backup','Backup contains an administrative authority root.')
            retained=target.parent/('.freo-retained-'+operation['operation_id']+'-'+target.name)
            staged=target.parent/('.freo-restoring-'+operation['operation_id']+'-'+target.name)
            target.parent.mkdir(parents=True,exist_ok=True)
            # Write-ahead attachment state; repeat safely after either rename.
            if operation.get('attaching_index')!=index:
                a.checkpoint(operation,attaching_index=index,had_target=target.exists() or target.is_symlink())
            if operation['had_target'] and not retained.exists() and not retained.is_symlink():
                os.rename(target,retained)
            if not target.exists() and not target.is_symlink():
                if staged.exists() or staged.is_symlink():
                    if staged.is_dir() and not staged.is_symlink():shutil.rmtree(staged)
                    else:staged.unlink()
                a.run(['cp','-a','--',str(Path(operation['restore_directory'])/f'root-{index}'),str(staged)],timeout=3600)
                os.rename(staged,target)
            completed.append(index)
            a.checkpoint(operation,attached=completed)
        # Restore symlinks to their original approved targets, mapping executable paths.
        with recovery.unpack(bundle,a.key()) as (_,manifest):
            for entry in manifest['entries']:
                if entry['kind']!='symlink' or entry['root'] not in completed:continue
                original=Path(restored['roots'][entry['root']])
                target=(release/original.relative_to(metadata['source']) if original.is_relative_to(metadata['source']) else original)/entry['path']
                link=entry['target']
                if Path(link).is_absolute() and Path(link).is_relative_to(metadata['source']):link=str(release/Path(link).relative_to(metadata['source']))
                target.unlink(missing_ok=True);target.symlink_to(link)
        # venv console scripts contain an absolute Python shebang.
        for path in (release/'venv/bin').iterdir():
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as stream: prefix=stream.read(2)
                if prefix==b'#!':
                    data=path.read_bytes().replace(str(metadata['source']).encode(),str(release).encode())
                    path.write_bytes(data)
        url,dbname,role=local_database()
        preserved='freo_preserved_'+operation['operation_id']
        names=set(pg('SELECT datname FROM pg_database;').splitlines())
        if preserved not in names:
            # Refuse external writers rather than terminating unrelated sessions.
            ensure_no_clients(url)
            pg('ALTER DATABASE '+quote(dbname)+' RENAME TO '+quote(preserved)+';')
        names=set(pg('SELECT datname FROM pg_database;').splitlines())
        if restored['database'] in names:
            if dbname in names:raise h.HostingError('recovery_required','Database attachment is ambiguous.')
            pg('ALTER DATABASE '+quote(restored['database'])+' RENAME TO '+quote(dbname)+';')
        a.checkpoint(operation,preserved_database=preserved)
        adopt_restored_release(metadata,release)
        switch_pointer(Path('/opt/freo'),release)
    # Use retained administration with the restored release's models/dependencies.
    if (release/'freo_ops/hosting.py').exists():
        helper=(a.STATE/'runtime').resolve()
        a.run([str(release/'venv/bin/python'),'-I',str(helper/'scripts/admin-maintenance.py'),'storage'],timeout=180)
    a.run(['nginx','-t'])
    a.run(['systemctl','reload','nginx'])
    if operation.get('interrupted_upgrade'):
        journal=a.read_json(a.UPDATES/'journal.json')
        if journal['operation']==operation['interrupted_upgrade']:
            history=a.private_directory(a.UPDATES/'history')
            a.write(history/(journal['operation']+'-recovered.json'),dict(journal,recovered_by=operation['operation_id']))
            (a.UPDATES/'journal.json').unlink()
    a.checkpoint(operation,phase='attached',active_units=restored_service_selection(metadata))
    verification=thaw(operation,reconcile=reconcile)
    return dict(operation_id=operation['operation_id'],backup_id=metadata['id'],recovery_point=operation['recovery_point'],
                preserved_database=operation['preserved_database'],verification=verification)


def resume(operation):
    if operation['operation']=='backup.restore':return restore_live(operation,reconcile=True)
    if operation['operation']=='backup.create':
        if not operation.get('backup_id'):
            return dict(operation_id=operation['operation_id'],verification=thaw(operation,reconcile=True),backup_created=False)
        try: verified=verify(operation['backup_id'])
        except Exception:
            # No attachment/migration occurred: return the old services, report failure.
            thaw(operation,reconcile=True)
            raise
        return dict(backup=verified,verification=thaw(operation,reconcile=True))
    if operation['operation']=='upgrade.apply':
        from .admin_upgrade import register_backup
        if operation.get('backup_id'):register_backup(operation['backup_id'])
        journal=a.read_json(a.UPDATES/'journal.json')
        if journal['phase']=='complete':
            verification=a.verified_health()
            a.checkpoint(operation,phase='complete')
            return dict(operation_id=operation['operation_id'],verification=verification,upgrade_outcome='complete')
        safe=('preflight','preflight_failed','preflight_passed','stopping','backup','dependencies','failed_before_migration')
        if journal['phase'] in safe and str(a.source())==journal.get('previous_release'):
            _,values=a.settings()
            connection=recovery.connect(values['DATABASE_URL'])
            try:revision=recovery.schema_revision(connection)
            finally:connection.close()
            if journal.get('source_revision',revision)==revision:
                a.checkpoint(operation,active_units=journal.get('active_units',[]),was_inhibited=False)
                verification=thaw(operation,reconcile=True)
                a.write(a.private_directory(a.UPDATES/'history')/(journal['operation']+'-aborted.json'),dict(journal,recovered_by=operation['operation_id']))
                (a.UPDATES/'journal.json').unlink()
                return dict(operation_id=operation['operation_id'],verification=verification,upgrade_outcome='aborted_before_migration')
        raise h.HostingError('recovery_required','Inspect the upgrade journal; restore its recovery point explicitly.',backup_id=operation.get('backup_id'))
    return dict(verification=thaw(operation,reconcile=True))


def dispatch(args):
    if args.action=='list':
        return dict(backups=[{k:v for k,v in a.read_json(path).items() if k in ('id','created_at','version','status','role')} for path in sorted(catalog().glob('*/metadata.json'))])
    if args.action=='verify':return dict(backup=verify(args.id))
    if args.action=='restore':return restore_start(args)
    disk_check(roots());a.key()
    operation=a.begin('backup.create')
    try:
        freeze(operation)
        metadata=create_frozen(operation)
        verification=thaw(operation)
        return dict(operation_id=operation['operation_id'],backup={k:metadata[k] for k in ('id','version','status')},
                    encryption=dict(key_id=a.read_json(a.STATE/'backup-key.json')['key_id'],escrow_required=True),verification=verification)
    except Exception:
        # Preserve the journal/guard for explicit services recover after interruption.
        if operation['phase']=='preparing':a.checkpoint(operation,phase='failed_before_changes')
        raise
