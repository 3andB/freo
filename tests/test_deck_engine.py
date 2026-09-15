"""Opt-in real Liquidsoap + worker integration, using temporary audio and SQLite."""
import os,subprocess,time,uuid
from pathlib import Path
from datetime import datetime,timezone
import pytest
from app.extensions import db
from app.models import Station,Track,AdminUser,SelectionDecision
from app.services.station_runtime import render_liquidsoap
from app.services.live_assist import request_deck,status
from app.automation_worker import process_manual,observe_queue,EventReader
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST')!='1',reason='Explicit isolated Liquidsoap integration')


def test_actual_worker_load_play_pause_repeat_clear_and_mode(app,tmp_path,monkeypatch):
    media=tmp_path/'media';runtime=tmp_path/'runtime';directory=runtime/'test-station';directory.mkdir(parents=True)
    originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    key='a'*32+'.mp3';audio=originals/key
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=4','-y',str(audio)],check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT',runtime)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();track=Track.query.first();track.storage_key=key;track.duration_ms=4000
        station.automation.operator_mode='DJ_BOOTH';station.automation.hold=True;db.session.commit();user=AdminUser.query.first()
        source=render_liquidsoap(station,'a'*64).replace('/run/freo/playout/test-station',str(directory))
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav, "{tmp_path}/audio.wav", radio)\n'
        config=tmp_path/'engine.liq';config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                for _ in range(300):
                    if (directory/'control.sock').exists():break
                    if proc.poll() is not None:pytest.fail((tmp_path/'engine.log').read_text()[-2000:])
                    time.sleep(.2)
                reader=EventReader()
                def refresh():
                    process_manual(station,reader);observe_queue(station);return status(station)
                refresh()
                def action(deck,operation):
                    observed=refresh();item=observed['mixer'][deck.lower()]
                    command=request_deck(station,user,deck,operation,track.uuid,str(item['decision_id']) if item else '',str(uuid.uuid4()),fade_seconds=0)
                    refresh();db.session.refresh(command);assert command.status=='sent',command.error_code
                    time.sleep(.3);return refresh(),command
                for deck in ('A','B'):
                    observed,command=action(deck,'LOAD');identifier=command.target_decision_id
                    assert observed['mixer'][deck.lower()]['decision_id']==identifier
                    assert not observed['mixer'][deck.lower()+'_playing']
                    assert db.session.get(SelectionDecision,identifier).status=='queued'
                    observed,_=action(deck,'PLAY')
                    assert observed['current']['decision_id']==identifier
                    assert db.session.get(SelectionDecision,identifier).status=='started'
                    observed,_=action(deck,'PAUSE');elapsed=observed['mixer'][deck.lower()+'_elapsed'];time.sleep(.3)
                    assert abs(refresh()['mixer'][deck.lower()+'_elapsed']-elapsed)<.1
                    observed,replacement=action(deck,'LOAD');identifier=replacement.target_decision_id
                    assert observed['mixer'][deck.lower()+'_elapsed']==0
                    time.sleep(.2);assert refresh()['mixer'][deck.lower()+'_elapsed']==0
                    observed,_=action(deck,'PLAY');assert observed['current']['decision_id']==identifier
                observed,command=action('B','REPEAT');repeat=command.target_decision_id
                time.sleep(4);observed=refresh()
                assert observed['current']['decision_id']==repeat
                assert db.session.get(SelectionDecision,repeat).status=='started'
                for deck in ('A','B'):
                    observed,_=action(deck,'CLEAR');assert observed['mixer'][deck.lower()] is None
                assert refresh()['current'] is None
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()


def test_recorded_crossfade_has_both_tones_and_live_meter(app,tmp_path,monkeypatch):
    """Spectral energy must ramp in both directions, not just switch flags."""
    import math, wave, struct
    from app.services.playout_queue import _command,deck_control,mixer_state,program_rms
    media=tmp_path/'media';runtime=tmp_path/'runtime';directory=runtime/'test-station';directory.mkdir(parents=True)
    originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    for key,hz in [('a',440),('b',880)]:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={hz}:duration=25','-y',str(originals/(key*32+'.mp3'))],check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media));monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.automation.operator_mode='DJ_BOOTH'
        source=render_liquidsoap(station,'a'*64).replace('/run/freo/playout/test-station',str(directory))
    recording=tmp_path/'crossfade.wav'
    source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav, "{recording}", radio)\n'
    config=tmp_path/'crossfade.liq';config.write_text(source)
    with (tmp_path/'crossfade.log').open('w') as log:
        proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
        try:
            for _ in range(300):
                if (directory/'control.sock').exists():break
                if proc.poll() is not None:pytest.fail((tmp_path/'crossfade.log').read_text()[-2500:])
                time.sleep(.2)
            for deck,key,bus,identifier in [('A','a','freo_a',1),('B','b','freo_b',2)]:
                deck_control('test-station',deck,'clear')
                _command('test-station',f'{bus}.push annotate:freo_decision={identifier}:{originals/(key*32+".mp3")}')
            time.sleep(1)
            deck_control('test-station','A','take',0);time.sleep(.8)
            assert 0 < program_rms('test-station') < 1
            deck_control('test-station','B','take',2);time.sleep(.6)
            state=mixer_state('test-station');assert state['a_playing'] and state['b_playing']
            assert state['transition']['incoming']=='B' and 0<state['transition']['progress']<1
            time.sleep(1.8)
            state=mixer_state('test-station');assert not state['a_playing'] and state['b_playing']
            deck_control('test-station','A','take',2);time.sleep(2.4)
            state=mixer_state('test-station');assert state['a_playing'] and not state['b_playing']
            # An old delayed completion must not stop a newer Take Air command.
            deck_control('test-station','B','take',1);time.sleep(.2)
            deck_control('test-station','A','take',0);time.sleep(1.1)
            state=mixer_state('test-station');assert state['a_playing'] and not state['b_playing']
            deck_control('test-station','A','fade',.5);time.sleep(.8)
            assert not mixer_state('test-station')['a_playing']
        finally:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    # Downsample each 100 ms window; exact-bin Fourier amplitudes isolate decks.
    with wave.open(str(recording),'rb') as wav:
        rate=wav.getframerate();channels=wav.getnchannels();assert wav.getsampwidth()==2
        from array import array
        data=array('h')
        while chunk:=wav.readframes(rate):data.frombytes(chunk)
        if __import__('sys').byteorder!='little':data.byteswap()
    mono=data[::channels];size=rate//10
    levels=[]
    for start in range(0,len(mono)-size,size):
        window=mono[start:start+size:4]
        amplitudes=[]
        for hz in (440,880):
            real=sum(value*math.cos(2*math.pi*hz*4*i/rate) for i,value in enumerate(window))
            imag=sum(value*math.sin(2*math.pi*hz*4*i/rate) for i,value in enumerate(window))
            amplitudes.append(math.hypot(real,imag)*2/len(window))
        levels.append(amplitudes)
    peak_a=max(a for a,b in levels);peak_b=max(b for a,b in levels)
    ratios=[(a/peak_a,b/peak_b) for a,b in levels]
    assert sum(.15<a<.85 and .15<b<.85 for a,b in ratios)>=18
    assert any(a>.8 and b<.1 for a,b in ratios)
    assert any(b>.8 and a<.1 for a,b in ratios)
    # During a ramp, several consecutive windows must move gradually both ways.
    assert sum(a2<a1-.015 and b2>b1+.015 for (a1,b1),(a2,b2) in zip(ratios,ratios[1:]))>=10
    assert sum(a2>a1+.015 and b2<b1-.015 for (a1,b1),(a2,b2) in zip(ratios,ratios[1:]))>=10


@pytest.mark.parametrize('deck',['A','B'])
@pytest.mark.parametrize('direction',['to_auto','to_dj'])
def test_auto_and_dj_crossfade(app,tmp_path,monkeypatch,deck,direction):
    import math,wave
    from array import array
    from app.services.playout_queue import _command,deck_control,mixer_state,program_decision_id
    runtime=tmp_path/'runtime';directory=runtime/'test-station';directory.mkdir(parents=True)
    originals=tmp_path/'media'/'test-station'/'originals';originals.mkdir(parents=True)
    for key,hz in [('a',440),('b',880)]:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={hz}:duration=20','-y',str(originals/(key*32+'.mp3'))],check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'));monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.automation.operator_mode='AUTO' if direction=='to_dj' else 'DJ_BOOTH'
        source=render_liquidsoap(station,'a'*64).replace('/run/freo/playout/test-station',str(directory))
    recording=tmp_path/'auto.wav'
    source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav,"{recording}",radio)\n'
    config=tmp_path/'auto.liq';config.write_text(source)
    with (tmp_path/'auto.log').open('w') as log:
        proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
        try:
            for _ in range(300):
                if (directory/'control.sock').exists():break
                if proc.poll() is not None:pytest.fail((tmp_path/'auto.log').read_text()[-2500:])
                time.sleep(.2)
            bus='freo_a' if deck=='A' else 'freo_b'
            if direction=='to_auto':
                deck_control('test-station',deck,'clear')
                _command('test-station',f'{bus}.push annotate:freo_decision=1:{originals/("a"*32+".mp3")}')
                time.sleep(.5);deck_control('test-station',deck,'take',0);time.sleep(1)
                _command('test-station','freo_mixer.mode AUTO')
                _command('test-station',f'freo_queue.push annotate:freo_decision=2:{originals/("b"*32+".mp3")}')
            else:
                _command('test-station',f'freo_queue.push annotate:freo_decision=1:{originals/("a"*32+".mp3")}')
                time.sleep(1)
                _command('test-station','freo_mixer.mode DJ_BOOTH')
                time.sleep(1)
                standby=mixer_state('test-station')
                assert standby['auto_standby'] and standby['a_id'] is None and standby['b_id'] is None
                assert program_decision_id('test-station')==1
                deck_control('test-station',deck,'clear')
                _command('test-station',f'{bus}.push annotate:freo_decision=2:{originals/("b"*32+".mp3")}')
                time.sleep(.5)
                assert program_decision_id('test-station')==1
                assert not mixer_state('test-station')[deck.lower()+'_playing']
                deck_control('test-station',deck,'take',3)
            time.sleep(.8)
            assert program_decision_id('test-station')==1
            assert mixer_state('test-station')[deck.lower()+'_playing']
            time.sleep(4)
            assert program_decision_id('test-station')==2
            assert mixer_state('test-station')['mode']==('AUTO' if direction=='to_auto' else 'DJ_BOOTH')
            if direction=='to_dj':assert mixer_state('test-station')['auto_gain']==0
        finally:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    with wave.open(str(recording),'rb') as wav:
        rate=wav.getframerate();channels=wav.getnchannels();data=array('h',wav.readframes(wav.getnframes()))
    mono=data[::channels];size=rate//10;levels=[]
    for start in range(0,len(mono)-size,size):
        window=mono[start:start+size:4];pair=[]
        for hz in (440,880):
            real=sum(v*math.cos(2*math.pi*hz*4*i/rate) for i,v in enumerate(window))
            imag=sum(v*math.sin(2*math.pi*hz*4*i/rate) for i,v in enumerate(window))
            pair.append(math.hypot(real,imag)*2/len(window))
        levels.append(pair)
    outgoing=max(a for a,b in levels);incoming=max(b for a,b in levels)
    assert outgoing>100 and incoming>100
    ratios=[(a/outgoing,b/incoming) for a,b in levels]
    assert sum(.1<a<.9 and .1<b<.9 for a,b in ratios)>=15
    assert sum(a2<a1-.01 for (a1,_),(a2,_) in zip(ratios,ratios[1:]))>=15
