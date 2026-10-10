"""Exercise the shipped upload locations through an isolated real Nginx."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import pytest


def test_upload_proxy_limits(tmp_path):
    nginx=shutil.which('nginx')
    if not nginx:pytest.skip('Nginx is required for proxy integration coverage')
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            size=int(self.headers['Content-Length'])
            received.append((self.path,len(self.rfile.read(size))))
            self.send_response(202)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length','2')
            self.end_headers();self.wfile.write(b'{}')
        def log_message(self,*args):pass
    upstream=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    target=f'http://127.0.0.1:{upstream.server_port}'
    snippet=(Path(__file__).resolve().parents[1]/'deploy/nginx/admin-upload.conf').read_text()
    snippet=snippet.replace('http://127.0.0.1:8000',target)
    config=tmp_path/'nginx.conf'
    # All runtime paths and listeners are private to this test.
    config.write_text(f'''
daemon off;
master_process off;
pid {tmp_path}/nginx.pid;
error_log {tmp_path}/error.log;
events {{ worker_connections 32; }}
http {{
    access_log off;
    client_body_temp_path {tmp_path}/bodies;
    proxy_temp_path {tmp_path}/proxy;
    server {{
        listen 127.0.0.1:{port};
        {snippet}
        location / {{ proxy_pass {target}; }}
    }}
}}
''')
    process=None
    try:
        subprocess.run([nginx,'-t','-p',str(tmp_path),'-c',str(config)],check=True,capture_output=True)
        process=subprocess.Popen([nginx,'-p',str(tmp_path),'-c',str(config)],stderr=subprocess.PIPE)
        deadline=time.monotonic()+5
        while True:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.2):break
            except OSError:
                if process.poll() is not None or time.monotonic()>deadline:
                    pytest.fail((tmp_path/'error.log').read_text())
                time.sleep(.05)
        new='/admin/api/stations/test-station/imports/12345678-1234-4123-8123-123456789abc/files'
        legacy='/admin/stations/test-station/media/upload'
        artwork='/admin/api/stations/test-station/artwork'
        payload=bytes(2236885)  # Size of the production request that was rejected.
        for path,expected in [(new,202),(legacy,202),(artwork,202),('/admin/api/stations/test-station/catalog',413)]:
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.request('POST',path,body=payload)
                response=connection.getresponse();assert response.status==expected
                response.read()
            finally:connection.close()
        assert received==[(new,len(payload)),(legacy,len(payload)),(artwork,len(payload))]
        # Reject above the new limit using Content-Length, without sending 129 MiB.
        for path,limit in [(new,129),(artwork,21)]:
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            try:
                connection.putrequest('POST',path)
                connection.putheader('Content-Length',str(limit*1024*1024+1));connection.endheaders()
                response=connection.getresponse();assert response.status==413;response.read()
            finally:connection.close()
        assert len(received)==3
    finally:
        if process is not None:
            process.terminate();process.communicate(timeout=5)
        upstream.shutdown();upstream.server_close();thread.join(timeout=3)
