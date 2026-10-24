"""Real dual-stack vhost routing and the narrowly allowed proxy migration."""
import http.client
import os
from pathlib import Path
import pwd
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from freo_ops import proxy_ipv6 as proxy
from freo_ops.recovery import RecoveryError

ROOT = Path(__file__).resolve().parents[1]


def test_template_transition_allows_only_ipv6_listener_additions():
    for name in proxy.TEMPLATES:
        current = (ROOT/name).read_text()
        old = '\n'.join(line for line in current.split('\n') if 'listen [::]:' not in line)
        assert proxy.allowed_template_change(name, old, current)
        assert not proxy.allowed_template_change(name, old, current.replace('return 404', 'return 200')+'# other change\n')
        assert proxy.with_ipv6(current) == current
    assert not proxy.allowed_template_change('deploy/icecast/config', 'listen 80;', 'listen 80;\nlisten [::]:80;')


def test_certbot_listener_migration_preserves_tls_and_redirects():
    old = '''server {
    listen 443 ssl; # managed by Certbot
    server_name radio.example;
    ssl_certificate /etc/letsencrypt/live/radio.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/radio.example/privkey.pem;
}
server {
    listen 80;
    server_name radio.example;
    return 301 https://$host$request_uri;
}
'''
    changed = proxy.with_ipv6(old)
    assert '    listen [::]:443 ssl;' in changed
    assert '    listen [::]:80;' in changed
    assert '\n'.join(line for line in changed.split('\n') if 'listen [::]:' not in line) == old
    assert proxy.with_ipv6(changed) == changed


@pytest.mark.parametrize('body', [
    'server {\n listen 80;\n}\nserver {\n listen 80;\n}',
    'server {\n listen 127.0.0.1:80;\n}',
    'server {\n listen 80;\n listen [::1]:80;\n}',
    'server {\n listen 443 ssl;\n listen [::]:443 ssl http2;\n}',
])
def test_custom_listener_layout_requires_review(body):
    with pytest.raises(RecoveryError):
        proxy.with_ipv6(body)


def test_apply_checks_preflight_content_and_rolls_back_invalid_nginx(tmp_path, monkeypatch):
    site = tmp_path/'freo'
    before = 'server {\n    listen 80;\n}\n'
    site.write_text(before);site.chmod(0o640)
    changes = {site: (before, proxy.with_ipv6(before))}
    calls = []
    def invalid(command):
        calls.append(command)
        raise RecoveryError('nginx configuration rejected')
    monkeypatch.setattr(proxy, 'run', invalid)
    with pytest.raises(RecoveryError, match='configuration rejected'):
        proxy.apply(changes)
    assert site.read_text() == before and site.stat().st_mode & 0o777 == 0o640
    assert calls == [['nginx', '-t']]
    site.write_text(before+'# operator edit\n')
    with pytest.raises(RecoveryError, match='changed after preflight'):
        proxy.apply(changes)
    assert site.read_text().endswith('# operator edit\n')


@pytest.mark.skipif(os.geteuid()!=0, reason='Root-owned migration fixture')
def test_plan_updates_only_freo_sites_and_rejects_unsafe_files(tmp_path):
    available = tmp_path/'sites-available';available.mkdir()
    enabled = tmp_path/'sites-enabled';enabled.mkdir()
    body = (ROOT/'deploy/nginx/freo.conf.template').read_text().replace('    listen [::]:80;\n', '')
    site = available/'freo';site.write_text(body)
    other = available/'default';other.write_text('server {\n listen 80 default_server;\n}\n')
    (enabled/site.name).symlink_to(site)
    (enabled/other.name).symlink_to(other)
    (available/'freo.pre-static-assets').write_text(body)
    assert set(proxy.plan(available)) == {site}
    reject = available/'freo-reject-unknown'
    reject.write_text('\n'.join(line for line in (ROOT/'deploy/nginx/reject-unknown.conf').read_text().split('\n') if 'listen [::]:' not in line))
    (enabled/reject.name).symlink_to(reject)
    assert set(proxy.plan(available)) == {site, reject}
    site.chmod(0o666)
    with pytest.raises(RecoveryError, match='root-owned'):
        proxy.plan(available)
    site.chmod(0o644);site.write_text('server {\n listen 80;\n}\n')
    with pytest.raises(RecoveryError, match='Customized primary'):
        proxy.plan(available)


@pytest.mark.parametrize('template,placeholder', [
    ('freo.conf.template','FREO_SERVER_NAME'),
    ('custom-domain.conf.template','FREO_CUSTOM_HOSTNAME'),
])
def test_actual_templates_route_web_and_streams_on_both_families(tmp_path, template, placeholder):
    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'fixture-audio' if self.path == '/fixture' else b'freo-web'
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Backend)
    thread = threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    # Binding explicitly proves the test host supports the address family.
    with socket.socket(socket.AF_INET6) as listener:
        listener.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1);listener.bind(('::1',port))
    snippets=tmp_path/'snippets';snippets.mkdir();(snippets/'freo-stations').mkdir()
    (snippets/'freo-stream.conf').write_text('')
    (snippets/'freo-admin-upload.conf').write_text('')
    (snippets/'freo-static-assets.conf').write_text('')
    mount=(ROOT/'deploy/nginx/station-location.conf.template').read_text().replace('__SLUG__','fixture').replace('127.0.0.1:8001',f'127.0.0.1:{server.server_port}')
    (snippets/'freo-stations/fixture.conf').write_text(mount)
    body=(ROOT/'deploy/nginx'/template).read_text().replace(placeholder,'freo.example.test')
    body=body.replace('listen 80;',f'listen 127.0.0.1:{port};').replace('listen [::]:80;',f'listen [::1]:{port};')
    body=body.replace('/etc/nginx/snippets',str(snippets)).replace('127.0.0.1:8000',f'127.0.0.1:{server.server_port}')
    user=f'user {pwd.getpwuid(os.getuid()).pw_name};' if os.geteuid()==0 else ''
    config=tmp_path/'nginx.conf'
    config.write_text(f'''{user}
daemon off;
master_process off;
pid {tmp_path}/nginx.pid;
error_log {tmp_path}/error.log;
events {{ worker_connections 64; }}
http {{
 client_body_temp_path {tmp_path}/body;
 proxy_temp_path {tmp_path}/proxy;
 access_log off;
 server {{ listen 127.0.0.1:{port} default_server; listen [::1]:{port} default_server; return 404; }}
 {body}
}}
''')
    with (tmp_path/'nginx-process.log').open('w') as log:
        process=subprocess.Popen(['nginx','-p',str(tmp_path),'-c',str(config)],stdout=log,stderr=subprocess.STDOUT)
        try:
            for attempt in range(100):
                assert process.poll() is None,(tmp_path/'nginx-process.log').read_text()
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                except OSError:time.sleep(.05)
            else:pytest.fail('Private nginx did not start')
            for host in ('127.0.0.1','::1'):
                for path,expected in (('/admin/login',b'freo-web'),('/stream/fixture',b'fixture-audio')):
                    connection=http.client.HTTPConnection(host,port,timeout=5)
                    try:
                        connection.request('GET',path,headers={'Host':'freo.example.test'})
                        response=connection.getresponse()
                        assert response.status==200,(host,path,response.status)
                        assert response.read()==expected
                    finally:connection.close()
                connection=http.client.HTTPConnection(host,port,timeout=5)
                try:
                    connection.request('GET','/',headers={'Host':'unknown.example.test'})
                    assert connection.getresponse().status==404
                finally:connection.close()
        finally:
            process.terminate();process.wait(timeout=10)
            server.shutdown();server.server_close();thread.join(timeout=5)
