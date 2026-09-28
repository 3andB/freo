#!/usr/bin/env python3
"""Test a supplied source/venv against a disposable PostgreSQL cluster and Gunicorn.

Uses no installed .env, production database or system service. Nginx listens
only on temporary loopback ports and proxies to private Gunicorn Unix sockets.
Run as root for the same admin bootstrap command used by the installer.
This is package acceptance, not a substitute for full fresh-VM provisioning.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('venv', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as root: the installer admin bootstrap requires it')
    source, venv, output = (p.resolve() for p in (args.source, args.venv, args.output))
    sys.path.insert(0, str(source))
    from tests.nginx_fixture import nginx_vhost
    output.mkdir(parents=True, exist_ok=False)
    pg_bin = Path(subprocess.check_output(['pg_config', '--bindir'], text=True).strip())
    cluster = Path(tempfile.mkdtemp(prefix='freo-install-pg-'))
    owner = pwd.getpwnam('postgres')
    os.chown(cluster, owner.pw_uid, owner.pw_gid)
    pg = ['runuser', '-u', 'postgres', '--']
    report = dict(status='running', scope='Disposable database and package startup; fresh VM pending', checks=[])
    proxies = ExitStack()
    try:
        with (output / 'postgres.log').open('w') as log:
            subprocess.run(pg + [str(pg_bin / 'initdb'), '-D', str(cluster / 'data'),
                                 '-A', 'trust', '-U', 'freo_install_test', '--no-locale', '--encoding=UTF8'],
                           check=True, stdout=log, stderr=subprocess.STDOUT)
            subprocess.run(pg + [str(pg_bin / 'pg_ctl'), '-D', str(cluster / 'data'),
                                 '-l', str(cluster / 'server.log'), '-o', f"-k {cluster} -h '' -F", '-w', 'start'],
                           check=True, stdout=log, stderr=subprocess.STDOUT)
        for index, scheme in enumerate(('postgresql', 'postgresql+psycopg', 'postgresql+psycopg2')):
            database = f'install_test_{index}'
            subprocess.run(pg + [str(pg_bin / 'createdb'), '-h', str(cluster), '-U', 'freo_install_test', database], check=True)
            state = cluster / database
            state.mkdir()
            hostname = '198.51.100.24' if index == 0 else 'freo-validation.invalid'
            proxy = proxies.enter_context(nginx_vhost(f'http://unix:{state}/web.sock', hostname, tls=index == 2))
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('FREO_', 'PG', 'FLASK_', 'SQLALCHEMY_', 'PYTHON'))
                   and k not in ('DATABASE_URL', 'SECRET_KEY')}
            env.update(FREO_ENV_FILE='/dev/null', FLASK_ENV='production',
                       SECRET_KEY='disposable-install-acceptance-only',
                       DATABASE_URL=f'{scheme}://freo_install_test@/{database}?host={cluster}',
                       PUBLIC_BASE_URL=proxy.base, FREO_DOMAIN=hostname,
                       FREO_MEDIA_ROOT=str(state / 'media'), FREO_API_STATE_DIR=str(state / 'api'),
                       FREO_STATS_STATE_DIR=str(state / 'statistics'), PYTHONDONTWRITEBYTECODE='1')
            if proxy.certificate:
                env['SSL_CERT_FILE'] = str(proxy.certificate)
            with (output / f'{index}-application.log').open('w') as log:
                command = [str(venv / 'bin/python'), '-m', 'flask', '--app', 'wsgi:app']
                for step in (['db', 'upgrade'], ['db', 'upgrade'], ['settings', 'import-environment'], ['admin', 'bootstrap']):
                    subprocess.run(command + step, cwd=source, env=env, check=True, stdout=log, stderr=subprocess.STDOUT)
                current = subprocess.check_output(command + ['db', 'current'], cwd=source, env=env, text=True).strip()
                head = subprocess.check_output(command + ['db', 'heads'], cwd=source, env=env, text=True).strip()
                if current != head:
                    raise RuntimeError(f'{scheme}: migration did not reach head')
                verification = '''
import json
from app import create_app
from app.extensions import db
from app.models import AdminUser, Station
from app.version import VERSION
app = create_app()
with app.app_context():
    admin = AdminUser.query.one()
    assert admin.username == 'admin' and admin.installation_admin and admin.setup_required
    assert Station.query.count() == 0
    db.session.remove()
    db.engine.dispose()
print(json.dumps({'version': VERSION, 'bootstrap': 'passed', 'empty_station_library': True}))
'''
                details = json.loads(subprocess.check_output([str(venv / 'bin/python'), '-c', verification],
                                    cwd=source, env=env, text=True))
                for restart in range(2):
                    socket = state / 'web.sock'
                    web = subprocess.Popen([str(venv / 'bin/python'), '-m', 'gunicorn', '--workers', '1',
                                            '--no-control-socket', '--bind', f'unix:{socket}', 'wsgi:app'],
                                           cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
                    try:
                        deadline = time.monotonic() + 30
                        while True:
                            probe = subprocess.run(['curl', '--fail', '--silent', '--max-time', '2',
                                                    '--unix-socket', str(socket), 'http://localhost/ready'],
                                                   capture_output=True)
                            if probe.returncode == 0:
                                break
                            if web.poll() is not None or time.monotonic() > deadline:
                                raise RuntimeError(f'{scheme}: Gunicorn readiness failed (restart {restart})')
                            time.sleep(0.25)
                        for route in ('/health', '/ready', '/admin/login'):
                            subprocess.run(['curl', '--fail', '--silent', '--show-error', '--max-time', '5',
                                            '--unix-socket', str(socket), 'http://localhost' + route],
                                           check=True, stdout=subprocess.DEVNULL)
                        # Exercise the actual final installer validator through
                        # Nginx, with real sessions/CSRF after migration/bootstrap.
                        login = subprocess.run([str(venv / 'bin/python'), str(source / 'scripts/validate-admin-login.py')],
                                               cwd=source, env=env, capture_output=True, text=True)
                        log.write(login.stdout + login.stderr)
                        log.flush()
                        login.check_returncode()
                        if 'LOCAL APPLICATION VALIDATION — PASSED' not in login.stdout:
                            raise RuntimeError('Local Nginx/admin validation did not report success')
                    finally:
                        web.terminate()
                        try:
                            web.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            web.kill()
                            web.wait()
            routing = proxy.access_log.read_text()
            if f'{hostname}:{proxy.port}|' not in routing or '|POST|/admin/login|302' not in routing:
                raise RuntimeError('Configured Host/login path was not used')
            if proxy.certificate and f'|{hostname}|POST|' not in routing:
                raise RuntimeError('Configured TLS SNI was not used')
            shutil.copyfile(proxy.access_log, output / f'{index}-nginx-access.log')
            # Successful validation must leave initial setup and credentials alone.
            subprocess.run([str(venv / 'bin/python'), '-c', verification], cwd=source, env=env,
                           check=True, stdout=subprocess.DEVNULL)
            report['checks'].append(dict(scheme=scheme, schema=current, migration='passed',
                                         public_origin=proxy.base, local_nginx_login='passed',
                                         tls_sni='passed' if proxy.certificate else 'not applicable',
                                         gunicorn_start_and_restart='passed', health='passed', readiness='passed',
                                         admin_login='passed', **details))
        report['status'] = 'passed'
        print(json.dumps(report, indent=2))
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        proxies.close()
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        subprocess.run(pg + [str(pg_bin / 'pg_ctl'), '-D', str(cluster / 'data'), '-m', 'immediate', 'stop'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if (cluster / 'server.log').exists():
            shutil.copyfile(cluster / 'server.log', output / 'postgres-server.log')
        shutil.rmtree(cluster)


if __name__ == '__main__':
    main()
