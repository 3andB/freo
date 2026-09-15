"""Real queue replacement and cart exclusivity with isolated generated audio."""
import os
import subprocess
import time
import uuid
from pathlib import Path
from datetime import datetime,timezone
import pytest
from app.extensions import db
from app.models import Station,Track,AdminUser,SelectionDecision,LiveCartSlot
from app.services.station_runtime import render_liquidsoap
from app.services.live_assist import fire_cart,request_skip,status
from app.services.programming_refresh import signature,refresh as refresh_programming
from app.automation_worker import EventReader,process_manual,observe_queue,refill_station
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST')!='1',reason='Explicit isolated Liquidsoap integration')


def test_programming_edit_replaces_next_song_and_cart_locks_until_actual_end(app,tmp_path,monkeypatch):
    media=tmp_path/'media';runtime=tmp_path/'runtime';directory=runtime/'test-station';directory.mkdir(parents=True)
    originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    for key,hz,duration in [('a',440,30),('b',880,30),('c',660,4)]:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={hz}:duration={duration}','-y',str(originals/(key*32+'.mp3'))],check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT',runtime)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();old=Track.query.first();old.storage_key='a'*32+'.mp3';old.duration_ms=30000
        user=AdminUser.query.first();category=old.categories[0];db.session.commit()
        source=render_liquidsoap(station,'a'*64).replace('/run/freo/playout/test-station',str(directory))
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav, "{tmp_path}/audio.wav", radio)\n'
        config=tmp_path/'engine.liq';config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                for _ in range(300):
                    if (directory/'control.sock').exists():break
                    if proc.poll() is not None:pytest.fail((tmp_path/'engine.log').read_text()[-2500:])
                    time.sleep(.2)
                reader=EventReader()
                def observe():process_manual(station,reader);observe_queue(station);return status(station)
                def wait_until(predicate):
                    for _ in range(100):
                        result=observe()
                        if predicate(result):return result
                        time.sleep(.1)
                    pytest.fail('Expected engine state was not observed')
                refill_station(station.slug,reader,3)
                current=wait_until(lambda state:state['current'] and state['current']['started_at'])['current']['decision_id']
                prior=[row['decision_id'] for row in observe()['queue']];assert prior
                new=[]
                for key,name,duration in [('b','Updated category song',30000),('c','Short cart',4000)]:
                    audio=originals/(key*32+'.mp3')
                    song=Track(station_id=station.id,uuid=str(uuid.uuid4()),title=name,artist='Test',original_filename=name+'.mp3',storage_key=audio.name,
                        media_type='mp3',duration_ms=duration,sample_rate_hz=44100,channels=2,file_size_bytes=audio.stat().st_size,checksum_sha256=key*64,enabled=True,ingest_status='accepted')
                    db.session.add(song);new.append(song)
                old.enabled=False;category.tracks.append(new[0]);db.session.commit()
                assert refresh_programming(station,reader,signature(station))
                refill_station(station.slug,reader,2)
                observed=observe()
                assert observed['current']['decision_id']==current
                assert all(item['title']=='Updated category song' for item in observed['queue'])
                assert all(db.session.get(SelectionDecision,identifier).reason=='programming_changed' for identifier in prior)
                from app.services.playout_queue import fade_current
                with pytest.raises(RuntimeError):fade_current(station.slug,current+10000)
                assert observe()['current']['decision_id']==current
                request_skip(station,user,current,str(uuid.uuid4()))
                wait_until(lambda state:state['current'] and state['current']['title']=='Updated category song' and state['current']['started_at'])
                for pos in (1,2):db.session.add(LiveCartSlot(station_id=station.id,role='HOT',position=pos,track_id=new[1].id,label='Cart '+str(pos)))
                db.session.commit()
                nonce=str(uuid.uuid4());cart=fire_cart(station,user,'HOT',1,nonce)
                assert fire_cart(station,user,'HOT',1,nonce).id==cart.id
                with pytest.raises(ValueError):fire_cart(station,user,'HOT',2,str(uuid.uuid4()))
                observed=wait_until(lambda state:state['cart']['state']=='playing')
                assert observed['cart']['position']==1 and observed['cart']['locked']
                with pytest.raises(ValueError):fire_cart(station,user,'HOT',2,str(uuid.uuid4()))
                wait_until(lambda state:not state['cart']['locked'])
                assert fire_cart(station,user,'HOT',2,str(uuid.uuid4())).id!=cart.id
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
