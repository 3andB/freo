"""Real Host/SNI, cookie and initial-login validation through private Nginx vhosts."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler

import pytest
from flask.sessions import SecureCookieSessionInterface
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db
from app.models import AdminUser
from app.services.admin_setup import bootstrap
from app.services.installation_settings import import_environment
from tests.nginx_fixture import nginx_vhost


@pytest.mark.parametrize('mode', ['ipv4', 'hostname', 'https', 'wrong-certificate',
                                  'wrong-vhost', 'broken-cookie', 'existing-admin',
                                  'missing-csrf', 'cross-origin', 'downgrade'])
def test_actual_validator_selects_freo_vhost_and_preserves_setup(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'validation.sqlite'))
    monkeypatch.setenv('SECRET_KEY', 'isolated-vhost-validation-fixture')
    app = create_app('production')
    if mode == 'broken-cookie':
        app.session_interface = SecureCookieSessionInterface()
    if mode in ('missing-csrf', 'cross-origin', 'downgrade'):
        @app.after_request
        def break_response(response):
            if mode == 'missing-csrf' and response.status_code == 200:
                response.set_data(response.get_data().replace(b'name="csrf"', b'name="removed"'))
            elif response.status_code == 302:
                response.headers['Location'] = ('http://freo-validation.invalid/admin/setup' if mode == 'downgrade'
                                                else 'https://another-site.invalid/admin/setup')
            return response
    backend = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=backend.serve_forever, daemon=True)
    thread.start()
    try:
        hostname = '198.51.100.24' if mode == 'ipv4' else 'freo-validation.invalid'
        tls = mode in ('https', 'wrong-certificate', 'downgrade')
        with nginx_vhost(f'http://127.0.0.1:{backend.server_port}', hostname, tls=tls,
                         certificate_hostname='wrong.invalid' if mode == 'wrong-certificate' else None,
                         server_name='other.invalid' if mode == 'wrong-vhost' else None) as proxy:
            app.config.update(PUBLIC_BASE_URL=proxy.base, FREO_DOMAIN=hostname)
            with app.app_context():
                db.create_all()
                import_environment()
                bootstrap()
                user = AdminUser.query.one()
                if mode == 'existing-admin':
                    user.setup_required = False
                    db.session.commit()
                original = (user.password_hash, user.setup_required)
            if proxy.certificate:
                monkeypatch.setenv('SSL_CERT_FILE', str(proxy.certificate))
            if not tls:
                with pytest.raises(HTTPError) as error:
                    build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{proxy.port}/admin/login')
                assert error.value.code == 404  # Deliberately different default vhost.
            result = subprocess.run([sys.executable, 'scripts/validate-admin-login.py'],
                                    env=os.environ.copy(), capture_output=True, text=True, timeout=30)
            failures = {'wrong-certificate': 'TLS certificate verification failed',
                        'wrong-vhost': 'HTTP 404', 'broken-cookie': 'cookie policy',
                        'missing-csrf': 'CSRF token', 'cross-origin': 'Redirect left', 'downgrade': 'Redirect left'}
            if mode in failures:
                assert result.returncode == 1, result.stdout
                assert 'LOCAL APPLICATION VALIDATION — FAILED' in result.stderr
                assert failures[mode] in result.stderr
            else:
                assert result.returncode == 0, result.stderr
                assert 'LOCAL APPLICATION VALIDATION — PASSED' in result.stdout
                assert 'EXTERNAL ACCESS VALIDATION — NOT CHECKED' in result.stdout
                log = proxy.access_log.read_text()
                assert f'{hostname}:{proxy.port}|' in log
                if tls:
                    assert f'|{hostname}|POST|/admin/login|302' in log  # Real TLS SNI and successful login.
                if mode != 'existing-admin':
                    assert '|POST|/admin/login|302' in log
                    assert '|GET|/admin/setup|200' in log
                    assert 'setup remains unclaimed' in result.stdout
            with app.app_context():
                user = AdminUser.query.one()
                assert (user.password_hash, user.setup_required) == original
                db.session.remove()
                db.engine.dispose()
    finally:
        backend.shutdown()
        backend.server_close()
        thread.join(timeout=5)
