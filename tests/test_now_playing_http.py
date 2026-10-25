"""Real verified HTTPS transport for the v1.3 optional reporting endpoint."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import importlib.util
import ssl
import subprocess
import threading
from uuid import uuid4

import pytest
from app.services.central_api.client import Client, APIError


@pytest.fixture
def endpoint(tmp_path, monkeypatch):
    cert, key = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
        '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
    state = dict(status=200, calls=[], code='station_not_synced')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            assert self.path == '/health'
            assert not self.headers.get('Authorization')
            self.reply(200, {'status': 'ok'}, {'X-Freo-Now-Playing-Revision': '2026-10-v1',
                                           'X-Freo-Contract-Revision': '2026-10-v1.1'})
        def do_POST(self):
            assert self.path == '/v1/now-playing'
            assert self.headers.get('Authorization') == 'Bearer freo_' + 'x' * 43
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['calls'].append(payload)
            if state['status'] != 200:
                self.reply(state['status'], {'error': {'code': state['code']}},
                           {'Retry-After': '25', 'Location': '/credential-redirect'})
                return
            source = os.environ.get('FREO_NOW_PLAYING_VALIDATION')
            if source:
                spec = importlib.util.spec_from_file_location('published_now_playing_validation', source)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.NowPlaying.model_validate_json(json.dumps(payload))
            rows = payload['stations']
            assert 1 <= len(rows) <= 100
            assert len({row['station_id'] for row in rows}) == len(rows)
            for row in rows:
                assert set(row) == {'station_id', 'on_air', 'title', 'artist', 'observed_at'}
                assert type(row['on_air']) is bool
                for field in ('title', 'artist'):
                    assert row[field] is None or isinstance(row[field], str) and len(row[field]) <= 500
            self.reply(200, dict(server_time=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                               stations_accepted=len(rows), stations_updated=len(rows), next_report_seconds=60))
        def reply(self, status, data, headers=None):
            raw = json.dumps(data).encode()
            self.send_response(status)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_context = ssl.create_default_context
    monkeypatch.setattr(ssl, 'create_default_context', lambda: real_context(cafile=str(cert)))
    yield 'https://localhost:' + str(server.server_port), state
    server.shutdown()
    server.server_close()
    thread.join()


def payload():
    return {'stations': [dict(station_id=str(uuid4()), on_air=True, title='Unicode 歌 😀', artist=None,
        observed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))]}


def test_verified_https_capability_and_bearer(endpoint):
    url, state = endpoint
    client = Client(url, 'freo_' + 'x' * 43)
    assert client.request('GET', '/health')['status'] == 'ok'
    assert client.now_playing_revision == '2026-10-v1'
    assert client.request('POST', '/v1/now-playing', payload())['stations_accepted'] == 1
    assert len(state['calls']) == 1


@pytest.mark.parametrize('status,code', [(409, 'directory_not_enabled'), (409, 'station_not_synced'),
                                        (429, 'http_429'), (503, 'http_503'), (302, 'http_302')])
def test_errors_retry_after_and_no_redirects(endpoint, status, code):
    url, state = endpoint
    state.update(status=status, code=code)
    with pytest.raises(APIError) as error:
        Client(url, 'freo_' + 'x' * 43).request('POST', '/v1/now-playing', payload())
    assert error.value.code == code and error.value.retry_after == 25
    assert len(state['calls']) == 1
