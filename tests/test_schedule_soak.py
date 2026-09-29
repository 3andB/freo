"""Opt-in continuous isolated playout with all six directed mode changes.

FREO_SCHEDULE_SOAK_SECONDS=172800 runs the same checks for 48 hours. No live
station socket, database, stream, or media is used; decoded audio is measured
continuously and discarded, so long runs do not accumulate audio files.
"""
import json
import os
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
from app.services.playout_queue import program_decision_id
from app.automation_worker import EventReader, refill_station
from tests.test_web import app

SECONDS=int(os.environ.get('FREO_SCHEDULE_SOAK_SECONDS','0'))
SILENCE_FILTER='silencedetect=noise=0.01:d=3'
pytestmark=pytest.mark.skipif(SECONDS<60,reason='Opt-in isolated soak: FREO_SCHEDULE_SOAK_SECONDS >= 60')


@pytest.mark.parametrize('gap', [2.25, 3.2])
def test_soak_audio_probe_detects_actual_three_second_silence(gap):
    result=subprocess.run(['ffmpeg','-nostdin','-nostats','-v','info',
        '-f','lavfi','-i','sine=frequency=440:duration=0.5',
        '-f','lavfi','-i',f'anullsrc=r=44100:cl=mono:d={gap}',
        '-f','lavfi','-i','sine=frequency=440:duration=0.5',
        '-filter_complex','[0:a][1:a][2:a]concat=n=3:v=0:a=1,'+SILENCE_FILTER,
        '-f','null','-'],capture_output=True,text=True,check=True)
    assert ('silence_start:' in result.stderr)==(gap>=3),result.stderr
    assert 'audio:' in result.stderr


def test_continuous_scheduling_soak(app,tmp_path,monkeypatch):
    media=tmp_path/'media';runtime=tmp_path/'runtime';directory=runtime/'test-station';directory.mkdir(parents=True)
    originals=media/'test-station'/'originals';originals.mkdir(parents=True);key='c'*32+'.mp3'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=4','-y',str(originals/key)],check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media));monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime);monkeypatch.setattr('app.automation_worker.EVENT_ROOT',runtime)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();song=Track.query.first();song.storage_key=key;song.duration_ms=4000
        p=vs.policy(station,True);ref=dict(kind='song',id=song.id)
        anchor=datetime.now(timezone.utc).date().isoformat();rule=dict(frequency='daily',anchor=anchor)
        block=vs.save_composition(station,dict(kind='BLOCK',name='Soak block',sections=[dict(id='all',start=0,end=86400,source=ref)]));db.session.flush()
        p.calendar=vs.clean_document(station,[dict(id='all',start=0,end=86400,source=ref,rule=rule)])
        p.assignments=vs.clean_document(station,[dict(id='all',pattern=[vs.source(station,dict(kind='block',id=block.id),allow_block=True)],rule=rule)],assignments=True)
        p.simple=p.live_simple=ref;p.activated=True;p.calendar_saved=True;db.session.commit()
        source=render_liquidsoap(station,'isolated-soak').replace('/run/freo/playout/test-station',str(directory))
        audio_pipe=tmp_path/'audio.wav';os.mkfifo(audio_pipe)
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+'output.file(%wav, '+json.dumps(str(audio_pipe))+', radio)\n'
        config=tmp_path/'engine.liq';config.write_text(source)
        audio_evidence=tmp_path/'audio-probe.log'
        metrics=dict(seconds=SECONDS,switches=[],samples=0,started=0,max_switch_seconds=0,
            audio_evidence=audio_evidence.name,silence_limit_seconds=3)
        with (tmp_path/'engine.log').open('w') as log, audio_evidence.open('w') as audio_log:
            # Decode continuously: the time between two Python/socket samples
            # is not evidence that the intervening audio was silent.
            probe=subprocess.Popen(['ffmpeg','-nostdin','-nostats','-v','info',
                '-i',str(audio_pipe),'-af',SILENCE_FILTER,
                '-f','null','-'],stdout=subprocess.DEVNULL,stderr=audio_log)
            proc=None
            try:
                proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
                startup_deadline=time.monotonic()+120
                while not (directory/'control.sock').exists():
                    if proc.poll() is not None or time.monotonic()>=startup_deadline:
                        pytest.fail((tmp_path/'engine.log').read_text()[-3000:] or 'Isolated engine startup timed out')
                    time.sleep(.1)
                reader=EventReader();began=time.monotonic();next_switch=began;command=None;switch_at=None
                modes=['SIMPLE','BLOCKS','CALENDAR','BLOCKS','SIMPLE','CALENDAR'];index=0
                while time.monotonic()-began<SECONDS:
                    now=time.monotonic();reader.collect(station.slug)
                    assert proc.poll() is None,'Engine exited during soak'
                    assert probe.poll() is None,'Continuous audio decoder exited during soak'
                    if command is None and now>=next_switch:
                        before=p.mode;mode=modes[index%len(modes)];index+=1
                        command=vs.transition_request(station,dict(id=str(uuid.uuid4()),mode=mode,current=p.mode,revision=p.revision,simple=ref));db.session.commit();switch_at=now
                    if command is not None:
                        process_transition(station,reader)
                        assert command.state!='FAILED',command.error
                        assert now-switch_at<10,'Handoff exceeded 10 seconds'
                        if command.state=='APPLIED':
                            assert command.decision.status=='started'
                            current=program_decision_id(station.slug)
                            if current!=command.decision_id:
                                # A confirmed four-second target may finish before
                                # this later socket read, especially under clock lag.
                                # Require its real END callback, never infer completion.
                                events=(directory/'events.log').read_text().splitlines()
                                assert any(line.startswith(f'END {command.decision_id} ') for line in events), (command.decision_id,current)
                                metrics['completed_before_observation']=metrics.get('completed_before_observation',0)+1
                            assert vs.transition_request(station,dict(id=command.id)).id==command.id
                            metrics['switches'].append([before,p.mode]);metrics['max_switch_seconds']=max(metrics['max_switch_seconds'],now-switch_at)
                            command=None;next_switch=switch_at+10
                    else:
                        refill_station(station.slug,reader)
                        metrics['samples']+=1
                    assert 'silence_start:' not in audio_evidence.read_text(), 'Decoded programme contained at least three seconds of silence'
                    metrics['started']=SelectionDecision.query.filter_by(station_id=station.id,status='started').count()
                    (tmp_path/'soak-result.json').write_text(json.dumps(metrics,indent=2))
                    time.sleep(.25)
                assert {tuple(pair) for pair in metrics['switches']}=={(a,b) for a in vs.MODES for b in vs.MODES if a!=b}
                assert metrics['started']>=12
            finally:
                if proc is not None:
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                try:probe.wait(timeout=5)
                except subprocess.TimeoutExpired:probe.kill();probe.wait()
        evidence=audio_evidence.read_text()
        assert probe.returncode==0,evidence
        assert 'audio:' in evidence,'No decoded programme audio measured'
        assert 'silence_start:' not in evidence,'Decoded programme contained at least three seconds of silence'
