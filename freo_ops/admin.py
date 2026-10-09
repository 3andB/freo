"""Root-only lifecycle dispatcher; diagnostics do not initialize Flask."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import stat
import subprocess
import time
import uuid
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request

from . import hosting as h
from . import recovery

STATE = Path('/var/lib/freo-admin')
UPDATES = Path('/var/lib/freo-updates')
CORE = ('freo.service', 'freo-ingest.service', 'freo-automation.service', 'freo-production.service', 'freo-stats.service')
GROUPS = {
    'application': ('freo.service',), 'icecast': ('icecast2.service',),
    'microphone': ('freo-mic.service',), 'ingest': ('freo-ingest.service',),
    'automation': ('freo-automation.service',), 'production': ('freo-production.service',),
    'statistics': ('freo-stats.service',),
    'scheduled-workers': ('freo-provision.timer', 'freo-public-schedules.timer', 'freo-stats-inventory.timer', 'freo-geoip.timer'),
}
TERMINAL = ('complete', 'failed_before_changes')


def run(args, *, timeout=90, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout, **kwargs).stdout


def private_directory(path):
    from .upgrade import require_root_directory
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    for parent in (path, *path.parents):
        require_root_directory(parent, private=parent == path)
    return path


def read_json(path):
    h.trusted(path)
    return json.loads(path.read_text())


def write(path, value):
    h.atomic(path, value, 0o600)


def settings():
    from .__main__ import configuration
    path = Path('/etc/freo/freo.env')
    if not path.exists():
        path = Path('/opt/freo/.env')
    h.trusted(path)
    return path, configuration(path)


def source():
    root = Path('/opt/freo')
    return (root/'current').resolve() if (root/'current').is_symlink() else root


def initialize():
    from .admin_identity import initialize as initialize_identity
    with h.administrative_lock():
        return initialize_identity()


def key():
    path = STATE/'backup.key'
    marker = STATE/'backup-key.json'
    if not path.exists():
        if marker.exists() or any((STATE/'backups').glob('*/metadata.json')):
            raise h.HostingError('invalid_configuration', 'Restore the escrowed backup key; automatic replacement is forbidden.')
        value = secrets.token_hex(32).encode()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
    from .__main__ import passphrase
    h.trusted(path)
    value = passphrase(path)
    import hashlib
    identifier = hashlib.sha256(value).hexdigest()[:16]
    if marker.exists() and read_json(marker)['key_id'] != identifier:
        raise h.HostingError('invalid_configuration', 'Backup key does not match its recorded identity.')
    write(marker, dict(key_id=identifier))
    return value


def policy_state():
    try:
        return h.read()
    except h.HostingError:
        return dict(restricted=True, configuration_valid=False)


def inhibited(policy=None):
    policy = policy or policy_state()
    return bool(policy.get('restricted') or (policy.get('hosted') and
        (policy['status'] in ('suspended', 'maintenance') or (h.STATE/'inhibit').exists())))


def current_operation():
    path = STATE/'operation.json'
    return read_json(path) if path.exists() else None


def audit(operation, result):
    fd = os.open(STATE/'audit.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    row = dict(timestamp=datetime.now(timezone.utc).isoformat(), operation=operation,
               result=result, operator=dict(uid=os.getuid(), sudo_user=os.environ.get('SUDO_USER')))
    with os.fdopen(fd, 'a') as output:
        output.write(json.dumps(row, sort_keys=True)+'\n'); output.flush(); os.fsync(output.fileno())


def checkpoint(operation, **changes):
    operation.update(changes)
    write(STATE/'operation.json', operation)


def begin(name, **details):
    old = current_operation()
    if old and old['phase'] not in TERMINAL:
        raise h.HostingError('recovery_required', 'An administrative operation is unfinished.', operation_id=old['operation_id'])
    if old:
        write(private_directory(STATE/'history')/(old['operation_id']+'.json'), old)
    upgrade = read_json(UPDATES/'journal.json') if (UPDATES/'journal.json').exists() else {}
    if upgrade.get('phase') not in (None, 'complete', 'preflight_failed', 'preflight_passed', 'failed_before_migration'):
        raise h.HostingError('recovery_required', 'The existing upgrade journal requires recovery.', upgrade_phase=upgrade['phase'])
    if (UPDATES/'maintenance').exists():
        raise h.HostingError('recovery_required', 'An existing maintenance guard requires recovery.')
    operation = dict(operation_id=uuid.uuid4().hex, operation=name, phase='preparing',
                     previous_state=policy_state(), **details)
    checkpoint(operation)
    audit(name, dict(event='started', **operation))
    return operation


def units():
    rows = json.loads(run(['systemctl', 'list-units', '--all', '--output=json', '--no-pager',
                          '--type=service', '--type=timer', 'freo*', 'icecast2.service']))
    return {row['unit']: row for row in rows}


def unit_state(unit):
    raw = run(['systemctl', 'show', unit, '--property=LoadState,ActiveState,SubState,Result,MemoryCurrent,CPUUsageNSec,MainPID'])
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def station_rows():
    _, values = settings()
    con = recovery.connect(values['DATABASE_URL'])
    try:
        with con.cursor() as cur:
            cur.execute("SELECT id, slug, enabled, desired_state FROM stations WHERE deleted_at IS NULL ORDER BY id")
            rows = [dict(zip(('id','slug','enabled','desired_state'), row)) for row in cur.fetchall()]
            for row in rows:
                if not re.fullmatch('[a-z0-9-]+', row['slug']):
                    raise h.HostingError('invalid_configuration', 'A station identifier is invalid.')
            return rows
    finally:
        con.close()


def probe(url, *, audio=False, headers=None):
    try:
        with build_opener(ProxyHandler({})).open(Request(url, headers=headers or {}), timeout=4) as response:
            data = response.read(1024) if audio else response.read(4096)
            return dict(success=response.status == 200 and bool(data), http_status=response.status, bytes_read=len(data))
    except HTTPError as error:
        return dict(success=False, http_status=error.code)
    except Exception:
        return dict(success=False, error='unreachable')


def status():
    from .releases import version_at
    ready = probe('http://127.0.0.1:8000/ready')
    try:
        version = version_at(source())
    except Exception:
        version = None
    try:
        os_info = platform.freedesktop_os_release()
    except OSError:
        os_info = {}
    operation = current_operation()
    return dict(installation_id=read_json(STATE/'identity.json')['installation_id'], version=version,
                application_ready=ready['success'], hosting=policy_state(),
                os={k:os_info.get(k) for k in ('ID','VERSION_ID','PRETTY_NAME')},
                uptime_seconds=float(Path('/proc/uptime').read_text().split()[0]),
                operation={k:operation[k] for k in ('operation_id','operation','phase')} if operation else None)


def health():
    policy = policy_state()
    restricted = inhibited(policy)
    results = {}
    problems = []
    ready = probe('http://127.0.0.1:8000/ready')
    results['application'] = ready
    if not ready['success']:
        problems.append('application')
    try:
        stations = station_rows()
        results['database'] = dict(success=True)
    except Exception:
        stations = []
        results['database'] = dict(success=False, error='database_unavailable')
        problems.append('database')
    available = units()
    expected = list(CORE)
    # Optional components are required when installed and enabled, not guessed.
    for unit in ('freo-central-api.service','freo-mic.service', *GROUPS['scheduled-workers']):
        enabled = subprocess.run(['systemctl','is-enabled','--quiet',unit], capture_output=True, timeout=5).returncode == 0
        if enabled: expected.append(unit)
    station_units = ['freo-playout@'+row['slug']+'.service' for row in stations if row['enabled'] and row['desired_state']=='running']
    expected += ['icecast2.service', *station_units]
    for unit in sorted(set(expected)):
        broadcasting = unit == 'icecast2.service' or unit == 'freo-mic.service' or unit.startswith('freo-playout')
        observed = available.get(unit, {}).get('active', 'inactive')
        wanted = 'inactive' if broadcasting and restricted else 'active'
        ok = observed == wanted or (wanted == 'inactive' and observed == 'failed')
        results[unit] = dict(success=ok, expected=wanted, observed=observed,
                             intentionally_suspended=broadcasting and restricted)
        if not ok: problems.append(unit)
    streams = []
    listeners = None
    try:
        from .hosting_admin import observations
        data = observations() if not restricted else None
        if data is not None:
            listeners = int(data.findtext('freo_listeners') or sum(int(s.findtext('listeners') or 0) for s in data.findall('source')))
    except Exception:
        data = None
    _, values = settings()
    from urllib.parse import urlsplit
    public = values.get('PUBLIC_BASE_URL') or values.get('FREO_PUBLIC_URL') or 'http://127.0.0.1'
    host = urlsplit(public).netloc or 'localhost'
    for station in stations:
        if not station['enabled'] or station['desired_state'] != 'running': continue
        slug = station['slug']
        direct = probe('http://127.0.0.1:8001/'+slug, audio=True)
        public_result = probe('http://127.0.0.1/stream/'+slug, audio=True, headers={'Host':host})
        source_present = data is not None and any(n.get('mount') == '/'+slug for n in data.findall('source'))
        full = bool(policy.get('hosted') and listeners is not None and listeners >= policy['limits']['listeners'])
        if restricted:
            ok = not direct['success'] and not public_result['success']
        else:
            ok = source_present and all(p['success'] or (full and p.get('http_status') in (403,503)) for p in (direct,public_result))
        streams.append(dict(station_id=station['id'], direct=direct, public=public_result,
                            source_present=source_present, capacity_limited=full, success=ok))
        if not ok: problems.append('stream:'+slug)
    if policy.get('restricted'): problems.append('hosting_configuration')
    overall = ('failed' if not results['database']['success'] or not ready['success'] else 'degraded') if problems else ('intentionally_suspended' if restricted else 'healthy')
    return dict(health=overall, checks=results, streams=streams, listeners=listeners, problems=problems)


def verified_health():
    deadline = time.monotonic()+60
    while True:
        value = health()
        if value['health'] in ('healthy','intentionally_suspended'):
            return value
        if time.monotonic() >= deadline:
            raise h.HostingError('verification_failed', 'Operational health verification failed.', verification=value)
        time.sleep(2)


def resources():
    def cpu():
        return list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
    first = cpu(); time.sleep(1); second = cpu()
    delta = [b-a for a,b in zip(first,second)]
    memory = {line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
    _, values = settings()
    from .hosting_storage import files_usage, usage
    roots = media_roots(values)
    if h.read()['hosted']:
        media = usage()
    else:
        con = recovery.connect(values['DATABASE_URL'])
        try:
            with con.cursor() as cur:
                cur.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND data_type='bytea'")
                columns = cur.fetchall(); blobs = 0
                from psycopg2 import sql
                for table,column in columns:
                    cur.execute(sql.SQL('SELECT COALESCE(sum(octet_length({})),0) FROM {}').format(sql.Identifier(column),sql.Identifier(table)))
                    blobs += cur.fetchone()[0]
        finally: con.close()
        size = files_usage(roots)
        media = dict(used_bytes=size+blobs, file_bytes=size, database_media_bytes=blobs, limit_bytes=None)
    disks = []
    for name in dict.fromkeys(['/', '/tmp', str(STATE), *roots]):
        path = Path(name)
        while not path.exists(): path = path.parent
        size = shutil.disk_usage(path)
        disks.append(dict(path=name, device=path.stat().st_dev, total_bytes=size.total, used_bytes=size.used, free_bytes=size.free))
    service_resources = {}
    for unit in units():
        details = unit_state(unit)
        service_resources[unit] = {key: int(details[key]) if details.get(key,'').isdigit() else None for key in ('MemoryCurrent','CPUUsageNSec','MainPID')}
    listeners = None
    if inhibited(): listeners = 0
    else:
        try:
            from .hosting_admin import observations
            data=observations()
            listeners=int(data.findtext('freo_listeners') or sum(int(s.findtext('listeners') or 0) for s in data.findall('source')))
        except Exception: pass
    return dict(cpu_percent=round(100*(sum(delta)-delta[3]-delta[4])/max(sum(delta),1),2), sample_seconds=1,
                ram=dict(total_bytes=memory['MemTotal'],available_bytes=memory['MemAvailable'],used_bytes=memory['MemTotal']-memory['MemAvailable']),
                disks=disks, media=media, listeners=listeners, services=service_resources)


def media_roots(values):
    uploads = values.get('FREO_UPLOAD_ROOT') or '/var/lib/freo/uploads'
    return list(dict.fromkeys([values.get('FREO_MEDIA_ROOT') or '/var/lib/freo/media', uploads,
        values.get('FREO_PRODUCTION_ROOT') or str(Path(uploads)/'production'),
        values.get('FREO_BULLETIN_ROOT') or '/var/lib/freo/bulletins']))


def service_action(args):
    if args.action == 'status':
        return dict(services={unit:unit_state(unit) for unit in units()})
    operation = current_operation()
    if args.action == 'recover' and operation and operation['phase'] not in TERMINAL:
        from .admin_backup import resume
        return resume(operation)
    operation = begin('services.'+args.action)
    try:
        if args.action == 'restart':
            if args.service == 'playout':
                chosen = ['freo-playout@'+s['slug']+'.service' for s in station_rows() if s['enabled'] and s['desired_state']=='running']
            else: chosen = list(GROUPS[args.service])
            if inhibited() and (args.service in ('icecast','playout','microphone')):
                raise h.HostingError('service_inhibited', 'Hosting authority prohibits restarting broadcasting.')
        else:
            chosen = list(CORE)+list(GROUPS['scheduled-workers'])
            if subprocess.run(['systemctl','is-enabled','--quiet','freo-central-api.service'],capture_output=True).returncode==0:
                chosen.append('freo-central-api.service')
            if not inhibited():
                chosen += ['icecast2.service']
                chosen += ['freo-playout@'+s['slug']+'.service' for s in station_rows() if s['enabled'] and s['desired_state']=='running']
                if subprocess.run(['systemctl','is-enabled','--quiet','freo-mic.service'],capture_output=True).returncode==0:
                    chosen.append('freo-mic.service')
        checkpoint(operation, phase='services', units=chosen)
        if chosen: run(['systemctl','restart' if args.action=='restart' else 'start',*chosen])
        verification = verified_health()
        checkpoint(operation, phase='complete')
        return dict(operation_id=operation['operation_id'], verification=verification)
    except Exception:
        checkpoint(operation, phase='failed_before_changes')
        raise


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs['add_help'] = False
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise h.HostingError('invalid_arguments', message)


def parser():
    root = Parser(prog='freo-admin', allow_abbrev=False)
    commands = root.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('status','health','resources'): commands.add_parser(name, allow_abbrev=False)
    backup = commands.add_parser('backup', allow_abbrev=False).add_subparsers(dest='action',required=True,parser_class=Parser)
    for name in ('create','list','verify','restore'):
        child=backup.add_parser(name,allow_abbrev=False)
        if name in ('verify','restore'): child.add_argument('--id',required=True)
        if name=='restore': child.add_argument('--confirm-installation',required=True)
    update=commands.add_parser('upgrade',allow_abbrev=False).add_subparsers(dest='action',required=True,parser_class=Parser)
    update.add_parser('check',allow_abbrev=False)
    update.add_parser('apply',allow_abbrev=False).add_argument('--version',required=True)
    service=commands.add_parser('services',allow_abbrev=False).add_subparsers(dest='action',required=True,parser_class=Parser)
    service.add_parser('status',allow_abbrev=False)
    service.add_parser('recover',allow_abbrev=False)
    service.add_parser('restart',allow_abbrev=False).add_argument('--service',choices=(*GROUPS,'playout'),required=True)
    return root


def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['hosting']:
        from .hosting_admin import main as hosting_main
        return hosting_main(argv)
    result = {}; code = 0
    try:
        if os.geteuid()!=0:
            raise h.HostingError('unauthorized', 'Root authorization is required.')
        args = parser().parse_args(argv)
        os.umask(0o077)
        # Do not allow remote caller environment to redirect recovery or helpers.
        for name in list(os.environ):
            if name.startswith(('FREO_','FLASK_','PG','PYTHON')) or name in ('DATABASE_URL','SECRET_KEY','TMPDIR','TMP','TEMP'):
                os.environ.pop(name,None)
        os.environ['PATH']='/usr/sbin:/usr/bin:/sbin:/bin'
        if not (STATE/'identity.json').exists(): initialize()
        read_only = args.command in ('status','health','resources') or (args.command in ('services','backup') and args.action in ('status','list'))
        @contextmanager
        def lock():
            if read_only: yield
            else:
                with h.administrative_lock(): yield
        with lock():
            if args.command=='status': result=status()
            elif args.command=='health':
                result=health()
                if result['health'] not in ('healthy','intentionally_suspended'): code=6
            elif args.command=='resources': result=resources()
            elif args.command=='services': result=service_action(args)
            elif args.command=='backup':
                from .admin_backup import dispatch
                result=dispatch(args)
            else:
                from .admin_upgrade import dispatch
                result=dispatch(args)
        result=dict(success=code==0, **result)
    except h.HostingError as error:
        result=error.response()
        code={'invalid_arguments':2,'unauthorized':3,'service_inhibited':4,'confirmation_required':4,
              'backup_not_found':4,'release_not_found':4,'operation_busy':4,'incompatible_backup':4,'invalid_configuration':5}.get(error.code,6)
    except Exception:
        result=dict(success=False,error='operation_failed',message='Operation failed; inspect the private administrative journal. No success recorded.')
        code=6
        if os.geteuid()==0 and STATE.is_dir():
            import traceback
            fd=os.open(STATE/'last-error.log',os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as stream: traceback.print_exc(file=stream)
    result['state']=policy_state()
    if os.geteuid()==0 and STATE.is_dir():
        try: audit(' '.join(argv[:2]),result)
        except Exception:
            result.update(success=False,error='audit_failed');code=6
    print(json.dumps(dict(schema_version=1,**result),sort_keys=True))
    return code
