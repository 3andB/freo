"""Opt-in wall-clock endurance run of edited tracks through the managed engine.

FREO_PHASE2_SOAK_SECONDS=3600 runs for one hour with generated audio, a fixture
database, private sockets and bounded audio evidence. It never uses a live station.
"""
import json
import math
import os
from array import array
from pathlib import Path
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import Station, Track, SelectionDecision
from app.services.station_runtime import render_liquidsoap
from app.services import visual_schedule as vs
from app.services.schedule_switch import process_transition
from app.services.track_audio import decision_duration_ms
from app.services.playout_queue import mixer_state
from app.automation_worker import EventReader, refill_station
from tests.test_web import app, admin_client

SECONDS = int(os.environ.get('FREO_PHASE2_SOAK_SECONDS', '0'))
pytestmark = pytest.mark.skipif(SECONDS < 60, reason='Opt-in isolated Phase 2 soak')


def test_edited_track_endurance(app, tmp_path, monkeypatch):
    media = tmp_path/'media'
    runtime = tmp_path/'runtime'
    directory = runtime/'test-station'
    directory.mkdir(parents=True)
    originals = media/'test-station'/'originals'
    originals.mkdir(parents=True)
    key = 'd'*32+'.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=1760:duration=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:duration=4',
                    '-f', 'lavfi', '-i', 'sine=frequency=2640:duration=1',
                    '-filter_complex', '[0:a][1:a][2:a]concat=n=3:v=0:a=1',
                    '-y', str(originals/key)], check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT', str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT', runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT', runtime)
    client = admin_client(app)
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        song = Track.query.first()
        song.storage_key = key
        song.media_type = 'wav'
        song.duration_ms = 6000
        song.audio_edit_enabled = True
        song.cue_in_ms, song.cue_out_ms = 1000, 5000
        song.fade_in_ms = song.fade_out_ms = 250
        song.gain_trim_db = -6
        p = vs.policy(station, True)
        ref = dict(kind='song', id=song.id)
        rule = dict(frequency='daily', anchor=datetime.now(timezone.utc).date().isoformat())
        block = vs.save_composition(station, dict(kind='BLOCK', name='Edited soak block',
            sections=[dict(id='all', start=0, end=86400, source=ref)]))
        db.session.flush()
        p.calendar = vs.clean_document(station, [dict(id='all', start=0, end=86400, source=ref, rule=rule)])
        p.assignments = vs.clean_document(station, [dict(id='all', pattern=[vs.source(station,
            dict(kind='block', id=block.id), allow_block=True)], rule=rule)], assignments=True)
        p.simple = p.live_simple = ref
        p.activated = p.calendar_saved = True
        db.session.commit()
        source = render_liquidsoap(station, 'isolated-phase2-soak').replace('/run/freo/playout/test-station', str(directory))
        pipe = tmp_path/'audio.wav'
        os.mkfifo(pipe)
        source = 'settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav, {json.dumps(str(pipe))}, radio)\n'
        config = tmp_path/'engine.liq'
        config.write_text(source)
        metrics = dict(requested_seconds=SECONDS, elapsed_seconds=0, samples=0, edits=0,
            confirmed_starts=0, transitions=[], max_transition_seconds=0, max_fallback_seconds=0,
            max_clock_lag_seconds=0, clock_lag_limit_seconds=3,
            resources=[], edit_history=[], confirmed_policy_counts={}, completed=False)
        engine = probe = None
        with (tmp_path/'engine.log').open('w') as log, (tmp_path/'audio-probe.log').open('w') as audio_log:
            try:
                # Four rolling 30-second recordings bound disk use independently
                # of soak length. Continuous silence detection spans segments.
                probe = subprocess.Popen(['ffmpeg', '-nostdin', '-nostats', '-v', 'info', '-y',
                    '-i', str(pipe), '-af', 'silencedetect=noise=0.005:d=3', '-ac', '1', '-ar', '8000',
                    '-f', 'segment', '-segment_format_options', 'flush_packets=1',
                    '-segment_time', '30', '-segment_wrap', '4', str(tmp_path/'audio-%d.wav')],
                    stdout=subprocess.DEVNULL, stderr=audio_log)
                engine = subprocess.Popen(['liquidsoap', str(config)], stdout=log, stderr=log)
                deadline = time.monotonic()+120
                while not (directory/'control.sock').exists():
                    assert engine.poll() is None, (tmp_path/'engine.log').read_text()[-3000:]
                    assert time.monotonic() < deadline, 'Engine startup timed out'
                    time.sleep(.1)
                reader = EventReader()
                began = time.monotonic()
                last_program = began
                metrics['started_utc'] = datetime.now(timezone.utc).isoformat()
                next_switch = began
                next_edit = began+20
                next_sample = began+10
                command = None
                modes = ['SIMPLE', 'BLOCKS', 'CALENDAR', 'BLOCKS', 'SIMPLE', 'CALENDAR']
                index = 0
                frozen = {}
                while time.monotonic()-began < SECONDS:
                    now = time.monotonic()
                    assert engine.poll() is None and probe.poll() is None, 'Engine/decoder exited'
                    reader.collect(station.slug)
                    if command is None and now >= next_switch:
                        before = p.mode
                        mode = modes[index % len(modes)]
                        index += 1
                        command = vs.transition_request(station, dict(id=str(uuid.uuid4()), mode=mode,
                            current=p.mode, revision=p.revision, simple=ref))
                        db.session.commit()
                        switch_at = now
                    if command is not None:
                        process_transition(station, reader)
                        assert command.state != 'FAILED', command.error
                        assert now-switch_at < 10, 'Schedule handoff exceeded ten seconds'
                        if command.state == 'APPLIED':
                            assert command.decision.status == 'started'
                            metrics['transitions'].append([before, p.mode])
                            metrics['max_transition_seconds'] = max(metrics['max_transition_seconds'], now-switch_at)
                            command = None
                            next_switch = switch_at+10
                    else:
                        refill_station(station.slug, reader)
                    if not mixer_state(station.slug)['tone']:
                        last_program = now
                    metrics['max_fallback_seconds'] = max(metrics['max_fallback_seconds'], now-last_program)
                    assert now-last_program < 5, 'Sustained fallback instead of edited programme'
                    if now >= next_edit:
                        variant = metrics['edits'] % 2
                        response = client.post(f'/admin/api/stations/{station.slug}/song/{song.uuid}/audio',
                            data={'csrf': 'test-admin-csrf-token', 'data': json.dumps(dict(
                                revision=song.audio_edit_revision, cue_in_ms=1500 if variant == 0 else 1000,
                                cue_out_ms=4500 if variant == 0 else 5000,
                                fade_in_ms=500 if variant == 0 else 250,
                                fade_out_ms=500 if variant == 0 else 250,
                                gain_trim_db=-9 if variant == 0 else -6))})
                        assert response.status_code == 200, response.json
                        metrics['edit_history'].append(dict(at=round(now-began,2),
                            effective=response.json['audio']['effective']))
                        db.session.expire_all()
                        metrics['edits'] += 1
                        next_edit = now+20
                    if now >= next_sample:
                        # Durable queued/started snapshots must remain unchanged
                        # through editor saves and confirmed scheduling changes.
                        decisions = SelectionDecision.query.filter_by(station_id=station.id).all()
                        for decision in decisions:
                            saved = decision.audio_snapshot
                            if saved:
                                encoded = json.dumps(saved, sort_keys=True)
                                assert frozen.setdefault(decision.id, encoded) == encoded
                                assert decision_duration_ms(decision) in (3000, 4000)
                                assert saved['gain_db'] in (-6, -9)
                        metrics['confirmed_starts'] = sum(d.status == 'started' and bool(d.audio_snapshot) for d in decisions)
                        from collections import Counter
                        metrics['confirmed_policy_counts'] = dict(Counter(
                            f"{d.audio_snapshot['duration_ms']}ms/{d.audio_snapshot['gain_db']}dB"
                            for d in decisions if d.status == 'started' and d.audio_snapshot))
                        metrics['recent_started'] = [dict(id=d.id, started_at=d.started_at.isoformat(),
                            audio=d.audio_snapshot) for d in decisions if d.status == 'started' and d.audio_snapshot][-60:]
                        assert 'silence_start:' not in (tmp_path/'audio-probe.log').read_text(), 'Three seconds of decoded silence'
                        lag = [float(v) for v in re.findall(r'We must catchup ([\d.]+) seconds',
                                                          (tmp_path/'engine.log').read_text())]
                        metrics['max_clock_lag_seconds'] = max(lag, default=0)
                        assert metrics['max_clock_lag_seconds'] < metrics['clock_lag_limit_seconds'], 'Engine fell behind wall-clock playback'
                        clips = list(tmp_path.glob('audio-*.wav'))
                        assert clips and time.time()-max(c.stat().st_mtime for c in clips) < 10, 'Decoded audio stalled'
                        resources = dict(elapsed_seconds=round(now-began, 2))
                        for name, pid in [('engine', engine.pid), ('decoder', probe.pid), ('test_worker', os.getpid())]:
                            status = Path(f'/proc/{pid}/status').read_text()
                            resources[name+'_rss_kib'] = int(re.search(r'VmRSS:\s+(\d+)', status)[1])
                        metrics['resources'].append(resources)
                        next_sample = now+10
                    metrics['samples'] += 1
                    metrics['elapsed_seconds'] = round(time.monotonic()-began, 2)
                    (tmp_path/'soak-result.json').write_text(json.dumps(metrics, indent=2))
                    time.sleep(.25)
                metrics['elapsed_seconds'] = time.monotonic()-began
                metrics['finished_utc'] = datetime.now(timezone.utc).isoformat()
                assert metrics['elapsed_seconds'] >= SECONDS
                assert metrics['confirmed_starts'] >= SECONDS/10
                assert metrics['edits'] >= max(2, SECONDS//21-1)  # Allow polling/API time between saves.
                if SECONDS >= 70:
                    assert {tuple(pair) for pair in metrics['transitions']} == {(a, b) for a in vs.MODES for b in vs.MODES if a != b}
            finally:
                if engine is not None:
                    engine.terminate()
                    try:
                        engine.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        engine.kill()
                        engine.wait()
                if probe is not None:
                    try:
                        probe.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        probe.kill()
                        probe.wait()
                (tmp_path/'soak-result.json').write_text(json.dumps(metrics, indent=2))
        assert probe.returncode == 0, (tmp_path/'audio-probe.log').read_text()
        metrics = validate_soak_evidence(tmp_path, SECONDS)
        (tmp_path/'soak-result.json').write_text(json.dumps(metrics, indent=2))


def validate_soak_evidence(tmp_path, seconds):
    """Check a completed recording independently, preserving the raw run evidence.

    This also permits rechecking a full run after a test-only acceptance-criteria
    correction, without inventing playback or discarding the original test result.
    """
    tmp_path = Path(tmp_path)
    metrics = json.loads((tmp_path/'soak-result.json').read_text())
    assert metrics['requested_seconds'] == seconds
    assert metrics['elapsed_seconds'] >= seconds
    elapsed_utc = (datetime.fromisoformat(metrics['finished_utc']) -
                   datetime.fromisoformat(metrics['started_utc'])).total_seconds()
    assert elapsed_utc >= seconds
    assert metrics['confirmed_starts'] >= seconds/10
    # Scheduling every twenty seconds includes polling and API work. Allow one
    # second per interval rather than requiring zero accumulated execution time.
    assert metrics['edits'] >= max(2, seconds//21-1)
    assert metrics['max_transition_seconds'] < 10
    assert metrics['max_fallback_seconds'] < 5
    if seconds >= 70:
        assert {tuple(pair) for pair in metrics['transitions']} == {(a,b) for a in vs.MODES for b in vs.MODES if a != b}
    events = (tmp_path/'runtime/test-station/events.log').read_text().splitlines()
    starts = {line.split()[0] for line in events if line.split() and line.split()[0].isdigit()}
    assert len(starts) >= metrics['confirmed_starts']
    evidence = (tmp_path/'audio-probe.log').read_text()
    assert 'audio:' in evidence and 'silence_start:' not in evidence
    decoded = [int(h)*3600+int(m)*60+float(s) for h,m,s in
               re.findall(r'time=(\d+):(\d+):(\d+\.\d+)', evidence)]
    assert decoded and max(decoded) >= seconds-3, 'Decoder did not measure the complete interval'
    lag = [float(v) for v in re.findall(r'We must catchup ([\d.]+) seconds',
                                      (tmp_path/'engine.log').read_text())]
    metrics['max_clock_lag_seconds'] = max(lag, default=0)
    assert metrics['max_clock_lag_seconds'] < 3
    # Inspect the bounded final recordings as audio, not just socket state:
    # selected body survives, omitted intro/outro do not, gain stays bounded.
    frequencies = (880, 1760, 2640)
    n = 400
    bases = {hz: ([math.cos(2*math.pi*hz*i/8000) for i in range(n)],
                  [math.sin(2*math.pi*hz*i/8000) for i in range(n)]) for hz in frequencies}
    peaks = {hz: 0 for hz in frequencies}
    intermediate = frames = 0
    # The recorder stores PCM16 mono: FFmpeg normalizes its stereo downmix.
    # Direct float-mono decoding in the short engine tests instead preserves
    # stereo energy (sqrt(2) higher). Calibrated against the same -6 dB output.
    expected_peak = .125/math.sqrt(2)*10**(-6/20)
    for clip in tmp_path.glob('audio-*.wav'):
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(clip), '-ac', '1',
                                       '-ar', '8000', '-f', 'f32le', '-'])
        samples = array('f')
        samples.frombytes(raw)
        for offset in range(0, len(samples)-n, n):
            frame = samples[offset:offset+n]
            for hz, (cosines, sines) in bases.items():
                level = 2*math.hypot(sum(v*c for v, c in zip(frame, cosines)),
                                     sum(v*s for v, s in zip(frame, sines)))/n
                peaks[hz] = max(peaks[hz], level)
                if hz == 880 and .35*expected_peak < level < .6*expected_peak:
                    intermediate += 1
            frames += 1
    assert .9*expected_peak < peaks[880] < 1.1*expected_peak, peaks
    assert peaks[1760] < expected_peak*.1 and peaks[2640] < expected_peak*.1, peaks
    assert intermediate > 20, 'No intermediate fade levels measured'
    metrics.update(audio_peak_by_hz=peaks, audio_frames_measured=frames,
                   intermediate_level_frames=intermediate)
    metrics['completed'] = True
    (tmp_path/'soak-validation.json').write_text(json.dumps(metrics, indent=2))
    return metrics
