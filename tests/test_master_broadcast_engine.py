"""Real mixed-program fallback, source recovery and DJ pause audio proof."""
import json
import os
import subprocess
import time
import wave
import zlib

from array import array
from math import sqrt
import pytest
from app.extensions import db
from app.models import Station, Track, SelectionDecision
from app.services.station_runtime import render_liquidsoap
from app.services.playout_queue import push_decision, mixer_state, _command
from tests.test_web import app

pytestmark = pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit isolated Liquidsoap audio test')


@pytest.mark.parametrize('mode', ['AUTO', 'DJ_BOOTH'])
def test_tone_source_recovery_and_pause(app, tmp_path, monkeypatch, mode):
    monkeypatch.setenv('FREO_LIVE_MIC', '0')
    runtime = tmp_path / 'runtime'
    directory = runtime / 'test-station'
    directory.mkdir(parents=True)
    originals = tmp_path / 'media/test-station/originals'
    originals.mkdir(parents=True)
    song = originals / ('a'*32 + '.mp3')
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=997:duration=30', '-y', str(song)], check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(tmp_path/'media'))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT', runtime)
    output = tmp_path/'audio.wav'
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.automation.operator_mode = mode
        track = Track.query.first()
        track.storage_key = song.name
        track.duration_ms = 30000
        decision = SelectionDecision(station_id=station.id, track=track, status='selected', playback_bus='A', reason='deck_load' if mode == 'DJ_BOOTH' else 'test')
        db.session.add(decision)
        db.session.commit()
        source = render_liquidsoap(station, 'a'*64).replace('/run/freo/playout/test-station', str(directory))
        source = 'settings.init.allow_root := true\n' + source[:source.index('output.icecast(')]
        source += f'output.file(%wav, {json.dumps(str(output))}, radio)\n'
        config = tmp_path/'engine.liq'
        config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            proc = subprocess.Popen(['liquidsoap', str(config)], stdout=log, stderr=log)
            def wait_tone(expected):
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        pytest.fail((tmp_path/'engine.log').read_text()[-3000:])
                    try:
                        if mixer_state(station.slug)['tone'] is expected:
                            return
                    except (OSError, RuntimeError):
                        pass
                    time.sleep(.1)
                pytest.fail('Tone status did not become ' + str(expected))
            try:
                wait_tone(True)
                time.sleep(1.2)
                push_decision(decision)
                if mode == 'DJ_BOOTH':
                    _command(station.slug, 'freo_deck.take_a 0.000')
                wait_tone(False)
                time.sleep(1.2)
                _command(station.slug, 'freo_queue.flush_and_skip' if mode == 'AUTO' else 'freo_deck.pause_a')
                wait_tone(True)
                time.sleep(1.2)
                if mode == 'AUTO':
                    push_decision(decision)
                else:
                    _command(station.slug, 'freo_deck.take_a 0.000')
                wait_tone(False)
                time.sleep(1.2)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait()
        with wave.open(str(output)) as audio:
            rate = audio.getframerate()
            samples = array('h', audio.readframes(audio.getnframes()))[::audio.getnchannels()]
        frequencies = []
        for start in range(0, len(samples)-rate, rate//2):
            segment = samples[start:start+rate]
            if sqrt(sum(value*value for value in segment) / len(segment)) > 100:
                frequencies.append(sum(a < 0 <= b for a, b in zip(segment, segment[1:])))
        assert any(abs(frequency - 997) <= 2 for frequency in frequencies)  # Real program audio reached the output.
        assert any(abs(frequency - (300 + zlib.crc32(station.slug.encode()) % 300)) <= 2 for frequency in frequencies)  # Audible fallback.
