"""Cue playback proof using an isolated Liquidsoap process and generated audio."""
import os
import subprocess
import time
import uuid

import pytest

from app.extensions import db
from app.models import Station, Track, AdminUser, BoothCue, CuePlayback, SelectionDecision
from app.services.station_runtime import render_liquidsoap
from app.services.live_assist import request_deck, status
from app.services.booth_cue import mutate, advance
from app.services.playout_queue import mixer_state
from app.automation_worker import EventReader, process_manual, observe_queue
from tests.test_web import app

pytestmark = pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit isolated Liquidsoap integration')


def test_cue_cycles_from_manual_song_and_rotates_actual_end(app, tmp_path, monkeypatch):
    media = tmp_path/'media'; runtime = tmp_path/'runtime'; directory = runtime/'test-station'; directory.mkdir(parents=True)
    originals = media/'test-station'/'originals'; originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(media))
    monkeypatch.setenv('FREO_LIVE_MIC', '0')
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT', runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT', runtime)
    for key, frequency in [('a', 440), ('b', 880)]:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={frequency}:duration=6', '-y', str(originals/(key*32+'.mp3'))], check=True)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.automation.operator_mode = 'DJ_BOOTH'; station.automation.hold = True
        first = Track.query.first(); first.storage_key = 'a'*32+'.mp3'; first.duration_ms = 6000
        second = Track(station_id=station.id, uuid=str(uuid.uuid4()), title='Second cue song', artist='Test', original_filename='b.mp3', storage_key='b'*32+'.mp3', media_type='mp3', duration_ms=6000, sample_rate_hz=44100, channels=1, file_size_bytes=1000, checksum_sha256='b'*64, enabled=True, ingest_status='accepted')
        db.session.add(second); db.session.commit(); user = AdminUser.query.first()
        def edit(**data):
            cue = db.session.get(BoothCue, station.id)
            return mutate(station, user, dict(revision=str(cue.revision if cue else 0), nonce=str(uuid.uuid4()), **data))
        edit(operation='add', identifier=first.uuid)
        edit(operation='add', identifier=second.uuid)
        cue = db.session.get(BoothCue, station.id)
        initial = [entry['id'] for entry in cue.entries]
        source = render_liquidsoap(station, 'a'*64).replace('/run/freo/playout/test-station', str(directory))
        source = 'settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav, "{tmp_path}/audio.wav", radio)\n'
        config = tmp_path/'engine.liq'; config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            proc = subprocess.Popen(['liquidsoap', str(config)], stdout=log, stderr=log)
            try:
                deadline = time.monotonic()+90
                while not (directory/'control.sock').exists():
                    if proc.poll() is not None or time.monotonic() > deadline:
                        pytest.fail((tmp_path/'engine.log').read_text()[-3000:])
                    time.sleep(.1)
                reader = EventReader()
                def cycle():
                    process_manual(station, reader)
                    advance(station, mixer_state(station.slug), reader)
                    observe_queue(station)
                    return status(station)
                cycle()
                # A search-loaded song starts the chain, without an entry binding.
                request_deck(station, user, 'A', 'LOAD', first.uuid, '', str(uuid.uuid4()), fade_seconds=0, play_on_load=True)
                cycle()
                edit(operation='auto', enabled='true')
                started = []
                deadline = time.monotonic()+50
                while time.monotonic() < deadline:
                    observed = cycle()
                    current = observed['current']
                    if current and (not started or started[-1] != current['decision_id']):
                        started.append(current['decision_id'])
                    if len(started) >= 4:
                        break
                    time.sleep(.12)
                assert len(started) >= 4, (started, cue.message, (directory/'events.log').read_text(), (tmp_path/'engine.log').read_text()[-2000:])
                assert [db.session.get(SelectionDecision, key).track_id for key in started[:4]] == [first.id, first.id, second.id, first.id]
                assert [entry['id'] for entry in cue.entries] == initial
                assert CuePlayback.query.filter(CuePlayback.completed_at.isnot(None)).count() >= 3
                # Pause must freeze the song and disarm without rotating it.
                current = observed['mixer']['a']
                request_deck(station, user, 'A', 'PAUSE', '', str(current['decision_id']), str(uuid.uuid4()))
                cycle(); before = list(cue.entries); time.sleep(.5); cycle()
                assert cue.entries == before and not cue.auto_enabled
                # Replaying all log lines is harmless.
                revision = cue.revision
                EventReader().collect(station.slug)
                assert cue.revision == revision
            finally:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        # Inspect actual output, not just UI/engine identity: both tones aired.
        import array
        import math
        import wave
        with wave.open(str(tmp_path/'audio.wav')) as wav:
            samples = array.array('h', wav.readframes(wav.getnframes()))
            rate, channels = wav.getframerate(), wav.getnchannels()
        mono = samples[::channels]
        heard = set()
        for start in range(0, len(mono)-rate//5, rate//5):
            chunk = mono[start:start+rate//5]
            for hz in (440, 880):
                real = sum(value*math.cos(2*math.pi*hz*i/rate) for i, value in enumerate(chunk)) / len(chunk)
                imaginary = sum(value*math.sin(2*math.pi*hz*i/rate) for i, value in enumerate(chunk)) / len(chunk)
                if math.hypot(real, imaginary) > 100:
                    heard.add(hz)
        assert heard == {440, 880}
