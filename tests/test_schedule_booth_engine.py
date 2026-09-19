"""Full worker path through mixed-media Cue, Events, restart replay and scheduling."""
import os
import json
import math
import subprocess
import time
import uuid
import wave
from array import array
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import AdminUser, BoothCue, Playlist, PlaylistItem, SelectionDecision, Station, Track
from app.automation_worker import EventReader, tick
from app.services.booth_cue import mutate
from app.services.live_assist import request_deck
from app.services.playout_queue import program_decision_id
from app.services.station_runtime import render_liquidsoap
from app.services.timed_events import save_event
from app.services.visual_schedule import policy, transition_request
from tests.test_web import app

pytestmark = pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1',
    reason='Explicit isolated Liquidsoap integration')


@pytest.mark.parametrize('interrupt_dj', [False, True])
def test_worker_cue_event_restart_and_return_to_schedule(app, tmp_path, monkeypatch, interrupt_dj):
    runtime = tmp_path/'runtime'
    directory = runtime/'test-station'
    directory.mkdir(parents=True)
    media = tmp_path/'media'
    originals = media/'test-station'/'originals'
    originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(media))
    monkeypatch.setenv('FREO_LIVE_MIC', '0')
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT', runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT', runtime)
    monkeypatch.setattr('app.services.broadcast_status.observation', lambda slug: (True, 0))
    # Leave enough audio on the second Cue item for a deliberate interruption,
    # including the engine's two-second fade and worker/database round trips.
    for key, extension, duration, frequency in [('a', 'mp3', 5, 440), ('b', 'flac', 20, 660), ('c', 'wav', 2, 880)]:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            f'sine=frequency={frequency}:duration={duration}', '-y', str(originals/(key*32+'.'+extension))], check=True)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.automation.operator_mode = 'DJ_BOOTH'
        station.automation.hold = True
        first = Track.query.first()
        first.storage_key = 'a'*32+'.mp3'
        first.duration_ms = 5000
        def audio(key, extension, duration):
            track = Track(station_id=station.id, uuid=str(uuid.uuid4()), title='Test '+key,
                artist='Test', original_filename=key+'.'+extension, storage_key=key*32+'.'+extension,
                media_type=extension, duration_ms=duration, sample_rate_hz=44100, channels=1,
                file_size_bytes=1000, checksum_sha256=key*64, enabled=True, ingest_status='accepted')
            db.session.add(track)
            return track
        second = audio('b', 'flac', 20000)
        event_track = audio('c', 'wav', 2000)
        playlist = Playlist(station_id=station.id, name='Scheduled music')
        playlist.items.append(PlaylistItem(track=first, position=1))
        db.session.add(playlist)
        db.session.flush()
        schedule = policy(station, True)
        schedule.activated = True
        schedule.default_playlist_id = playlist.id
        db.session.commit()
        user = AdminUser.query.first()
        def edit(**data):
            cue = db.session.get(BoothCue, station.id)
            return mutate(station, user, dict(revision=str(cue.revision if cue else 0),
                nonce=str(uuid.uuid4()), **data))
        edit(operation='add', identifier=first.uuid)
        edit(operation='add', identifier=second.uuid)
        source = render_liquidsoap(station, 'isolated-test').replace('/run/freo/playout/test-station', str(directory))
        config = tmp_path/'engine.liq'
        recording = tmp_path/'program.wav'
        config.write_text('settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+
            'output.file(%wav, '+json.dumps(str(recording))+', radio)\n')
        with (tmp_path/'engine.log').open('w') as log:
            proc = subprocess.Popen(['liquidsoap', str(config)], stdout=log, stderr=log)
            try:
                deadline = time.monotonic()+90
                while not (directory/'control.sock').exists():
                    if proc.poll() is not None or time.monotonic()>deadline:
                        pytest.fail((tmp_path/'engine.log').read_text()[-3000:])
                    time.sleep(.1)
                reader = EventReader()
                tick(reader)
                command = request_deck(station, user, 'A', 'LOAD', first.uuid, '',
                    str(uuid.uuid4()), fade_seconds=0, play_on_load=True)
                deadline = time.monotonic()+8
                while command.target_decision.status != 'started' and time.monotonic()<deadline:
                    tick(reader)
                    time.sleep(.1)
                assert command.target_decision.status == 'started'
                edit(operation='auto', enabled='true')
                now = datetime.now(timezone.utc)
                event = save_event(station.slug, name='Cue boundary event', recurrence_type='ONE_TIME',
                    content_type='TRACK', content_identifier=event_track.uuid,
                    local_date=now.date().isoformat(), local_time=now.strftime('%H:%M:%S'),
                    late_tolerance_seconds=2, interrupt_dj=interrupt_dj)
                occurrence = event.occurrences[0]
                cue = db.session.get(BoothCue, station.id)
                replayed = False
                deadline = time.monotonic()+30
                while time.monotonic()<deadline:
                    tick(reader)
                    if not replayed and (occurrence.boundary_reserved or occurrence.state=='MISSED'):
                        reader = EventReader()
                        replayed = True
                    starts = SelectionDecision.query.filter_by(station_id=station.id,
                        selection_method='cue_auto', status='started').order_by(SelectionDecision.id).all()
                    if len(starts)>=2:
                        break
                    time.sleep(.12)
                assert replayed and len(starts)>=2
                assert [row.track_id for row in starts[:2]] == [first.id, second.id]
                assert cue.auto_enabled and station.automation.operator_mode=='DJ_BOOTH'
                if interrupt_dj:
                    assert occurrence.state=='COMPLETED'
                    assert occurrence.selection_decision.started_at >= command.target_decision.started_at
                    assert occurrence.selection_decision.started_at < starts[0].started_at
                else:
                    assert occurrence.state=='MISSED'
                    assert occurrence.selection_decision is None
                before = list(cue.entries)
                switch = transition_request(station, dict(id=str(uuid.uuid4()), mode='SIMPLE',
                    current=schedule.mode, revision=schedule.revision, simple=dict(kind='song', id=first.id)))
                db.session.commit()
                deadline = time.monotonic()+8
                while switch.state not in ('APPLIED', 'FAILED') and time.monotonic()<deadline:
                    tick(reader)
                    time.sleep(.1)
                assert switch.state=='APPLIED', switch.error
                tick(reader)
                assert station.automation.operator_mode=='AUTO' and not cue.auto_enabled
                assert cue.entries==before, 'Interrupted Cue must not rotate as a completed song'
                assert f'END {starts[1].id} ' not in (directory/'events.log').read_text()
                assert program_decision_id(station.slug)==switch.decision_id
                assert switch.decision.status=='started'
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        # Measure the recorded output; a slow worker polling cycle must not be
        # miscounted as silence between two RMS observations.
        with wave.open(str(recording), 'rb') as wav:
            assert wav.getsampwidth()==2
            rate, channels = wav.getframerate(), wav.getnchannels()
            data = array('h', wav.readframes(wav.getnframes()))
            if __import__('sys').byteorder!='little':
                data.byteswap()
        mono = data[::channels]
        size = rate//10
        levels = [math.sqrt(sum(v*v for v in mono[i:i+size])/size)/32768
                  for i in range(0, len(mono)-size, size)]
        audible = [i for i, level in enumerate(levels) if level>.001]
        assert audible, 'No audible output recorded'
        silence = longest = 0
        for level in levels[audible[0]:audible[-1]+1]:
            silence = silence+1 if level<=.001 else 0
            longest = max(longest, silence)
        (tmp_path/'audio-result.json').write_text(json.dumps(dict(max_silence_seconds=longest/10)))
        assert longest/10<3, 'Sustained silence in recorded mixed workflow'
