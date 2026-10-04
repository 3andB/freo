"""Isolated Liquidsoap proof: real leader START precedes smart-playlist music."""
import os
import subprocess
import time
import pytest
from app import models as m
from app.extensions import db
from app.services.station_runtime import render_liquidsoap
from app.services.visual_schedule import policy
from app.services.playout_queue import program_rms
from app.automation_worker import EventReader, refill_station, worker_delay
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST')!='1',reason='Explicit isolated Liquidsoap integration')


@pytest.mark.parametrize('seconds',[0.8,3.0])
def test_real_leader_then_dynamic_member_and_worker_restart(app,tmp_path,monkeypatch,seconds):
    runtime=tmp_path/'run';directory=runtime/'test-station';directory.mkdir(parents=True)
    media=tmp_path/'media';originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT',runtime)
    with app.app_context():
        station=m.Station.query.filter_by(slug='test-station').one();leader=m.Track.query.first()
        leader.storage_key='a'*32+'.mp3';leader.duration_ms=int(seconds*1000);leader.audio_kind='STATION'
        from tests.test_music_delete import add_song
        member=add_song(station,2);member.title='Dynamic member';member.genre='Review';member.duration_ms=5000
        for track,hz,duration in ((leader,440,seconds),(member,880,5)):
            subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={hz}:duration={duration}','-y',str(originals/track.storage_key)],check=True)
        row=m.Playlist(station_id=station.id,name='Engine review',leader_track=leader,smart_enabled=True,smart_rules={'genre':'Review'})
        db.session.add(row);db.session.flush()
        schedule=policy(station,True);schedule.mode='SIMPLE';schedule.activated=True
        schedule.simple=schedule.live_simple={'kind':'playlist','id':row.id};schedule.activation='phase1-engine'
        db.session.commit()
        source=render_liquidsoap(station,'isolated-test').replace('/run/freo/playout/test-station',str(directory))
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav,"{tmp_path}/recording.wav",radio)\n'
        config=tmp_path/'engine.liq';config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            process=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+90
                while not (directory/'control.sock').exists() and time.monotonic()<deadline:
                    if process.poll() is not None:pytest.fail((tmp_path/'engine.log').read_text()[-3000:])
                    time.sleep(.1)
                assert (directory/'control.sock').exists()
                reader=EventReader();heard=False;member_started=None
                deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    refill_station(station.slug,reader)
                    heard=heard or program_rms(station.slug)>.03
                    member_started=m.SelectionDecision.query.filter_by(station_id=station.id,track_id=member.id,status='started').first()
                    if member_started:break
                    time.sleep(worker_delay(reader))
                assert member_started is not None and heard,(tmp_path/'engine.log').read_text()[-3000:]
                leader_started=m.SelectionDecision.query.filter_by(selection_method='playlist_leader',status='started').one()
                assert leader_started.started_at <= member_started.started_at
                assert (member_started.started_at-leader_started.started_at).total_seconds() < seconds+2
                # A new reader emulates worker recovery while the engine persists.
                reader=EventReader();refill_station(station.slug,reader)
                assert m.SelectionDecision.query.filter_by(selection_method='playlist_leader').count()==1
                assert (directory/'events.log').read_text().count(str(leader_started.id)+' ')>=1
                assert (tmp_path/'recording.wav').stat().st_size>44100
            finally:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
