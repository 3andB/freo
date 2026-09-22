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
            assert result.returncode==1 and 'validation failed' in result.stderr
        else:
            assert result.returncode==0,result.stderr
            assert 'setup remains unclaimed' in result.stdout
        with app.app_context():
            user=AdminUser.query.one()
            assert user.setup_required and user.password_hash==original
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
