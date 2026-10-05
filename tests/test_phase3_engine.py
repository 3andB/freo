"""Real program recording, automatic closure, lease expiry and output failure."""
import os
import subprocess
import time
from array import array
import math
import pytest
from app.extensions import db
from app.models import Station, AdminUser, DJStationAssignment, SelectionDecision, Track
from app.services import live_sessions as shows
from app.services.station_runtime import render_liquidsoap
from app.services.playout_queue import _command, push_decision, deck_control
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.getenv('FREO_ENGINE_TEST')!='1',reason='Isolated Liquidsoap opt-in')


def wait_for(predicate, timeout=10):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.1)
    raise AssertionError('Engine observation timed out')


@pytest.mark.parametrize('ending',['auto','lease','file_error'])
def test_record_final_program_and_fail_independently(app,tmp_path,monkeypatch,ending):
    runtime=tmp_path/'run';directory=runtime/'test-station';directory.mkdir(parents=True)
    media=tmp_path/'media';originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    recordings=media/'test-station'/'recordings';recordings.mkdir()
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media));monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    path=originals/('a'*32+'.wav')
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:duration=40','-y',str(path)],check=True)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();song=Track.query.first()
        song.storage_key=path.name;song.media_type='wav';song.duration_ms=40000
        station.automation.operator_mode='DJ_BOOTH'
        user=AdminUser.query.first();user.role='DJ'
        db.session.add(DJStationAssignment(admin_user_id=user.id,station_id=station.id));db.session.commit()
        show=shows.claim(station,user,True);db.session.commit()
        output=tmp_path/'program.wav'
        script=render_liquidsoap(station,'isolated').replace('/run/freo/playout/test-station',str(directory))
        script='settings.init.allow_root := true\n'+script[:script.index('output.icecast(')]+f'output.file(%wav,"{output}",radio)\n'
        config=tmp_path/'engine.liq';config.write_text(script)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                wait_for(lambda: (directory/'control.sock').exists() or proc.poll() is not None,60)
                assert proc.poll() is None,(tmp_path/'engine.log').read_text()[-5000:]
                assert shows.engine_observation(station.slug)['source']=='AUTO'
                shows.sync(station)
                assert _command(station.slug,'freo_record.state').split('|')[1]=='ARMED',show.recording.error
                if ending=='file_error':
                    (recordings/show.recording.storage_key).mkdir()
                decision=SelectionDecision(station_id=station.id,track=song,status='selected',reason='deck_load',playback_bus='A')
                db.session.add(decision);db.session.commit();push_decision(decision);deck_control(station.slug,'A','take',0)
                wait_for(lambda: shows.engine_observation(station.slug)['source']=='DJ')
                wait_for(lambda: _command(station.slug,'freo_record.state').split('|')[1] in ('RECORDING','ERROR'))
                if ending=='auto':
                    for _ in range(5):
                        shows.sync(station);time.sleep(.5)
                    assert show.started_at and show.recording.status=='recording'
                    _command(station.slug,'freo_mixer.mode AUTO')
                    wait_for(lambda: shows.engine_observation(station.slug)['source']=='AUTO')
                    wait_for(lambda: _command(station.slug,'freo_record.state').split('|')[1]=='CLOSED')
                    shows.sync(station)
                    assert show.ended_at and show.recording.status=='complete',show.recording.error
                    assert show.recording.duration_ms>2000
                else:
                    state=wait_for(lambda: (value if (value:=_command(station.slug,'freo_record.state')).split('|')[1]=='ERROR' else None),20)
                    assert state.split('|')[4]
                    assert proc.poll() is None
                    before=output.stat().st_size;time.sleep(1);assert output.stat().st_size>before
                    assert shows.engine_observation(station.slug)['source']=='DJ'
                    shows.sync(station)
                    assert show.recording.status==('failed' if ending=='file_error' else 'partial'),show.recording.error
                assert proc.poll() is None
                # A fresh, non-recorded show must not reopen the old file.
                _command(station.slug,'freo_mixer.mode AUTO');time.sleep(3.5)
                if ending!='file_error':
                    size=(recordings/show.recording.storage_key).stat().st_size
                    _command(station.slug,'freo_mixer.mode DJ_BOOTH')
                    another=SelectionDecision(station_id=station.id,track=song,status='selected',reason='deck_load',playback_bus='A')
                    db.session.add(another);db.session.commit();push_decision(another);deck_control(station.slug,'A','take',0)
                    time.sleep(1)
                    assert (recordings/show.recording.storage_key).stat().st_size==size
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        if ending=='auto':
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(recordings/show.recording.storage_key),'-ac','1','-ar','8000','-f','f32le','-'])
            samples=array('f');samples.frombytes(raw)
            n=800;levels=[2*math.hypot(sum(samples[o+i]*math.cos(2*math.pi*880*i/8000) for i in range(n)),sum(samples[o+i]*math.sin(2*math.pi*880*i/8000) for i in range(n)))/n for o in range(0,len(samples)-n,n)]
            assert max(levels)>.05
            assert sum(level>.02 for level in levels)>20


def test_recording_contains_decks_webrtc_microphone_and_carts(app,tmp_path,monkeypatch):
    import asyncio
    from tests.test_live_mic import gateway_roundtrip
    from app.services import station_runtime
    monkeypatch.setenv('FREO_LIVE_MIC','1')
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    directory=tmp_path/'media'/'test-station'/'recordings';directory.mkdir(parents=True)
    original=station_runtime.render_liquidsoap
    key='c'*32
    def render(*args,**kwargs):
        script=original(*args,**kwargs)
        # The harness has no automation loop; arm with a bounded test lease.
        return script.replace('output.icecast(',f'record_key := "{key}"\nrecord_phase := "ARMED"\nrecord_lease := time()+120.0\noutput.icecast(',1)
    monkeypatch.setattr(station_runtime,'render_liquidsoap',render)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        asyncio.run(gateway_roundtrip(tmp_path,station))
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(directory/(key+'.mp3')),'-ac','1','-ar','8000','-f','f32le','-'])
    samples=array('f');samples.frombytes(raw);n=800
    for hz in (440,880,1320):
        levels=[2*math.hypot(sum(samples[o+i]*math.cos(2*math.pi*hz*i/8000) for i in range(n)),sum(samples[o+i]*math.sin(2*math.pi*hz*i/8000) for i in range(n)))/n for o in range(0,len(samples)-n,n)]
        assert max(levels)>.03,(hz,max(levels))
