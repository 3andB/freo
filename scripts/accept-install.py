#!/usr/bin/env python3
"""Explicit destructive acceptance on a disposable fresh installation, never a health probe."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
STATE = Path('/var/lib/freo-admin/rc1-acceptance')
SLUGS = ('rc1-test-one', 'rc1-test-two')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, code=0, timeout=120):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    require(result.returncode == code, f'{Path(args[0]).name} failed (expected exit {code}, got {result.returncode}); inspect local service logs')
    return result.stdout


def admin(*args, code=0):
    result = json.loads(run('freo-admin', *args, code=code, timeout=1800))
    require(result['success'] == (code == 0), 'Administrative result contradicts exit status')
    return result


def station(*args, code=0):
    return run(str(ROOT/'venv/bin/flask'), '--app', 'wsgi:app', 'station', *args, code=code)


def save(name, value):
    path = STATE/name
    with path.open('w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2)
        stream.write('\n')


def login_tools():
    spec = importlib.util.spec_from_file_location('login_validation', ROOT/'scripts/validate-admin-login.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def form(client, base, path, values):
    module = login_tools()
    _, body = module.fetch(client, base+path, 'Acceptance form')
    token = re.search(r'name="csrf" value="([^"]+)"', body)
    require(token is not None, 'Missing CSRF form token')
    return module.fetch(client, Request(base+path, data=urlencode(dict(values, csrf=token.group(1))).encode()), 'Acceptance submission')


def stream(base, slug, direct=False):
    module = login_tools()
    url = 'http://127.0.0.1:8001/'+slug if direct else base+'/stream/'+slug
    client, _ = module.client_for(url, local=True)
    response = client.open(url, timeout=10)
    require(response.status == 200 and response.headers.get_content_type() == 'audio/mpeg', 'Stream is not MP3')
    require(bool(response.read(1024)), 'Stream has no audio bytes')
    return response


def streams(base):
    for slug in SLUGS:
        for direct in (False, True):
            with stream(base, slug, direct):
                pass


def fresh(app):
    from app.models import AdminUser, Station
    from app.services.installation_settings import get_setting
    from freo_ops import hosting
    require(hosting.read() == {'hosted': False}, 'Fresh acceptance requires untouched self-hosted policy')
    require(Station.query.count() == 0, 'Fresh acceptance refuses existing stations')
    users = AdminUser.query.all()
    require(len(users) == 1 and users[0].username == 'admin' and users[0].setup_required,
            'Fresh acceptance requires one unclaimed bootstrap account')
    base = get_setting('PUBLIC_BASE_URL').rstrip('/')
    module = login_tools()
    client, _ = module.client_for(base, local=True)
    url, _ = form(client, base, '/admin/login', dict(email='admin', password='IAmOnTheAir'))
    require(urlsplit(url).path == '/admin/setup', 'Bootstrap login did not require setup')
    password = secrets.token_urlsafe(32)
    save('credentials.json', dict(email='rc1-acceptance@example.test', password=password))
    url, _ = form(client, base, '/admin/setup', dict(email='rc1-acceptance@example.test', password=password, confirmation=password))
    require(urlsplit(url).path == '/admin', 'First-use setup failed')
    client, _ = module.client_for(base, local=True)
    url, _ = form(client, base, '/admin/login', dict(email='admin', password='IAmOnTheAir'))
    require(urlsplit(url).path == '/admin/login', 'Bootstrap password still works')
    url, _ = form(client, base, '/admin/login', dict(email='admin', password=password))
    require(urlsplit(url).path == '/admin', 'Replacement password did not authenticate')
    for slug in SLUGS:
        station('create', slug, '--name', 'RC1 acceptance '+slug, '--start', '--json')
    # These streams contain the engine's generated fallback audio. No copyrighted
    # media or direct database fixture bypasses are needed to prove provisioning.
    for attempt in range(30):
        try:
            streams(base)
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(2)
    status = admin('status')
    admin('health')
    admin('services', 'restart', '--service', 'application')
    client, _ = module.client_for(base, local=True)
    url, _ = form(client, base, '/admin/login', dict(email='admin', password=password))
    require(urlsplit(url).path == '/admin', 'Authentication did not survive application restart')
    return dict(base=base, installation_id=status['installation_id'],
                checks=['bootstrap_setup', 'bootstrap_password_revoked', 'authenticated_after_restart',
                        'station_creation', 'direct_and_nginx_audio', 'self_hosted_health'])


def hosted(app, previous):
    from app.extensions import db
    from app.models import AdminUser, Station
    from app.services.station_audio import active_settings, queue_settings, process_audio, validate_settings
    from freo_ops import hosting, hosting_storage
    require(admin('status')['installation_id'] == previous['installation_id'], 'Fixture belongs to another installation')
    rows = Station.query.filter_by(deleted_at=None).all()
    require({row.slug for row in rows} == set(SLUGS), 'Hosted acceptance refuses non-fixture stations')
    user = AdminUser.query.filter_by(installation_admin=True).one()
    for row in rows:
        queue_settings(row, validate_settings(dict(active_settings(row.stream), bitrate=128)), row.stream.audio_revision, user)
        db.session.commit()
        process_audio(row)
    admin('hosting', 'configure', '--plan', 'custom', '--stations', '2', '--listeners', '2', '--bitrate', '128', '--storage-gb', '1')
    station('create', 'rc1-over-limit', '--name', 'Must be refused', '--json', code=1)
    require(Station.query.filter_by(slug='rc1-over-limit').count() == 0, 'Station limit was not enforced')
    try:
        validate_settings(dict(active_settings(rows[0].stream), bitrate=192))
    except (ValueError, hosting.HostingError):
        pass
    else:
        raise RuntimeError('Bitrate limit was not enforced')
    encoded = json.loads(run('ffprobe', '-v', 'error', '-read_intervals', '%+#50', '-show_entries', 'stream=bit_rate', '-of', 'json', 'http://127.0.0.1:8001/'+SLUGS[0]))
    require(encoded['streams'][0]['bit_rate'] == '128000', 'Actual encoder is not 128 kbps')
    try:
        with hosting_storage.reserve(1_000_000_001):
            raise RuntimeError('Storage quota was not enforced')
    except hosting.HostingError as error:
        require(error.code == 'storage_limit_exceeded', 'Storage failed for a reason other than quota')
    time.sleep(2)
    from urllib.error import HTTPError
    connections = []
    try:
        connections.append(stream(previous['base'], SLUGS[0]))
        connections.append(stream(previous['base'], SLUGS[1], True))
        try:
            with stream(previous['base'], SLUGS[0], True):
                raise RuntimeError('Aggregate listener quota was not enforced')
        except HTTPError as error:
            require(error.code in (403, 503), 'Unexpected listener rejection')
        admin('hosting', 'verify')
    finally:
        for connection in connections:
            connection.close()
    time.sleep(2)
    admin('hosting', 'past-due')
    streams(previous['base'])
    for state in ('suspend', 'maintenance'):
        admin('hosting', state)
        admin('health')
        admin('hosting', 'verify')
        run('bash', str(ROOT/'scripts/validate-install.sh'))
        # Even root starting ordinary units must not bypass persisted guards.
        subprocess.run(['systemctl', 'start', 'icecast2.service', 'freo-playout@'+SLUGS[0]+'.service'], capture_output=True, timeout=30)
        admin('hosting', 'verify')
        admin('hosting', 'activate')
        streams(previous['base'])
    previous['checks'] += ['station_limit', 'bitrate_limit', 'actual_128kbps', 'storage_quota',
                           'aggregate_listener_limit', 'past_due_audio', 'suspension',
                           'maintenance', 'restart_inhibition', 'explicit_reactivation']
    return previous


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('phase', choices=('fresh', 'hosted'))
    parser.add_argument('--confirm-hostname', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or args.confirm_hostname != socket.gethostname():
        parser.error('Root and the exact disposable hostname confirmation are required')
    os.umask(0o077)
    os.chdir(ROOT)
    os.environ['FREO_ENV_FILE'] = str(ROOT/'.env')
    sys.path.insert(0, str(ROOT))
    from freo_ops.hosting import trusted
    trusted(ROOT/'scripts/accept-install.py')
    # A fresh run cannot overwrite prior acceptance or private credentials.
    if args.phase == 'fresh':
        STATE.mkdir(mode=0o700, exist_ok=False)
    from freo_ops.admin import private_directory
    private_directory(STATE)
    from app import create_app
    app = create_app()
    report = dict(success=False, phase=args.phase)
    try:
        with app.app_context():
            result = fresh(app) if args.phase == 'fresh' else hosted(app, json.loads((STATE/'fresh.json').read_text()))
        report.update(result, success=True)
    except Exception as error:
        report['error'] = type(error).__name__
        # Raw subprocess/HTTP/DB diagnostics can contain credentials. Retain a
        # stage and error type, not arbitrary exception text in public evidence.
        if isinstance(error, RuntimeError):
            report['message'] = str(error)
    save(args.phase+'.json', report)
    print(json.dumps(report))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
