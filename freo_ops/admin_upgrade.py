"""Approved staged versions, executed exclusively by the existing updater."""
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone
from . import admin as a, admin_backup as backups, hosting as h, recovery, releases


def staged(version):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.]+)?',version):
        raise h.HostingError('invalid_arguments','A concrete Freo version is required.')
    directory=a.UPDATES/'staged'/version
    if not directory.is_dir():raise h.HostingError('release_not_found','That version has not been staged by the server administrator.')
    from .upgrade import require_root_directory
    require_root_directory(directory,private=True)
    artifact=directory/'release.tar.gz';signature=directory/'release.tar.gz.asc'
    keyring=Path('/etc/freo/publisher.gpg')
    for path in (artifact,signature,keyring):h.trusted(path)
    return artifact,signature,keyring


def candidate_allowed():
    path=Path('/etc/freo/admin-upgrades.json')
    if not path.exists():return False
    value=a.read_json(path)
    if set(value)!={'allow_candidate'} or type(value['allow_candidate']) is not bool:
        raise h.HostingError('invalid_configuration','Upgrade policy must contain only boolean allow_candidate.')
    return value['allow_candidate']


def verify_staged(version):
    artifact,signature,keyring=staged(version)
    import tempfile
    with tempfile.TemporaryDirectory(prefix='freo-admin-release-') as name:
        manifest=releases.extract_verified(artifact,Path(name)/'release',signature=signature,keyring=keyring,allow_candidate=candidate_allowed())
    if manifest['version']!=version:
        raise h.HostingError('invalid_configuration','Staged directory does not match signed release version.')
    from .releases import version_at
    from packaging.version import Version
    _,values=a.settings()
    con=recovery.connect(values['DATABASE_URL'])
    try: revision=recovery.schema_revision(con)
    finally:con.close()
    compatible=revision in manifest['supported_source_revisions'] and Version(version)>=Version(version_at(a.source()))
    return dict(version=version,signature_verified=True,compatible=compatible,commit=manifest['commit'],platform=manifest['platform'],schema_head=manifest['schema_head'])


def register_backup(value):
    directory=backups.catalog()/value
    path=directory/'metadata.json'
    metadata=a.read_json(path)
    bundle=directory/'bundle.gpg'
    if not bundle.exists():return None
    with recovery.unpack(bundle,a.key()) as (_,manifest):
        metadata.update(bundle_id=manifest['backup_id'],roots=manifest['roots'],version=manifest['version'],
                        sha256=recovery.digest(bundle),status='integrity_verified_restore_not_tested')
    a.write(path,metadata)
    return metadata


def dispatch(args):
    if args.action=='check':
        candidates=[]
        for directory in sorted((a.UPDATES/'staged').glob('*')):
            if directory.is_dir():
                result=verify_staged(directory.name)
                if result['compatible']:
                    from .upgrade import upgrade
                    artifact,signature,keyring=staged(directory.name)
                    env,_=a.settings()
                    preflight=upgrade(artifact,signature,keyring,env,a.STATE/('preflight-'+uuid.uuid4().hex+'.gpg'),b'',env,
                        a.STATE/('preflight-'+uuid.uuid4().hex),check=True,allow_candidate=candidate_allowed())
                    result['preflight']=preflight['status']
                else:
                    result['preflight']='incompatible'
                candidates.append(result)
        journal=a.read_json(a.UPDATES/'journal.json') if (a.UPDATES/'journal.json').exists() else None
        return dict(releases=candidates,upgrade={k:journal[k] for k in ('operation','phase') if k in journal} if journal else None,
                    source='root_staged',recovery_key_present=(a.STATE/'backup.key').exists())
    approved=verify_staged(args.version)
    if not approved['compatible']:
        raise h.HostingError('incompatible_release','The staged version is not a compatible upgrade.')
    artifact,signature,keyring=staged(args.version)
    backups.disk_check(backups.roots());a.key()
    operation=a.begin('upgrade.apply',version=args.version)
    value=uuid.uuid4().hex
    directory=a.private_directory(backups.catalog()/value)
    env,values=a.settings()
    a.write(directory/'metadata.json',dict(id=value,installation_id=a.read_json(a.STATE/'identity.json')['installation_id'],
        created_at=datetime.now(timezone.utc).isoformat(),
        source=str(a.source()),env_file=str(env),active_units=[unit for unit,row in a.units().items() if row['active'] not in ('inactive','failed')],
        role='before_upgrade',status='creating'))
    a.checkpoint(operation,backup_id=value,phase='upgrading')
    # Isolated restore needs CREATEDB, supplied through local postgres rather than
    # temporarily granting the application role administrative privileges.
    _,_,role=backups.local_database()
    def create_database(name,encoding):
        if not re.fullmatch('[A-Za-z0-9_-]{1,32}',encoding):raise ValueError('encoding')
        backups.pg('CREATE DATABASE '+backups.quote(name)+' OWNER '+backups.quote(role)+" TEMPLATE template0 ENCODING '"+encoding+"';")
    try:
        from .upgrade import upgrade
        result=upgrade(artifact,signature,keyring,env,directory/'bundle.gpg',a.key(),env,
            a.STATE/('upgrade-verification-'+operation['operation_id']),allow_candidate=candidate_allowed(),
            verification_create_database=create_database)
        metadata=register_backup(value)
        verification=a.verified_health()
        a.checkpoint(operation,phase='complete')
        return dict(operation_id=operation['operation_id'],upgrade=result,backup_id=value if metadata else None,verification=verification)
    except Exception:
        register_backup(value)
        raise
