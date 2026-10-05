"""Private generated-audio proof of selection, request START and recovery."""
import os
import subprocess
import time
import pytest
from app import models as m
from app.extensions import db
from app.services.station_runtime import render_liquidsoap
from app.services.visual_schedule import policy
from app.services import listener_requests as r
from app.services.playout_queue import program_rms
from app.automation_worker import EventReader, refill_station, worker_delay
from tests.test_web import app
from tests.test_playlists import setup_playlist

pytestmark = pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit private Liquidsoap integration')


def test_request_normal_queue_confirmed_start_and_reader_restart(app, tmp_path, monkeypatch):
    runtime = tmp_path / 'run'; directory = runtime / 'test-station'; directory.mkdir(parents=True)
    media = tmp_path / 'media'; originals = media / 'test-station' / 'originals'; originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT', runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT', runtime)
    with app.app_context():
        station, playlist, tracks = setup_playlist()
        m.SelectionDecision.query.delete()
        playlist.items = [item for item in playlist.items if item.track_id in [t.id for t in tracks[:2]]]
        for i, track in enumerate(tracks):
            track.storage_key = str(i + 1) * 32 + '.mp3'; track.duration_ms = 3000
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={440+i*220}:duration=3', '-y', str(originals / track.storage_key)], check=True)
        schedule = policy(station, True); schedule.mode = 'SIMPLE'; schedule.activated = True
        schedule.simple = schedule.live_simple = dict(kind='playlist', id=playlist.id); schedule.activation = 'phase5-engine'
        station.request_settings = dict(r.DEFAULTS, enabled=True, delay_songs=1, restrict_programming=False)
        db.session.commit()
        req = r.submit(station, tracks[2].uuid, 'engine-listener', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'); db.session.commit()
        source = render_liquidsoap(station, 'isolated-test').replace('/run/freo/playout/test-station', str(directory))
        source = 'settings.init.allow_root := true\n' + source[:source.index('output.icecast(')] + f'output.file(%wav,"{tmp_path}/recording.wav",radio)\n'
        config = tmp_path / 'engine.liq'; config.write_text(source)
        with (tmp_path / 'engine.log').open('w') as log:
            process = subprocess.Popen(['liquidsoap', str(config)], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 90
                while not (directory / 'control.sock').exists() and time.monotonic() < deadline:
                    if process.poll() is not None: pytest.fail((tmp_path / 'engine.log').read_text()[-3000:])
                    time.sleep(.1)
                assert (directory / 'control.sock').exists()
                reader = EventReader(); heard = False; restarted = False
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    refill_station(station.slug, reader)
                    heard = heard or program_rms(station.slug) > .03
                    db.session.refresh(req)
                    if req.status == 'queued' and not restarted:
                        reader = EventReader(); restarted = True
                    if req.status == 'played': break
                    time.sleep(worker_delay(reader))
                assert req.status == 'played' and heard and restarted, (tmp_path / 'engine.log').read_text()[-3000:]
                bound = m.SelectionDecision.query.filter_by(listener_request_id=req.id).all()
                assert len(bound) == 1 and bound[0].status == 'started'
                assert m.SelectionDecision.query.filter(m.SelectionDecision.status == 'started', m.SelectionDecision.started_at < req.played_at).count() >= 1
                refill_station(station.slug, EventReader())
                assert m.SelectionDecision.query.filter_by(listener_request_id=req.id).count() == 1
                assert (tmp_path / 'recording.wav').stat().st_size > 44100
            finally:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
