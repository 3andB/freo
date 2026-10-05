"""Measure full managed Liquidsoap output through each file playback bus."""
import os
import subprocess
import time
from array import array
import math
import pytest
from app.extensions import db
from app import models as m
from app.services.station_runtime import render_liquidsoap
from app.services.playout_queue import _command, push_decision, deck_control, mixer_state
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.getenv('FREO_ENGINE_TEST')!='1',reason='Isolated Liquidsoap opt-in')


@pytest.mark.parametrize('bus',['AUTO','A','B','CART','EVENT','A_PAUSED'])
def test_trim_fades_gain_and_confirmed_start_on_each_bus(app,tmp_path,monkeypatch,bus):
    paused = bus == 'A_PAUSED'
    if paused: bus = 'A'
    runtime=tmp_path/'run';directory=runtime/'test-station';directory.mkdir(parents=True)
    media=tmp_path/'media';originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media));monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    path=originals/('a'*32+'.wav')
    # The omitted intro/outro have distinguishable frequencies.
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=1760:duration=1','-f','lavfi','-i','sine=frequency=880:duration=4','-f','lavfi','-i','sine=frequency=2640:duration=1','-filter_complex','[0:a][1:a][2:a]concat=n=3:v=0:a=1','-y',str(path)],check=True)
    with app.app_context():
        song=m.Track.query.first();station=song.station
        song.storage_key=path.name;song.media_type='wav';song.duration_ms=6000
        song.audio_edit_enabled=True;song.cue_in_ms=1000;song.cue_out_ms=5000;song.fade_in_ms=1000;song.fade_out_ms=1000;song.gain_trim_db=-6
        station.automation.operator_mode='DJ_BOOTH' if bus in ('A','B','EVENT') else 'AUTO'
        decision=m.SelectionDecision(station_id=station.id,track=song,status='selected',reason='deck_load' if bus in ('A','B') else 'phase2_test',playback_bus=bus if bus in ('B','CART') else 'A')
        db.session.add(decision);db.session.commit()
        script=render_liquidsoap(station,'isolated').replace('/run/freo/playout/test-station',str(directory))
        output=tmp_path/'output.wav'
        script='settings.init.allow_root := true\n'+script[:script.index('output.icecast(')]+f'output.file(%wav,"{output}",radio)\n'
        config=tmp_path/'engine.liq';config.write_text(script)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+60
                while not (directory/'control.sock').exists() and time.monotonic()<deadline:
                    if proc.poll() is not None:pytest.fail((tmp_path/'engine.log').read_text()[-4000:])
                    time.sleep(.1)
                assert (directory/'control.sock').exists()
                if bus=='EVENT':
                    uri=push_decision(decision,prepare_only=True)
                    _command(station.slug,'freo_event.load_many '+uri)
                    _command(station.slug,'freo_event.arm 1')
                else:push_decision(decision)
                if bus in ('A','B'):deck_control(station.slug,bus,'take',0)
                if paused:
                    deadline=time.monotonic()+5
                    while mixer_state(station.slug)['a_elapsed'] < .35:
                        assert time.monotonic()<deadline
                        time.sleep(.02)
                    deck_control(station.slug,'A','pause')
                    position=mixer_state(station.slug)['a_elapsed']
                    time.sleep(2)
                    assert abs(mixer_state(station.slug)['a_elapsed']-position)<.05
                    deck_control(station.slug,'A','take',0)
                deadline=time.monotonic()+9
                while time.monotonic()<deadline:time.sleep(.1)
                events=(directory/'events.log').read_text()
                assert any(line.startswith(str(decision.id)+' ') for line in events.splitlines()),events
                if bus!='CART':assert f'END {decision.id} ' in events
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-ac','1','-ar','8000','-f','f32le','-'])
        samples=array('f');samples.frombytes(raw);n=400
        def amplitudes(hz):
            return [2*math.hypot(sum(samples[o+i]*math.cos(2*math.pi*hz*i/8000) for i in range(n)),sum(samples[o+i]*math.sin(2*math.pi*hz*i/8000) for i in range(n)))/n for o in range(0,len(samples)-n,n)]
        levels=amplitudes(880);peak=max(levels)
        assert .05<peak<.075,peak # 0.125 source peak, attenuated 6 dB
        assert max(amplitudes(1760))<peak*.08
        assert max(amplitudes(2640))<peak*.08
        audible=[i for i,v in enumerate(levels) if v>peak*.1]
        assert 3.6<len(audible)*.05<4.15
        if paused:
            # Resumption continues the fade from consumed source time. A wall
            # clock envelope would jump to full gain after this two-second gap.
            gaps=[(a,b) for a,b in zip(audible,audible[1:]) if b-a>20]
            assert len(gaps)==1 and 1.8<(gaps[0][1]-gaps[0][0])*.05<2.3
            assert .2*peak<levels[gaps[0][1]+1]<.7*peak
            assert sum(.35*peak<v<.65*peak for v in levels)>=8
            return
        # Both one-second envelopes have a measurable half-amplitude region.
        assert sum(.35*peak<v<.65*peak for v in levels[:audible[0]+22])>=4
        assert sum(.35*peak<v<.65*peak for v in levels[audible[-1]-22:])>=4


def test_zero_envelope_is_sample_identical_to_existing_decode(tmp_path):
    from pathlib import Path
    source=tmp_path/'source.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:duration=1','-y',str(source)],check=True)
    template=Path('deploy/liquidsoap/station.liq.template').read_text()
    helper=template[template.index('def track_fades(s)'):template.index('music_a = source.on_end')]
    script='settings.init.allow_root := true\n'+helper+f'''
raw = request.once(request.create("{source}"))
edited = track_fades(request.once(request.create("{source}")))
output.file(%wav, "{tmp_path}/raw.wav", fallible=true, raw)
output.file(%wav, "{tmp_path}/neutral.wav", fallible=true, on_stop=fun () -> shutdown(), edited)
'''
    config=tmp_path/'neutral.liq';config.write_text(script)
    result=subprocess.run(['liquidsoap',str(config)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    def pcm(path):return subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','s16le','-'])
    assert pcm(tmp_path/'raw.wav')==pcm(tmp_path/'neutral.wav')


def test_fade_overrides_do_not_leak_into_next_unedited_track(tmp_path):
    from pathlib import Path
    import json
    source=tmp_path/'source.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880:duration=1','-y',str(source)],check=True)
    template=Path('deploy/liquidsoap/station.liq.template').read_text()
    helper=template[template.index('def track_fades(s)'):template.index('music_a = source.on_end')]
    uri=f'annotate:liq_cue_in="0.000",liq_cue_out="1.000",freo_fade_in="0.200",freo_fade_out="0.200":{source}'
    script='settings.init.allow_root := true\n'+helper+f'''
raw = request.queue(interactive=false, queue=[request.create("{source}"), request.create("{source}")])
edited = track_fades(request.queue(interactive=false, queue=[request.create({json.dumps(uri)}), request.create("{source}")]))
output.file(%wav, "{tmp_path}/raw.wav", fallible=true, raw)
output.file(%wav, "{tmp_path}/edited.wav", fallible=true, on_stop=fun () -> shutdown(), edited)
'''
    config=tmp_path/'sequence.liq';config.write_text(script)
    result=subprocess.run(['liquidsoap',str(config)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    def pcm(name):return subprocess.check_output(['ffmpeg','-v','error','-i',str(tmp_path/name),'-f','s16le','-'])
    raw,edited=pcm('raw.wav'),pcm('edited.wav')
    assert len(raw)==len(edited)==352800
    assert raw[:176400]!=edited[:176400]
    # Compare native PCM: resampling would mix the previous fade into the
    # first few samples of this track through the resampler filter history.
    assert raw[176400:]==edited[176400:]
