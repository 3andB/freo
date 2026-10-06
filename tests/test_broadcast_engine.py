"""Isolated real engine: event bus recovery, live controls and AAC Icecast output."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
import os
import socket
import subprocess
import time
import threading
import pytest
from app.extensions import db
from app.models import Station, Track, SelectionDecision, TimedEventOccurrence
from app.services.station_runtime import render_liquidsoap
from app.services.station_audio import processor_command
from app.services.playout_queue import _command, push_decision, program_rms
from app.services.timed_events import save_event
from app.services import bulletins
from app.services.relay_transport import RelayTransport
from tests.test_web import app
from tests.test_relay_engine import upstream, wait_for

pytestmark=pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST')!='1',reason='Explicit isolated real audio')


@pytest.mark.parametrize('failure',['disconnect','stall'])
def test_bulletin_file_live_failure_and_processor_controls(app,tmp_path,monkeypatch,failure):
    sockets=tmp_path/'sockets';directory=sockets/'test-station';directory.mkdir(parents=True)
    media=tmp_path/'media';originals=media/'test-station'/'originals';originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',sockets)
    app.config['FREO_BULLETIN_ROOT']=str(tmp_path/'bulletins')
    song=originals/('a'*32+'.mp3');remote=tmp_path/'remote.mp3'
    for target,hz in [(song,440),(remote,880)]:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={hz}:duration=120','-b:a','128k','-y',str(target)],check=True)
    with app.app_context(),upstream(remote.read_bytes()) as (url,up):
        station=Station.query.filter_by(slug='test-station').one();track=Track.query.first()
        track.storage_key=song.name;track.duration_ms=120000;db.session.commit()
        source=render_liquidsoap(station,'isolated').replace('/run/freo/playout/test-station',str(directory))
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav,"{tmp_path}/output.wav",radio)\n'
        script=tmp_path/'engine.liq';script.write_text(source)
        transport=RelayTransport(0,'127.0.0.1/32');reader=SimpleNamespace(relay_transport=transport)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(script)],stdout=log,stderr=log)
            try:
                wait_for(lambda:(directory/'control.sock').exists() or proc.poll() is not None,90)
                assert proc.poll() is None,(tmp_path/'engine.log').read_text()[-4000:]
                def music():
                    d=SelectionDecision(station_id=station.id,track=track,status='selected');db.session.add(d);db.session.commit();push_decision(d)
                music();wait_for(lambda:program_rms(station.slug)>.02)
                stop_probe=threading.Event();audio_stall=[0.0]
                def probe_output():
                    size=0;changed=time.monotonic()
                    while not stop_probe.wait(.05):
                        observed=(tmp_path/'output.wav').stat().st_size
                        if observed!=size:size=observed;changed=time.monotonic()
                        audio_stall[0]=max(audio_stall[0],time.monotonic()-changed)
                probe=threading.Thread(target=probe_output);probe.start()
                for preset in ('light','standard','punchy','off'):
                    assert _command(station.slug,processor_command(dict(bitrate=64,preset=preset)))=='OK'
                    time.sleep(.3);assert program_rms(station.slug)>.01 and proc.poll() is None
                with pytest.raises(RuntimeError):_command(station.slug,'freo_processor.apply 1.0 1.0 0.0 -99.0 1.0 0.0 0.0 0.0')
                assert _command(station.slug,'freo_processor.state')=='READY'
                def event(kind):
                    row=save_event(station.slug,name='Bulletin '+kind,recurrence_type='HOURLY',local_time='00:00',
                        content_type='BULLETIN',content_identifier='',bulletin=dict(kind=kind,url=url,duration=30))
                    occurrence=TimedEventOccurrence.query.filter_by(timed_event_id=row.id).first()
                    occurrence.scheduled_for_utc=datetime.now(timezone.utc)-timedelta(seconds=1)
                    occurrence.deadline_at_utc=datetime.now(timezone.utc)+timedelta(minutes=5)
                    db.session.commit();return occurrence
                live=event('LIVE')
                assert bulletins.prepare(live,reader,datetime.now(timezone.utc))
                wait_for(lambda:'|READY|' in _command(station.slug,'freo_bulletin.state'))
                assert _command(station.slug,f'freo_event.arm {live.id}')=='OK'
                # Simulate the current song reaching its boundary; queued automation is retained.
                music();_command(station.slug,'freo_queue.skip')
                wait_for(lambda:'|BODY|' in _command(station.slug,'freo_bulletin.state'))
                assert _command(station.slug,'freo_program.current')==''
                assert bulletins.reconcile(station,reader)
                monkeypatch.setattr('app.services.broadcast_status.observation',lambda slug:(True,0))
                from app.automation_worker import observe_queue
                from app.models import LiveQueueSnapshot
                observe_queue(station)
                current=db.session.get(LiveQueueSnapshot,station.id).current_decision_id
                assert current and db.session.get(SelectionDecision,current).reason==f'bulletin:{live.id}:body'
                if failure=='disconnect':up['up']=False
                else:up['stall']=True
                wait_for(lambda:'|FAILED|' in _command(station.slug,'freo_bulletin.state'),15)
                assert _command(station.slug,'freo_event.state').startswith('|')
                assert program_rms(station.slug)>.01
                live.state='FAILED';db.session.commit()
                bumper=originals/('b'*32+'.mp3')
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=990:duration=1','-y',str(bumper)],check=True)
                imaging=Track(station_id=station.id,uuid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',title='Station bumper',artist='Station',original_filename='bumper.mp3',storage_key=bumper.name,media_type='mp3',audio_kind='STATION',duration_ms=1000,sample_rate_hz=44100,channels=1,file_size_bytes=bumper.stat().st_size,checksum_sha256='b'*64,enabled=True,ingest_status='accepted')
                db.session.add(imaging);db.session.commit()
                file=event('FILE');file.state='READY';db.session.commit()
                intro=bulletins.sequence_uri(file,dict(intro=imaging.uuid),'intro')
                outro=bulletins.sequence_uri(file,dict(outro=imaging.uuid),'outro')
                db.session.commit()
                folder=bulletins.root()/str(station.id);folder.mkdir(parents=True)
                target=folder/f'{file.id}.wav'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=660:duration=2','-y',str(target)],check=True)
                assert _command(station.slug,f'freo_bulletin.prepare {file.id}|FILE|{target}|2.000|{intro}|{outro}')=='OK'
                wait_for(lambda:'|READY|' in _command(station.slug,'freo_bulletin.state'))
                _command(station.slug,f'freo_event.arm {file.id}');music();_command(station.slug,'freo_queue.skip')
                wait_for(lambda:'|COMPLETED|' in _command(station.slug,'freo_bulletin.state'),10)
                assert audio_stall[0]<3, f'Program output stalled for {audio_stall[0]:.3f}s'
                assert _command(station.slug,'freo_event.state').startswith('|')
                assert program_rms(station.slug)>.01
                from app.automation_worker import EventReader
                monkeypatch.setattr('app.automation_worker.EVENT_ROOT',sockets)
                EventReader().collect(station.slug)
                assert SelectionDecision.query.filter_by(track_id=imaging.id,status='started').count()==2
            finally:
                if 'stop_probe' in locals():stop_probe.set();probe.join(timeout=2)
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
                transport.close()


def test_aac_and_mp3_real_icecast(tmp_path):
    from urllib.request import build_opener,ProxyHandler
    import tempfile
    opener=build_opener(ProxyHandler({}))
    # Icecast refuses root; create a traversable dedicated directory for nobody.
    with tempfile.TemporaryDirectory(prefix='freo-phase10-icecast-') as folder:
        root=Path(folder);root.chmod(0o777)
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        config=Path('deploy/icecast/icecast.xml.template').read_text()
        for key in ('SOURCE','ADMIN','RELAY'):config=config.replace('__'+key+'_PASSWORD__','isolated-pass')
        config=config.replace('<port>8001</port>',f'<port>{port}</port>').replace('/var/log/icecast2',str(root))
        ice=root/'icecast.xml';ice.write_text(config);ice.chmod(0o644)
        script=root/'encoder.liq'
        from app.services.station_audio import encoder_liquidsoap
        lines=['settings.init.allow_root := true','settings.log.level := 2','radio = sine(amplitude=0.15,440.0)']
        for codec in ('mp3','aac'):
            lines.append(f'output.icecast({encoder_liquidsoap(dict(bitrate=192,codec=codec))},host="127.0.0.1",port={port},password="isolated-pass",mount="/{codec}",radio)')
        script.write_text('\n'.join(lines))
        with (root/'server.log').open('w') as log,(root/'encoder.log').open('w') as engine_log:
            server=subprocess.Popen(['icecast2','-c',str(ice)],stdout=log,stderr=log,user='nobody',group='nogroup')
            engine=subprocess.Popen(['liquidsoap',str(script)],stdout=engine_log,stderr=engine_log)
            try:
                def online():
                    try:
                        with opener.open(f'http://127.0.0.1:{port}/aac',timeout=2) as response:return bool(response.read(512))
                    except OSError:return False
                wait_for(online,90)
                for codec in ('mp3','aac'):
                    with opener.open(f'http://127.0.0.1:{port}/{codec}',timeout=4) as response:
                        assert response.headers.get_content_type()==('audio/mpeg' if codec=='mp3' else 'audio/aac')
                        data=response.read(65536)
                    target=tmp_path/f'output.{codec}';target.write_bytes(data)
                    subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],check=True,timeout=10)
            finally:
                for proc in (engine,server):
                    proc.terminate()
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()


def test_file_download_permissions_match_installed_accounts(tmp_path):
    import tempfile,threading,pwd,grp,sys
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    audio=tmp_path/'remote.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1','-y',str(audio)],check=True)
    payload=audio.read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Type','audio/wav');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='freo-bulletin-permissions-') as folder:
            root=Path(folder);group=grp.getgrnam('freo-playout').gr_gid
            os.chown(root,pwd.getpwnam('freo-automation').pw_uid,group);root.chmod(0o2750)
            code="import os; from pathlib import Path; from app.services.bulletins import fetch_file; os.umask(0o077); fetch_file("+repr(f'http://127.0.0.1:{server.server_port}/audio')+",'127.0.0.1/32',Path("+repr(str(root/'1'))+"),1)"
            subprocess.run([sys.executable,'-c',code],check=True,capture_output=True,timeout=30,user='freo-automation',group='freo-automation',extra_groups=[group])
            output=root/'1'/'1.wav';assert output.stat().st_gid==group and output.stat().st_mode&0o777==0o640
            result=subprocess.run(['head','-c','4',str(output)],check=True,capture_output=True,user='freo-playout',group='freo-playout',extra_groups=[])
            assert result.stdout==b'RIFF'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
