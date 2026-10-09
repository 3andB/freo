"""Privileged local hosting commands. No remote API or provider integration."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from . import hosting as h

RADIO = Path('/etc/freo/radio/icecast.xml')
UNITS = ('icecast2.service', 'freo-mic.service', 'freo-playout.service')


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=120, **kwargs).stdout


def render_listener_limit(root, policy=None):
    policy = policy or h.read()
    limits = root.find('limits')
    if limits is None:
        raise h.HostingError('invalid_configuration', 'Icecast limits are missing.')
    for node in limits.findall('freo-listeners'):
        limits.remove(node)
    if policy['hosted']:
        ET.SubElement(limits, 'freo-listeners').text = str(policy['limits']['listeners'])
        clients = limits.find('clients')
        if clients is None:
            clients = ET.SubElement(limits, 'clients')
        clients.text = str(max(int(clients.text or 0), policy['limits']['listeners'] + 128))


def radio_policy(policy):
    from app.services.icecast_directory import parse_config
    from app.services.station_runtime import atomic_install
    root = parse_config(RADIO.read_bytes())
    render_listener_limit(root, policy)
    staged = atomic_install(RADIO, ET.tostring(root, encoding='unicode'), 0o640, 'root', 'icecast')
    os.replace(staged, RADIO)
    if active('icecast2.service'):
        run(['systemctl', 'reload', 'icecast2.service'])


def active(unit):
    return subprocess.run(['systemctl', 'is-active', '--quiet', unit], capture_output=True).returncode == 0


def broadcast_units():
    result = set(UNITS)
    result.update(p.name.removesuffix('.d') for p in Path('/etc/systemd/system').glob('freo-playout@*.service.d'))
    result.update(row['unit'] for row in json.loads(run(['systemctl','list-units','--all','--output=json','--no-pager','freo-playout*'])))
    return sorted(result)


def stop_broadcasts():
    for unit in broadcast_units():
        subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=60)
    if any(active(unit) for unit in broadcast_units()):
        raise h.HostingError('verification_failed', 'Broadcast services did not stop.')
    import socket
    with socket.socket() as sock:
        sock.settimeout(2)
        if sock.connect_ex(('127.0.0.1', 8001)) == 0:
            raise h.HostingError('verification_failed', 'The public audio backend is still reachable.')


def observations():
    from app.services.statistics.icecast import Icecast
    return Icecast('/etc/freo/secrets/engine.json').read('/admin/stats')


def verify(policy=None):
    policy = policy or h.read()
    if not policy['hosted']:
        return dict(hosted=False)
    h.trusted(h.CONFIG)
    from .hosting_storage import usage
    storage = usage()
    stopped = policy['status'] in ('suspended','maintenance') or (h.STATE / 'inhibit').exists()
    if stopped:
        if any(active(unit) for unit in broadcast_units()):
            raise h.HostingError('verification_failed', 'A restricted broadcast service is running.')
        import socket
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex(('127.0.0.1',8001)) == 0:
                raise h.HostingError('verification_failed', 'Restricted Icecast remains reachable.')
        return dict(broadcasting=False, listeners=0, storage=storage)
    if not active('icecast2.service'):
        raise h.HostingError('verification_failed', 'Icecast is not active.')
    from urllib.request import build_opener, ProxyHandler
    try:
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:8000/ready',timeout=3) as response:
            if response.status != 200:
                raise OSError('not ready')
    except Exception:
        raise h.HostingError('verification_failed','The Freo application is not ready.') from None
    for unit, user in (('freo.service','freo'),('freo-ingest.service','freo-ingest'),
                       ('freo-automation.service','freo-automation'),('freo-production.service','freo-ingest')):
        verify_storage_access(unit,user)
    data = observations()
    # Attempt one admission to publish the native counter/limit, then close it.
    from app.models import Station
    expected = Station.query.filter_by(deleted_at=None, enabled=True, desired_state='running').all()
    from urllib.request import build_opener, ProxyHandler
    opener = build_opener(ProxyHandler({}))
    for station in expected:
        if not active('freo-playout@' + station.slug + '.service'):
            raise h.HostingError('verification_failed', 'A requested station is not running.', station_id=station.id)
        verify_storage_access('freo-playout@' + station.slug + '.service','freo-playout')
        if not any(node.get('mount') == '/' + station.slug for node in data.findall('source')):
            raise h.HostingError('verification_failed', 'A requested station has no Icecast source.', station_id=station.id)
        try:
            with opener.open('http://127.0.0.1:8001/' + station.slug, timeout=3) as response:
                response.read(1024)
        except Exception:
            # A full listener allocation may correctly reject this probe.
            pass
    time.sleep(.15)
    data = observations()
    limit = data.findtext('freo_listener_limit')
    if expected and limit != str(policy['limits']['listeners']):
        raise h.HostingError('verification_failed', 'Icecast did not report the assigned native listener limit.')
    listeners = int(data.findtext('freo_listeners') or 0)
    return dict(broadcasting=True, listeners=listeners, draining=listeners>policy['limits']['listeners'], storage=storage)


def constraints(policy):
    from app.services.stations import active_stations, allocation_lock
    from app.extensions import db
    allocation_lock()
    stations = active_stations().all()
    if len(stations) > policy['limits']['stations']:
        raise h.HostingError('station_limit_exceeded','Existing stations exceed the requested capacity.',current_stations=len(stations),requested_limit=policy['limits']['stations'])
    for station in stations:
        stream = station.stream
        if stream and max(stream.bitrate, (stream.pending_audio or {}).get('bitrate',0)) > policy['limits']['bitrate_kbps']:
            raise h.HostingError('bitrate_limit_exceeded','Existing or queued streaming settings exceed the requested maximum.',station_id=station.id,requested_limit=policy['limits']['bitrate_kbps'])
    return stations


def install_storage_access():
    """Apply after the existing managed storage.conf resets service paths."""
    from .hosting_storage import ROOT
    changed = set()
    for unit in ('freo.service','freo-ingest.service','freo-automation.service','freo-production.service','freo-playout@.service'):
        directory=Path('/etc/systemd/system')/(unit+'.d');directory.mkdir(exist_ok=True)
        target=directory/'zz-freo-hosting-storage.conf'
        body='[Service]\nSupplementaryGroups=freo-storage\nReadWritePaths='+str(ROOT)+'\n'
        if not target.exists() or target.read_text()!=body:
            target.write_text(body)
            changed.add(unit)
    run(['systemctl','daemon-reload'])
    return changed


def verify_storage_access(unit, user):
    """Check the running sandbox, not just the unit's future configuration."""
    from .hosting_storage import ROOT
    pid=int(run(['systemctl','show',unit,'--property=MainPID','--value']).strip())
    if pid<=0 or subprocess.run(['nsenter','--target',str(pid),'--mount','--',
            'runuser','-u',user,'--','test','-w',str(ROOT)],capture_output=True).returncode:
        raise h.HostingError('verification_failed','A media worker cannot reserve storage in its running sandbox.',unit=unit)


def provision_storage():
    import grp
    from flask import current_app
    from app.extensions import db
    from sqlalchemy import LargeBinary
    from sqlalchemy.engine import make_url
    from . import hosting_storage as storage
    url = make_url(current_app.config['SQLALCHEMY_DATABASE_URI'])
    if url.get_backend_name() != 'postgresql' or url.host not in (None,'','localhost','127.0.0.1','/var/run/postgresql'):
        raise h.HostingError('unsupported_environment','Hosted storage requires the supported local PostgreSQL installation.')
    media = current_app.config.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media'
    uploads = current_app.config.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads'
    roots = list(dict.fromkeys([media, uploads, str(current_app.config.get('FREO_PRODUCTION_ROOT') or Path(uploads)/'production'), str(current_app.config.get('FREO_BULLETIN_ROOT') or '/var/lib/freo/bulletins')]))
    if any(not Path(p).is_absolute() or Path(p).is_symlink() for p in roots):
        raise h.HostingError('invalid_configuration','Hosting storage roots must be absolute regular directories.')
    blobs = {table.name:[c.name for c in table.columns if isinstance(c.type, LargeBinary)] for table in db.metadata.sorted_tables}
    blobs = {name:columns for name,columns in blobs.items() if columns}
    try:
        group = grp.getgrnam('freo-storage').gr_gid
    except KeyError:
        run(['groupadd','--system','freo-storage']);group=grp.getgrnam('freo-storage').gr_gid
    users = ('root','freo','freo-ingest','freo-automation','freo-playout')
    for user in users[1:]:
        run(['usermod','-a','-G','freo-storage',user])
    storage.ROOT.mkdir(mode=0o2770,exist_ok=True)
    os.chown(storage.ROOT,0,group);os.chmod(storage.ROOT,0o2770)
    lock = storage.ROOT/'lock'
    if not lock.exists():
        lock.touch(mode=0o660)
    os.chown(lock,0,group);os.chmod(lock,0o660)
    for root in roots:
        path = Path(root)
        path.mkdir(parents=True,exist_ok=True)
        run(['setfacl','-R','-m','g:freo-storage:r-X', '--',root])
        directories = [path] + [p for p in path.rglob('*') if p.is_dir() and not p.is_symlink()]
        for directory in directories:
            run(['setfacl','-m','d:g:freo-storage:r-x','--',str(directory)])
        for parent in path.parents:
            if str(parent) in ('/','/var','/var/lib','/srv') or str(parent) in roots:
                continue
            run(['setfacl','-m','g:freo-storage:--x','--',str(parent)])
    def ident(value):
        return '"' + value.replace('"','""') + '"'
    statements = []
    for user in users:
        statements.append("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='"+user+"') THEN CREATE ROLE "+ident(user)+" LOGIN; END IF; END $$;")
        statements.append('GRANT CONNECT ON DATABASE '+ident(url.database)+' TO '+ident(user)+';')
        statements.append('GRANT USAGE ON SCHEMA public TO '+ident(user)+';')
        for table in blobs:
            statements.append('GRANT SELECT ON TABLE '+ident(table)+' TO '+ident(user)+';')
    run(['runuser','-u','postgres','--','psql','-X','-v','ON_ERROR_STOP=1','-d',url.database],input='\n'.join(statements))
    h.atomic(storage.INVENTORY,dict(roots=roots,media_root=media,database=url.database,socket='/var/run/postgresql',blobs=blobs))
    from .hosting_recovery import protect_request_spooling
    protect_request_spooling()
    return install_storage_access()


def audit(operation, previous, requested, result):
    row = dict(timestamp=datetime.now(timezone.utc).isoformat(),operation=operation,previous=previous,requested=requested,result=result,operator=dict(uid=os.getuid(),sudo_user=os.environ.get('SUDO_USER')))
    fd = os.open(h.STATE/'audit.jsonl',os.O_APPEND|os.O_CREAT|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as stream:
        stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())


def administrative_policy(repair=False):
    try:
        return h.read()
    except h.HostingError:
        if not repair:
            raise
        path = h.STATE / 'last-valid.json'
        h.trusted(path)
        saved = h.validate(json.loads(path.read_text()))
        if not saved['hosted']:
            raise h.HostingError('invalid_configuration','No authoritative hosted recovery state is available.')
        return dict(saved,status='maintenance')


def apply(policy, operation):
    from app.extensions import db
    from app.services import station_runtime as runtime
    previous = administrative_policy(repair=operation=='configure')
    requested = h.validate(policy)
    changed = False
    with runtime.operation_lock():
        try:
            stations = constraints(requested)
            first = not previous['hosted']
            storage_changes = set()
            if first:
                binary = run(['systemctl','show','icecast2.service','--property=ExecStart','--value'])
                match = re.search(r'path=([^ ;]+)',binary)
                if not match or b'freo-listeners' not in Path(match.group(1)).read_bytes():
                    from .v1 import prepare_icecast, activate_icecast
                    import tempfile
                    build_state=Path(tempfile.mkdtemp(prefix='hosting-engine-',dir=h.STATE))
                    engine=prepare_icecast(runtime.SOURCE,build_state)
                    activate_icecast(engine, replacing=True)
                storage_changes = provision_storage()
            elif operation == 'activate':
                storage_changes = provision_storage()
            h.atomic(h.STATE/'transaction.json',dict(previous=previous,requested=requested,phase='applying'))
            changed = True
            blocked = requested['status'] in ('suspended','maintenance')
            if first or blocked:
                # Icecast itself observes this marker: even process death here
                # cannot leave suspended public audio running.
                h.atomic(h.STATE/'inhibit',True)
                stop_broadcasts()
            reducing = previous['hosted'] and requested['limits']['listeners'] < previous['limits']['listeners']
            if reducing:
                radio_policy(requested)
            h.atomic(h.STATE/'enabled',True)
            from .hosting_storage import locked
            with locked():
                h.atomic(h.CONFIG,requested)
            if not reducing:
                radio_policy(requested)
            if not blocked:
                (h.STATE/'inhibit').unlink(missing_ok=True)
                if first:
                    # Hosted recording output and storage permissions need one controlled restart.
                    for station in stations:
                        if station.enabled and station.stream.enabled:
                            runtime.render(station)
                    for unit in ('freo.service','freo-ingest.service','freo-automation.service','freo-production.service'):
                        if active(unit):run(['systemctl','restart',unit])
                if not first:
                    for unit in sorted(storage_changes):
                        if unit != 'freo-playout@.service' and active(unit):
                            run(['systemctl','restart',unit])
                run(['systemctl','start','freo.service','freo-ingest.service','freo-automation.service','freo-production.service'])
                run(['systemctl','start','icecast2.service'])
                from app.services.live_mic import enabled
                if enabled():run(['systemctl','start','freo-mic.service'])
                for station in stations:
                    if station.enabled and station.desired_state == 'running':
                        run(['systemctl','restart' if first or 'freo-playout@.service' in storage_changes else 'start',runtime.unit_name(station.slug)])
                deadline=time.monotonic()+45
                while True:
                    try:
                        result=verify(requested);break
                    except h.HostingError:
                        if time.monotonic()>deadline:raise
                        time.sleep(1)
            else:
                result=verify(requested)
            db.session.commit()
            h.atomic(h.STATE/'last-valid.json',requested)
            h.atomic(h.STATE/'transaction.json',dict(phase='complete',state=requested))
            audit(operation,previous,requested,dict(success=True,verification=result))
            return dict(success=True,state=requested,verification=result)
        except Exception as error:
            db.session.rollback()
            if changed and (h.STATE/'enabled').exists():
                # Never report active after a partial transition. Keep customer data.
                safe = dict(previous if previous['hosted'] else requested,status='maintenance')
                h.atomic(h.STATE/'inhibit',True);h.atomic(h.CONFIG,safe)
                try:stop_broadcasts()
                except Exception:pass
            result=error.response() if isinstance(error,h.HostingError) else dict(success=False,error='operation_failed',message='Hosting operation failed; inspect the administrator audit log.')
            audit(operation,previous,requested,result)
            raise


class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise h.HostingError('invalid_arguments',message)


def main(argv=None):
    result=None
    try:
        if os.geteuid()!=0:
            raise h.HostingError('unauthorized','Root authorization is required.')
        parser=Parser(prog='freo-admin')
        parser.add_argument('area',choices=['hosting'])
        commands=parser.add_subparsers(dest='command',required=True)
        for name in ('status','storage','verify','maintenance','past-due','activate'):
            commands.add_parser(name)
        suspend=commands.add_parser('suspend');suspend.add_argument('--reason',default='')
        configure=commands.add_parser('configure');configure.add_argument('--plan',choices=['starter','pro','custom'],required=True)
        for flag in ('stations','listeners','bitrate','storage-gb'):
            configure.add_argument('--'+flag,type=int)
        args=parser.parse_args(argv)
        from dotenv import dotenv_values
        env=Path('/etc/freo/freo.env')
        if not env.exists():env=Path('/opt/freo/.env')
        values=dotenv_values(env,interpolate=False)
        for key in list(os.environ):
            if key.startswith(('FREO_','FLASK_')) or key in ('DATABASE_URL','SECRET_KEY'):
                os.environ.pop(key,None)
        os.environ.update(FREO_ENV_FILE=str(env),FLASK_ENV='production',PATH='/usr/sbin:/usr/bin:/sbin:/bin')
        for key,value in values.items():
            if value is not None:os.environ[key]=value
        from app import create_app
        with create_app().app_context(),h.administrative_lock():
            policy=administrative_policy(repair=args.command=='configure')
            if args.command=='status':
                result=dict(success=True,state=policy,inhibited=(h.STATE/'inhibit').exists())
            elif args.command=='storage':
                from .hosting_storage import usage
                result=dict(success=True,storage=usage())
            elif args.command=='verify':
                result=dict(success=True,state=policy,verification=verify(policy))
            else:
                if args.command=='configure':
                    limits=dict(h.PLANS.get(args.plan,{}))
                    for flag,key in [('stations','stations'),('listeners','listeners'),('bitrate','bitrate_kbps'),('storage_gb','storage_gb')]:
                        number=getattr(args,flag)
                        if number is not None:limits[key]=number
                    policy=dict(hosted=True,plan=args.plan,status=policy.get('status','active'),limits=limits)
                else:
                    if not policy['hosted']:
                        raise h.HostingError('not_hosted','Enable hosting before changing commercial service status.')
                    policy=dict(policy,status={'suspend':'suspended','maintenance':'maintenance','past-due':'past_due','activate':'active'}[args.command])
                    policy.pop('reason',None)
                    if args.command=='suspend':policy['reason']=args.reason
                try:
                    h.validate(policy)
                except h.HostingError as error:
                    raise h.HostingError('invalid_arguments',str(error)) from None
                result=apply(policy,args.command)
        print(json.dumps(dict(schema_version=1,**result),sort_keys=True));return 0
    except h.HostingError as error:
        result=error.response()
        code={'invalid_arguments':2,'unauthorized':3,'operation_busy':4,'station_limit_exceeded':4,'bitrate_limit_exceeded':4,'not_hosted':4,'invalid_configuration':5}.get(error.code,6)
    except Exception:
        result=dict(success=False,error='operation_failed',message='Operation failed. Check the private administrator journal; no success recorded.')
        code=6
    try:result['state']=h.read()
    except Exception:result['state']={'restricted':True}
    print(json.dumps(dict(schema_version=1,**result),sort_keys=True));return code

if __name__=='__main__':
    raise SystemExit(main())
