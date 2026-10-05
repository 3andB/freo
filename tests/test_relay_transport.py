"""The transport guard never follows redirects or re-resolves a validated host."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import socket
import threading
import pytest
from app.services.relay_transport import open_upstream, RelayTransport


@pytest.fixture
def origin():
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            seen.append(self.path)
            if self.path == '/redirect':
                self.send_response(302);self.send_header('Location','http://169.254.169.254/latest');self.end_headers()
            elif self.path == '/playlist':
                self.send_response(200);self.send_header('Content-Type','application/vnd.apple.mpegurl');self.end_headers();self.wfile.write(b'#EXTM3U')
            else:
                self.send_response(200);self.send_header('Content-Type','audio/mpeg');self.end_headers();self.wfile.write(self.headers['Host'].encode() if self.path=='/headers' else b'audio')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', seen
    finally: server.shutdown();server.server_close();thread.join(timeout=2)


def test_redirect_and_playlist_rejected(origin):
    url, seen = origin
    for path in ('/redirect','/playlist'):
        with pytest.raises(ValueError):open_upstream(url+path,'127.0.0.1/32')
    assert seen==['/redirect','/playlist']


def test_pinned_dns_and_original_host_header(origin,monkeypatch):
    url, seen = origin
    original=socket.getaddrinfo;lookups=[]
    def dns(host,*args,**kwargs):
        lookups.append(host)
        return original('127.0.0.1' if host=='radio.test' else host,*args,**kwargs)
    monkeypatch.setattr(socket,'getaddrinfo',dns)
    connection,response,_=open_upstream(url.replace('127.0.0.1','radio.test')+'/headers','127.0.0.1/32')
    try: assert response.read().decode()=='radio.test:'+url.rsplit(':',1)[1]
    finally: connection.close()
    assert lookups==['radio.test','127.0.0.1']


def test_capability_revocation_and_no_open_proxy(origin):
    from urllib.parse import urlsplit
    url, seen=origin
    guard=RelayTransport(0,'127.0.0.1/32')
    try:
        capability=guard.configure(1,url+'/audio');parsed=urlsplit(capability)
        def get(path):
            conn=http.client.HTTPConnection(parsed.hostname,parsed.port,timeout=3)
            try:
                conn.request('GET',path);response=conn.getresponse();return response.status,response.read()
            finally:conn.close()
        assert get(parsed.path)==(200,b'audio')
        assert get('/?url='+url)[0]==404
        guard.configure(1,'')
        assert get(parsed.path)[0]==404
        assert seen==['/audio']
    finally:guard.close()
