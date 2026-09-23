"""Opt-in real two-station Icecast/Liquidsoap lifecycle isolation proof.

Systemd/Nginx actions are replaced by an isolated process supervisor and a
recorded proxy check. Rendering, engine validation, audio, reloads, and cleanup
use the real implementations, entirely under a temporary directory.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import time
from urllib.request import ProxyHandler, build_opener
import pytest
from app.extensions import db
from app.models import Track, SelectionDecision
from app.services.stations import create_station, request_delete
from app.services.station_lifecycle import process_station
from app.services import station_runtime as runtime
from app.services.playout_queue import push_decision
from tests.test_stations import station_app

pytestmark=pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST')!='1',reason='Explicit isolated Icecast/Liquidsoap integration')


def test_stream_survives_other_station_creation_deletion_and_owner_removal(station_app,monkeypatch):
    opener=build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix='freo-stream-check-') as directory:
        root=Path(directory);root.chmod(0o755)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        configs=root/'radio'/'stations';secrets=root/'secrets';snippets=root/'snippets';playlists=root/'playlists';sockets=root/'sockets'
        for name in (configs.parent,secrets,playlists,sockets):name.mkdir(parents=True,exist_ok=True)
        monkeypatch.setattr(runtime,'ROOT',root)
        monkeypatch.setattr(runtime,'CONFIGS',configs)
        monkeypatch.setattr(runtime,'SECRETS',secrets)
        monkeypatch.setattr(runtime,'SNIPPETS',snippets)
        monkeypatch.setattr(runtime,'PLAYLISTS',playlists)
        monkeypatch.setattr('app.services.media.PLAYLIST_ROOT',playlists)
        monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',sockets)
        monkeypatch.setenv('FREO_MEDIA_ROOT',str(root/'media'))
        processes={};logs=[];icecast=None
        ice_config=root/'icecast.xml'
        def render_icecast():
            source=(runtime.SOURCE/'deploy/icecast/icecast.xml.template').read_text()
            for key in ('SOURCE','ADMIN','RELAY'):source=source.replace('__'+key+'_PASSWORD__','a'*64)
            mounts=''.join(f'<mount><mount-name>/{p.stem}</mount-name><password>{json.loads(p.read_text())["source"]}</password></mount>' for p in secrets.glob('*.json'))
            source=source.replace('<hostname>localhost</hostname>',mounts+'<hostname>localhost</hostname>').replace('<port>8001</port>',f'<port>{port}</port>').replace('/var/log/icecast2',str(root))
            ice_config.write_text(source);ice_config.chmod(0o644)
            (root/'radio'/'icecast.xml').write_text(source)
        render_icecast()
        log=(root/'icecast.log').open('w');logs.append(log)
        icecast=subprocess.Popen(['icecast2','-c',str(ice_config)],stdout=log,stderr=log,start_new_session=True,user='nobody',group='nogroup')
        def stream(slug):
            with opener.open(f'http://127.0.0.1:{port}/{slug}',timeout=2) as response:
                assert response.headers.get_content_type()=='audio/mpeg'
                assert len(response.read(512))==512
        def wait_for_stream(slug):
            # Cold Liquidsoap initialization competes with browser/encoder
            # checks on CI. Bound wall time and fail immediately on process exit.
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                try:stream(slug);return
                except OSError:
                    if processes[slug].poll() is not None:break
                    time.sleep(.5)
            detail=(root/(slug+'.log')).read_text()[-3000:]
            pytest.fail(f'Stream {slug} never became available (process={processes[slug].poll()}): {detail}')
        original_render=runtime.render_liquidsoap
        def render(station,password):
            import pwd, grp
            directory=sockets/station.slug
            directory.mkdir(exist_ok=True)
            os.chown(directory,pwd.getpwnam('freo-playout').pw_uid,grp.getgrnam('freo-playout').gr_gid)
            directory.chmod(0o750)
            return original_render(station,password).replace('/run/freo/playout',str(sockets)).replace('/var/lib/freo/playlists',str(playlists)).replace('port=8001',f'port={port}')
        monkeypatch.setattr(runtime,'render_liquidsoap',render)
        def service(slug,action):
            proc=processes.get(slug)
            if action=='status':return bool(proc and proc.poll() is None)
            if action=='stop':
                if proc and proc.poll() is None:
                    proc.terminate();proc.wait(timeout=10)
                return
            assert action=='start'
            log=(root/(slug+'.log')).open('w');logs.append(log)
            processes[slug]=subprocess.Popen(['liquidsoap',str(configs/(slug+'.liq'))],stdout=log,stderr=log,
                cwd=root,user='freo-playout',group='freo-playout',extra_groups=[])
        monkeypatch.setattr(runtime,'service_action',service)
        def checked(args):
            if 'render-radio-config.py' in args[-1]:render_icecast()
            elif args[:2]==['/usr/sbin/nginx','-t']:pass
            elif args[:2]==['/bin/systemctl','reload']:
                if args[-1]=='icecast2.service':os.killpg(icecast.pid,signal.SIGHUP)
            else:subprocess.run(args,check=True,capture_output=True,timeout=90)
        monkeypatch.setattr(runtime,'run_checked',checked)
        original_process = process_station
        def provision(station):
            mask=os.umask(0o077)
            try:original_process(station)
            finally:os.umask(mask)
        try:
            with station_app.app_context():
                first=create_station('First','first',pending=True);provision(first)
                runtime.service_action(first.slug,'start');first.desired_state='running';db.session.commit();wait_for_stream('first')
                first_pid=processes['first'].pid
                second=create_station('Second','second',pending=True);provision(second)
                runtime.service_action(second.slug,'start');second.desired_state='running';db.session.commit();wait_for_stream('second')
                stream('first');assert processes['first'].pid==first_pid
                # An approved shared track remains in its original media namespace.
                audio=root/'media'/'first'/'originals'/('a'*32+'.mp3')
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=523:duration=4','-y',str(audio)],check=True)
                song=Track(station_id=first.id,uuid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',title='Shared proof',artist='Test',original_filename='proof.mp3',storage_key=audio.name,media_type='mp3',duration_ms=4000,sample_rate_hz=44100,channels=2,file_size_bytes=audio.stat().st_size,checksum_sha256='a'*64,enabled=True,ingest_status='accepted',available_to_all=True)
                db.session.add(song);db.session.commit()
                request_delete(first);process_station(first)
                assert processes['first'].poll() is not None
                stream('second');assert audio.exists()
                decision=SelectionDecision(station_id=second.id,track=song,status='selected');db.session.add(decision);db.session.commit()
                assert push_decision(decision)>=0
                from app.services.playout_queue import program_decision_id
                for _ in range(40):
                    if program_decision_id('second') == decision.id:
                        break
                    time.sleep(.1)
                else:
                    pytest.fail('Shared track was queued but never reached the program output')
                stream('second')
                assert not (configs/'first.liq').exists() and not (secrets/'first.json').exists()
                third=create_station('Replacement','replacement',pending=True);provision(third)
                runtime.service_action(third.slug,'start');wait_for_stream('replacement');stream('second')
                request_delete(third);process_station(third);stream('second')
                request_delete(second);process_station(second)
                assert processes['second'].poll() is not None
                assert audio.exists() and song.available_to_all
        finally:
            for proc in processes.values():
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
            if icecast and icecast.poll() is None:
                os.killpg(icecast.pid,signal.SIGTERM)
                try:icecast.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(icecast.pid,signal.SIGKILL);icecast.wait()
            for log in logs:log.close()
