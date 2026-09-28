"""Private Nginx vhosts for package acceptance; never uses system configuration."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import tempfile
import time


def unused_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


@dataclass
class Vhost:
    base: str
    port: int
    certificate: Path | None
    access_log: Path


@contextmanager
def nginx_vhost(upstream, hostname, *, tls=False, certificate_hostname=None, server_name=None):
    """Default HTTP vhost returns 404; default TLS vhost rejects missing/wrong SNI."""
    nginx = shutil.which('nginx')
    if not nginx:
        raise RuntimeError('Nginx is required for installer vhost acceptance')
    with tempfile.TemporaryDirectory(prefix='freo-vhost-') as temporary:
        root = Path(temporary)
        port = unused_port()
        certificate = None
        tls_options = ''
        default_options = 'return 404;'
        if tls:
            certificate, key = root / 'cert.pem', root / 'key.pem'
            name = certificate_hostname or hostname
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', str(key), '-out', str(certificate), '-days', '1',
                            '-subj', f'/CN={name}', '-addext', f'subjectAltName=DNS:{name}'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            tls_options = f'ssl_certificate {certificate}; ssl_certificate_key {key};'
            default_options = 'ssl_reject_handshake on;'
        listen = f'127.0.0.1:{port}' + (' ssl' if tls else '')
        user = f'user {pwd.getpwuid(os.getuid()).pw_name};' if os.getuid() == 0 else ''
        config = root / 'nginx.conf'
        access_log = root / 'access.log'
        config.write_text(f'''
{user}
daemon off;
master_process off;
pid {root}/nginx.pid;
error_log {root}/error.log info;
events {{ worker_connections 64; }}
http {{
    client_body_temp_path {root}/body;
    proxy_temp_path {root}/proxy;
    log_format routing '$http_host|$ssl_server_name|$request_method|$uri|$status';
    access_log {access_log} routing;
    server {{ listen {listen} default_server; server_name _; {default_options} }}
    server {{
        listen {listen};
        server_name {server_name or hostname};
        {tls_options}
        location / {{
            proxy_pass {upstream};
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host "";
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }}
    }}
}}
''')
        with (root / 'process.log').open('w') as log:
            process = subprocess.Popen([nginx, '-p', str(root), '-c', str(config)],
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 10
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('Private Nginx fixture failed: ' + (root/'process.log').read_text())
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('Private Nginx fixture did not start')
                        time.sleep(.05)
                yield Vhost(f'{"https" if tls else "http"}://{hostname}:{port}', port, certificate, access_log)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
