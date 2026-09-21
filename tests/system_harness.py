"""Private web/worker/Liquidsoap/Icecast stack for opt-in system tests.

Only OS service management and installation paths are adapted. Playback decisions,
commands, engine events, broadcast observations and HTTP responses are real.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from urllib.request import ProxyHandler, build_opener

import pytest
from flask import Response
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server

from app import create_app
from app.extensions import db
from app.models import (AdminUser, AutomationState, LiveCartSlot, Playlist,
                        PlaylistItem, Station, StreamMount, Track)
from app.services import visual_schedule as vs


def wait_for(check, timeout=20, description='condition'):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError(f'Timed out waiting for {description}')


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class SystemStack:
    slug = 'test-station'

    def __init__(self, monkeypatch, evidence):
        self.evidence = evidence
        # A short socket path is necessary for AF_UNIX. Icecast drops privileges.
        self.root = Path(tempfile.mkdtemp(prefix='freo-system-', dir='/tmp'))
        self.root.chmod(0o755)
        self.runtime = self.root / 'runtime'
        (self.runtime / self.slug).mkdir(parents=True)
        self.media = self.root / 'media'
        self.logs = []
        self.engine = self.icecast = self.worker = self.server = None
        self.worker_stop = threading.Event()
        self.errors = []
        self.opener = build_opener(ProxyHandler({}))
        self.tick_count = 0
        for key, value in {
            'FREO_ENV_FILE': '/dev/null', 'DATABASE_URL': f'sqlite:///{self.root}/system.sqlite',
            'SECRET_KEY': 'isolated-system-test', 'FREO_MEDIA_ROOT': str(self.media),
            'FREO_LIVE_MIC': '0', 'FREO_API_STATE_DIR': str(self.root / 'api'),
            'FREO_STATS_STATE_DIR': str(self.root / 'stats'),
        }.items():
            monkeypatch.setenv(key, value)
        self.app = create_app('testing')
        self.app.config['FREO_UPLOAD_ROOT'] = str(self.root / 'uploads')
        from app import automation_worker as worker
        from app.services import playout_queue, station_runtime, broadcast_status
        monkeypatch.setattr(playout_queue, 'SOCKET_ROOT', self.runtime)
        monkeypatch.setattr(worker, 'EVENT_ROOT', self.runtime)
        monkeypatch.setattr(station_runtime, 'ROOT', self.root / 'etc')
        monkeypatch.setattr(station_runtime, 'require_root', lambda: None)
        monkeypatch.setattr(station_runtime, 'service_action', self.service_action)
        monkeypatch.setattr(station_runtime, 'wait_audio_online', lambda station: wait_for(
            self.online, timeout=120, description='private Icecast mount'))
        # Preserve production parsing/caching; redirect its sole HTTP destination.
        stack = self
        class LocalIcecast:
            def open(self, url, **kwargs):
                assert url == 'http://127.0.0.1:8001/status-json.xsl'
                return stack.opener.open(stack.icecast_url + '/status-json.xsl', **kwargs)
        monkeypatch.setattr(broadcast_status, '_opener', LocalIcecast())
        monkeypatch.setattr(broadcast_status, '_checked', 0.0)
        monkeypatch.setattr(broadcast_status, '_sources', None)
        with self.app.app_context():
            db.create_all()
            db.session.execute(db.text('PRAGMA journal_mode=WAL'))
            db.session.commit()
            self.seed()
        self.app.add_url_rule('/stream/test-station', 'system_test_stream', self.stream)

    def seed(self):
        station = Station(name='System Test Station', slug=self.slug,
                          desired_state='running', timezone='UTC', broadcast_status='ready')
        station.stream = StreamMount()
        station.automation = AutomationState(enabled=True, operator_mode='AUTO', hold=False)
        second = Station(name='Untouched Station', slug='second-station', desired_state='stopped')
        second.stream = StreamMount()
        db.session.add_all([station, second, AdminUser(email='admin@example.test',
            password_hash=generate_password_hash('test-password-long-enough'))])
        db.session.flush()
        originals = self.media / self.slug / 'originals'
        originals.mkdir(parents=True)
        self.tracks = []
        # Include a normal-length item for deck timers; automation uses short clips.
        for index, (extension, duration, frequency) in enumerate([
            ('mp3', 8, 440), ('flac', 11, 660), ('wav', 180, 880), ('wav', 3, 1100),
        ], 1):
            key = f'{index:032x}.{extension}'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                f'sine=frequency={frequency}:duration={duration}', '-y', str(originals / key)],
                check=True, timeout=30)
            track = Track(station_id=station.id, uuid=f'00000000-0000-4000-8000-{index:012d}',
                title=f'System Tone {frequency}', artist='Generated fixture', original_filename=key,
                storage_key=key, media_type=extension, duration_ms=duration*1000,
                sample_rate_hz=44100, channels=1, file_size_bytes=(originals/key).stat().st_size,
                checksum_sha256=f'{index:064x}', enabled=True, ingest_status='accepted')
            db.session.add(track)
            self.tracks.append(track)
        db.session.flush()
        playlist = Playlist(station_id=station.id, name='System rotation', mode='STRAIGHT')
        playlist.items = [PlaylistItem(track=track, position=index)
                          for index, track in enumerate(self.tracks[:2], 1)]
        db.session.add(playlist)
        db.session.flush()
        policy = vs.policy(station, True)
        ref = vs.source(station, dict(kind='playlist', id=playlist.id))
        block = vs.save_composition(station, dict(kind='BLOCK', name='System block', sections=[
            dict(id='all', start=0, end=86400, source=ref)]))
        db.session.flush()
        rule = dict(frequency='daily', anchor=datetime.now(timezone.utc).date().isoformat())
        block_ref = vs.source(station, dict(kind='block', id=block.id), allow_block=True)
        policy.calendar = vs.clean_document(station, [dict(id='all', start=0, end=86400,
            source=block_ref, rule=rule)])
        policy.assignments = vs.clean_document(station, [dict(id='all', pattern=[block_ref], rule=rule)], assignments=True)
        policy.simple = policy.live_simple = ref
        policy.default_playlist_id = playlist.id
        policy.mode = 'SIMPLE'
        policy.activated = policy.calendar_saved = True
        db.session.add(LiveCartSlot(station_id=station.id, role='HOT', position=1,
            track_id=self.tracks[3].id, label='System cart', playback_mode='OVER'))
        db.session.commit()
        self.track_ids = [track.id for track in self.tracks]
        self.track_uuids = [track.uuid for track in self.tracks]

    def spawn(self, args, name):
        log = (self.root / name).open('a')
        self.logs.append(log)
        return subprocess.Popen(args, stdout=log, stderr=log)

    def start(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.icecast_url = f'http://127.0.0.1:{port}'
        logdir = self.root / 'icecast-logs'
        logdir.mkdir(mode=0o777)
        logdir.chmod(0o777)
        security = '<changeowner><user>nobody</user><group>nogroup</group></changeowner>' if os.geteuid() == 0 else ''
        config = self.root / 'icecast.xml'
        config.write_text(f'''<icecast><location>Isolated test</location><admin>test@localhost</admin>
<limits><clients>20</clients><sources>2</sources><burst-size>0</burst-size></limits>
<authentication><source-password>system-test-only</source-password><relay-password>system-test-only</relay-password>
<admin-user>admin</admin-user><admin-password>system-test-only</admin-password></authentication>
<hostname>127.0.0.1</hostname><listen-socket><port>{port}</port><bind-address>127.0.0.1</bind-address></listen-socket>
<fileserve>1</fileserve><paths><logdir>{logdir}</logdir><webroot>/usr/share/icecast2/web</webroot>
<adminroot>/usr/share/icecast2/admin</adminroot></paths><logging><accesslog>access.log</accesslog>
<errorlog>error.log</errorlog><loglevel>2</loglevel><logsize>1024</logsize><logarchive>0</logarchive></logging>
<security><chroot>0</chroot>{security}</security></icecast>''')
        self.icecast = self.spawn(['icecast2', '-c', str(config)], 'icecast.log')
        wait_for(self.icecast_ready, timeout=15, description='private Icecast startup')
        self.service_action(self.slug, 'start')
        wait_for(self.online, timeout=120, description='real stream startup')
        self.start_worker()
        self.server = make_server('127.0.0.1', 0, self.app, threaded=True)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        (self.evidence / 'stack.json').write_text(json.dumps(dict(root=str(self.root), base=self.base,
            icecast=self.icecast_url, database='disposable SQLite WAL', worker='real tick in restartable thread'), indent=2))

    def icecast_ready(self):
        assert self.icecast.poll() is None, (self.root/'icecast.log').read_text()
        try:
            with self.opener.open(self.icecast_url + '/status-json.xsl', timeout=1) as response:
                return response.status == 200
        except OSError:
            return False

    def online(self):
        try:
            with self.opener.open(self.icecast_url + '/status-json.xsl', timeout=1) as response:
                rows = json.load(response)['icestats'].get('source', [])
            if isinstance(rows, dict):
                rows = [rows]
            return any(row.get('listenurl', '').endswith('/' + self.slug) for row in rows)
        except (OSError, ValueError):
            return False

    def service_action(self, slug, action):
        assert slug == self.slug, 'System test attempted to control another station'
        if action == 'status':
            return self.engine is not None and self.engine.poll() is None
        if action in ('stop', 'restart'):
            stop_process(self.engine)
            self.engine = None
        if action in ('start', 'restart') and self.engine is None:
            from app.services.station_runtime import render_liquidsoap
            with self.app.app_context():
                station = Station.query.filter_by(slug=slug).one()
                source = render_liquidsoap(station, 'system-test-only')
            source = source.replace('/run/freo/playout', str(self.runtime)).replace(
                '/var/lib/freo/playlists', str(self.root/'playlists')).replace(
                'port=8001,', f'port={self.icecast_url.rsplit(":", 1)[1]},')
            assert '/run/freo/' not in source and '/var/lib/freo/' not in source
            config = self.root / 'engine.liq'
            config.write_text('settings.init.allow_root := true\n' + source)
            # Remove only our stopped engine's socket so readiness cannot be stale.
            (self.runtime/slug/'control.sock').unlink(missing_ok=True)
            self.engine = self.spawn(['liquidsoap', str(config)], 'engine.log')
        return True

    def start_worker(self):
        from app.automation_worker import EventReader, tick, worker_delay
        from app.models import TimedEventOccurrence
        from app.services.master_broadcast import process_pending_broadcasts
        from app.services.statistics.icecast import Icecast
        from app.services.statistics.collect import tick as collect_statistics
        from urllib.request import Request
        credentials = self.root/'icecast-credentials.json'
        credentials.write_text(json.dumps(dict(admin='system-test-only')))
        statistics = Icecast(credentials)
        stack = self
        class LocalStats:
            def open(self, request, **kwargs):
                assert request.full_url.startswith('http://127.0.0.1:8001/admin/')
                return stack.opener.open(Request(request.full_url.replace(
                    'http://127.0.0.1:8001', stack.icecast_url), headers=dict(request.header_items())), **kwargs)
        statistics.opener = LocalStats()
        self.worker_stop.clear()
        def run():
            reader = EventReader()
            last_stats = 0
            while not self.worker_stop.is_set():
                try:
                    with self.app.app_context():
                        process_pending_broadcasts()
                        tick(reader)
                        if time.monotonic()-last_stats >= 5:
                            collect_statistics(statistics.observe(Station.query.all()), int(time.time()))
                            last_stats = time.monotonic()
                        delay = worker_delay(reader)
                    self.tick_count += 1
                except Exception:
                    self.errors.append(traceback.format_exc())
                    return
                self.worker_stop.wait(delay)
        self.worker = threading.Thread(target=run, daemon=True, name='isolated-automation')
        self.worker.start()

    def stop_worker(self):
        self.worker_stop.set()
        if self.worker:
            self.worker.join(timeout=135)
            assert not self.worker.is_alive(), 'Isolated worker did not stop'

    def stream(self):
        upstream = self.opener.open(self.icecast_url + '/' + self.slug, timeout=5)
        def chunks():
            try:
                while chunk := upstream.read(4096):
                    yield chunk
            finally:
                upstream.close()
        return Response(chunks(), mimetype='audio/mpeg')

    def query(self, function):
        assert not self.errors, '\n'.join(self.errors)
        with self.app.app_context():
            return function()

    def capture(self, seconds=3, name='stream.wav'):
        path = self.evidence / name
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', self.icecast_url+'/'+self.slug,
            '-t', str(seconds), '-ac', '1', '-ar', '8000', str(path)], check=True, timeout=seconds+20)
        return path

    def close(self):
        try:
            self.stop_worker()
        finally:
            stop_process(self.engine)
            stop_process(self.icecast)
            if self.server:
                self.server.shutdown()
                self.server_thread.join(timeout=5)
            for log in self.logs:
                log.close()
            # SQLite may still have recent commits in WAL. A plain file copy
            # would silently omit them from the evidence database.
            import sqlite3
            with sqlite3.connect(str(self.root/'system.sqlite')) as source:
                with sqlite3.connect(str(self.evidence/'system.sqlite')) as destination:
                    source.backup(destination)
            for name in ('engine.log', 'icecast.log'):
                if (self.root/name).exists():
                    shutil.copy2(self.root/name, self.evidence/name)
            shutil.copytree(self.runtime, self.evidence/'runtime', dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('*.sock'))
            (self.evidence/'worker-errors.json').write_text(json.dumps(self.errors, indent=2))
            with self.app.app_context():
                db.session.remove()
                db.engine.dispose()
            shutil.rmtree(self.root)


@pytest.fixture
def system_stack(monkeypatch, tmp_path):
    if os.environ.get('FREO_SYSTEM_TEST') != '1':
        pytest.skip('Opt-in private full stack: FREO_SYSTEM_TEST=1')
    stack = SystemStack.__new__(SystemStack)
    try:
        stack.__init__(monkeypatch, tmp_path)
        stack.start()
        yield stack
        assert not stack.errors, '\n'.join(stack.errors)
    finally:
        if hasattr(stack, 'app'):
            stack.close()
        elif hasattr(stack, 'root'):
            shutil.rmtree(stack.root)
