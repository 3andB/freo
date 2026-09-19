"""Real Icecast, local mock YP, generated audio only; never publishes publicly."""
import os
import base64
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.request import ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

import pytest

from app.services import icecast_directory as yp
from tests.test_radio_directories import public_app, app, station

pytestmark = pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit isolated Icecast engine test')


@pytest.mark.parametrize('directory_outage', [False, True])
def test_yp_public_url_opt_in_disable_and_continuous_playback(public_app, monkeypatch, tmp_path, directory_outage):
    requests = []
    fail_touch = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
            requests.append(data)
            if fail_touch.is_set() and data.get('action') == ['touch']:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('YPResponse', '1')
            self.send_header('YPMessage', 'OK')
            self.send_header('SID', 'local-test-id')
            self.send_header('TouchFreq', '30')
            self.end_headers()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(yp, 'YP_URL', 'http://127.0.0.1:' + str(server.server_port))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    # Icecast refuses root; make only this temporary fixture accessible.
    folder = Path('/tmp') / ('freo-yp-engine-' + str(os.getpid()))
    folder.mkdir(mode=0o755)
    config_path = folder / 'icecast.xml'
    raw = f'''<icecast><hostname>localhost</hostname><location>Test</location><admin>test@example.org</admin>
      <limits><sources>4</sources><clients>20</clients></limits>
      <authentication><source-password>test-source</source-password><admin-user>admin</admin-user><admin-password>test-admin</admin-password></authentication>
      <listen-socket><port>{port}</port><bind-address>127.0.0.1</bind-address></listen-socket>
      <mount type="normal"><mount-name>/test-station</mount-name><public>0</public></mount>
      <mount type="normal"><mount-name>/second-station</mount-name><public>0</public></mount>
      <mount type="default"><public>0</public></mount><fileserve>0</fileserve>
      <paths><logdir>{folder}</logdir><webroot>/usr/share/icecast2/web</webroot><adminroot>/usr/share/icecast2/admin</adminroot></paths>
      <logging><accesslog>-</accesslog><errorlog>-</errorlog><loglevel>3</loglevel></logging>
    </icecast>'''.encode()
    config_path.write_bytes(raw)
    config_path.chmod(0o644)
    log = (folder / 'engine.log').open('w+')
    processes = []
    opener = build_opener(ProxyHandler({}))
    def wait_for(condition, seconds=15):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if condition(): return
            except OSError:
                pass
            time.sleep(.1)
        log.flush()
        pytest.fail('Isolated Icecast condition timed out; log: ' + (folder / 'engine.log').read_text()[-5000:])
    def listen(slug):
        return opener.open(f'http://127.0.0.1:{port}/{slug}', timeout=3)
    def private_mount():
        request = Request(f'http://127.0.0.1:{port}/admin/stats', headers={
            'Authorization': 'Basic ' + base64.b64encode(b'admin:test-admin').decode()})
        with opener.open(request, timeout=3) as response:
            return ET.fromstring(response.read()).findtext("source[@mount='/test-station']/public") == '0'
    try:
        kwargs = {'user': 'nobody', 'group': 'nogroup'} if os.geteuid() == 0 else {}
        icecast = subprocess.Popen(['icecast2', '-c', str(config_path)], stdout=log, stderr=log, **kwargs)
        processes.append(icecast)
        wait_for(lambda: socket.create_connection(('127.0.0.1', port), timeout=1).close() is None)
        for slug in ('test-station', 'second-station'):
            source = subprocess.Popen(['ffmpeg', '-v', 'error', '-re', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100',
                '-c:a', 'libmp3lame', '-b:a', '64k', '-content_type', 'audio/mpeg', '-ice_public', '1', '-f', 'mp3',
                f'icecast://source:test-source@127.0.0.1:{port}/{slug}'], stdout=log, stderr=log)
            processes.append(source)
        def ready():
            for slug in ('test-station', 'second-station'):
                with listen(slug) as stream:
                    assert len(stream.read(256)) == 256
            return True
        wait_for(ready)
        assert not requests
        with listen('test-station') as first, listen('second-station') as other:
            stop = threading.Event()
            totals, errors = [0, 0], []
            def consume(index, stream):
                try:
                    while not stop.is_set():
                        chunk = stream.read(4096)
                        if not chunk:
                            raise OSError('Listener disconnected')
                        totals[index] += len(chunk)
                except Exception as error:
                    errors.append(type(error).__name__)
            readers = [threading.Thread(target=consume, args=pair, daemon=True) for pair in enumerate((first, other))]
            for reader in readers: reader.start()
            def audio_continues():
                previous = totals[:]
                wait_for(lambda: all(a > b for a, b in zip(totals, previous)), seconds=5)
                assert not errors
            try:
                with public_app.app_context():
                    enabled = yp.directory_config(raw, station(), True)
                config_path.write_bytes(enabled)
                icecast.send_signal(signal.SIGHUP)
                # Icecast deliberately delays a newly public source's first add by 60s.
                wait_for(lambda: any(r.get('action') == ['add'] for r in requests), seconds=90)
                adds = [r for r in requests if r.get('action') == ['add']]
                assert {r['listenurl'][0] for r in adds} == {'https://radio.example.org:443/test-station'}
                assert all('test-source' not in str(r) and 'test-admin' not in str(r) for r in requests)
                audio_continues()
                if directory_outage:
                    fail_touch.set()
                    wait_for(lambda: any(r.get('action') == ['touch'] for r in requests), seconds=15)
                    audio_continues()
                with public_app.app_context():
                    disabled = yp.directory_config(enabled, station(), False)
                config_path.write_bytes(disabled)
                icecast.send_signal(signal.SIGHUP)
                if not directory_outage:
                    wait_for(lambda: any(r.get('action') == ['remove'] for r in requests), seconds=15)
                # A rejected touch causes Icecast to discard the SID; in that
                # case the directory expires it rather than receiving remove.
                wait_for(private_mount)
                audio_continues()
                assert all(p.poll() is None for p in processes)
            finally:
                stop.set()
                for reader in readers: reader.join(timeout=4)
    finally:
        for process in reversed(processes):
            process.terminate()
        for process in reversed(processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        log.close()
        import shutil
        shutil.rmtree(folder)
