"""Run the installed validator against actual local HTTP/TLS servers."""
import os
import subprocess
import threading
import pytest
from werkzeug.serving import make_server
from flask.sessions import SecureCookieSessionInterface
from app import create_app
from app.extensions import db
from app.models import AdminUser
from app.services.admin_setup import bootstrap
from app.services.installation_settings import import_environment


@pytest.mark.parametrize('mode',['http','https','broken-cookie'])
def test_installer_login_validation_leaves_setup_unclaimed(tmp_path,monkeypatch,mode):
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null')
    monkeypatch.setenv('FLASK_ENV','production')
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(tmp_path/'validator.sqlite'))
    monkeypatch.setenv('SECRET_KEY','private-isolated-validator-fixture')
    app=create_app('production')
    tls=None
    if mode=='https':
        cert,key=tmp_path/'cert.pem',tmp_path/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=(str(cert),str(key))
        monkeypatch.setenv('SSL_CERT_FILE',str(cert))
    if mode=='broken-cookie':
        # The rc.1/rc.2 production policy that broke actual browsers.
        app.session_interface=SecureCookieSessionInterface()
    server=make_server('127.0.0.1',0,app,threaded=True,ssl_context=tls)
    app.config['PUBLIC_BASE_URL']=f'{"https" if tls else "http"}://127.0.0.1:{server.server_port}'
    with app.app_context():
        db.create_all();import_environment();bootstrap()
        original=AdminUser.query.one().password_hash
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        import sys
        result=subprocess.run([sys.executable,'scripts/validate-admin-login.py'],env=os.environ.copy(),capture_output=True,text=True,timeout=30)
        if mode=='broken-cookie':
            assert result.returncode==1 and 'LOCAL APPLICATION VALIDATION — FAILED' in result.stderr
        else:
            assert result.returncode==0,result.stderr
            assert 'setup remains unclaimed' in result.stdout
        with app.app_context():
            user=AdminUser.query.one()
            assert user.setup_required and user.password_hash==original
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


@pytest.mark.parametrize('failure', ['timeout', 'dns', 'tls', 'http', 'redirect'])
def test_external_failure_does_not_reverse_local_success(monkeypatch, capsys, failure):
    import runpy
    validator = runpy.run_path('scripts/validate-admin-login.py')
    # The real main function uses its defining globals, not runpy's returned copy.
    namespace = validator['main'].__globals__
    monkeypatch.setitem(namespace, 'validate', lambda: ('http://143.198.117.46', True))
    def fail(_base):
        raise validator['ValidationError']('External ' + failure + ' fixture')
    monkeypatch.setitem(namespace, 'external_access', fail)
    assert validator['main'](['--external']) == 0
    captured = capsys.readouterr()
    assert 'LOCAL APPLICATION VALIDATION — PASSED' in captured.out
    assert 'EXTERNAL ACCESS VALIDATION — NOT CONFIRMED' in captured.out
    assert 'Local application validation passed.' in captured.out
    assert not captured.err


def test_external_success_is_reported_separately(monkeypatch, capsys):
    import runpy
    validator = runpy.run_path('scripts/validate-admin-login.py')
    namespace = validator['main'].__globals__
    monkeypatch.setitem(namespace, 'validate', lambda: ('http://143.198.117.46', True))
    monkeypatch.setitem(namespace, 'external_access', lambda _base: None)
    assert validator['main'](['--external']) == 0
    assert 'EXTERNAL ACCESS VALIDATION — PASSED from this VM' in capsys.readouterr().out


def test_local_failure_remains_fatal_and_skips_external_probe(monkeypatch, capsys):
    import runpy
    validator = runpy.run_path('scripts/validate-admin-login.py')
    namespace = validator['main'].__globals__
    def fail():
        raise validator['ValidationError']('Login cookie policy failed.')
    monkeypatch.setitem(namespace, 'validate', fail)
    monkeypatch.setitem(namespace, 'external_access', lambda _base: pytest.fail('External probe ran after local failure'))
    assert validator['main'](['--external']) == 1
    captured = capsys.readouterr()
    assert 'LOCAL APPLICATION VALIDATION — FAILED' in captured.err
    assert 'PASSED' not in captured.out


def test_installer_success_prints_exact_ip_admin_url(tmp_path):
    from pathlib import Path
    script = Path('scripts/provision.sh').read_text()
    footer = script[script.index("printf '\\nFreo installation complete."):]
    result = subprocess.run(['bash', '-c', footer], env=dict(os.environ, public_base='http://143.198.117.46'),
                            text=True, capture_output=True)
    assert result.returncode == 0
    assert 'Freo installation complete.\nOpen: http://143.198.117.46/admin/login\n' in result.stdout


def test_real_external_probe_succeeds_without_sending_credentials():
    import runpy
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    received = []
    class Login(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.command, self.path, self.headers.get('Cookie'), self.headers.get('Authorization')))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'<input name="email"><input name="password"><input name="csrf">')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Login)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        validator = runpy.run_path('scripts/validate-admin-login.py')
        validator['external_access'](f'http://127.0.0.1:{server.server_port}')
        assert received == [('GET', '/admin/login', None, None)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_suspended_unclaimed_setup_validates_login_without_bypassing_guard(tmp_path, monkeypatch):
    import runpy
    from freo_ops import hosting
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'suspended.sqlite'))
    monkeypatch.setenv('SECRET_KEY', 'private-suspended-fixture')
    app = create_app('production')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    app.config['PUBLIC_BASE_URL'] = f'http://127.0.0.1:{server.server_port}'
    with app.app_context():
        db.create_all(); import_environment(); bootstrap()
    monkeypatch.setattr(hosting, 'read', lambda: dict(hosted=True, plan='starter', status='suspended', limits=hosting.PLANS['starter']))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        validator = runpy.run_path('scripts/validate-admin-login.py')
        assert validator['validate']() == (app.config['PUBLIC_BASE_URL'], True)
        with app.app_context():
            assert AdminUser.query.one().setup_required
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
