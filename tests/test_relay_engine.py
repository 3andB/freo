"""Private HTTP upstream and real Liquidsoap proof; never touches installed radio."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
import pytest
from app import models as m
from app.extensions import db
from app.services.station_runtime import render_liquidsoap
from app.services.playout_queue import _command, push_decision, program_rms
from app.services.relay import read_engine
from app.services.relay_transport import RelayTransport
from tests.test_web import app

pytestmark = pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST') != '1', reason='Explicit private Liquidsoap integration')


@contextmanager
def upstream(audio):
    state = dict(up=True, stall=False, metadata='Relay artist - Relay title')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            if not state['up']:
                self.send_error(503); return
            self.send_response(200); self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('icy-metaint', '4096'); self.end_headers()
            cursor = 0
            try:
                while state['up']:
                    if state['stall']:
                        time.sleep(.05); continue
                    block = bytes(audio[(cursor+i) % len(audio)] for i in range(4096)); cursor += 4096
                    title = ("StreamTitle='" + state['metadata'] + "';").encode()
                    padded = title + b'\0' * (-len(title) % 16)
                    self.wfile.write(block + bytes([len(padded)//16]) + padded); self.wfile.flush()
                    time.sleep(.256)  # 128kbps continuous stream
            except (OSError, ValueError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}/stream', state
    finally: state['up'] = False; server.shutdown(); server.server_close(); thread.join(timeout=2)


def wait_for(check, timeout=30):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        result = check()
        if result: return result
        time.sleep(.1)
    pytest.fail('Timed out waiting for relay transition')


@pytest.mark.parametrize('failure', ['disconnect', 'stall'])
def test_relay_fallback_recovery_and_disable(app, tmp_path, monkeypatch, failure):
    runtime = tmp_path/'run'; directory=runtime/'test-station'; directory.mkdir(parents=True)
    media=tmp_path/'media'; originals=media/'test-station'/'originals'; originals.mkdir(parents=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media))
    monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime)
    monkeypatch.setattr('app.automation_worker.EVENT_ROOT',runtime)
    song=originals/('a'*32+'.mp3'); upstream_file=tmp_path/'upstream.mp3'
    for file, frequency in [(song,440),(upstream_file,880)]:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={frequency}:duration=300','-b:a','128k','-y',str(file)],check=True)
    with app.app_context(), upstream(upstream_file.read_bytes()) as (url, state):
        transport=RelayTransport(0,'127.0.0.1/32')
        station=m.Station.query.filter_by(slug='test-station').one()
        track=m.Track.query.filter_by(station_id=station.id).one();track.storage_key=song.name;track.duration_ms=300000
        db.session.commit()
        source=render_liquidsoap(station,'isolated-test').replace('/run/freo/playout/test-station',str(directory))
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav,"{tmp_path}/output.wav",radio)\n'
        config=tmp_path/'engine.liq';config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                wait_for(lambda: (directory/'control.sock').exists() or proc.poll() is not None,90)
                assert proc.poll() is None,(tmp_path/'engine.log').read_text()[-4000:]
                local=m.SelectionDecision(station_id=station.id,track=track,status='selected');db.session.add(local);db.session.commit()
                push_decision(local)
                wait_for(lambda: program_rms(station.slug)>.02)
                stop_probe=threading.Event();audio_stall=[0.0]
                def probe_output():
                    size=0;changed=time.monotonic()
                    while not stop_probe.wait(.05):
                        observed=(tmp_path/'output.wav').stat().st_size
                        if observed!=size:size=observed;changed=time.monotonic()
                        audio_stall[0]=max(audio_stall[0],time.monotonic()-changed)
                probe=threading.Thread(target=probe_output);probe.start()
                state['up']=False
                capability=transport.configure(station.id,url)
                _command(station.slug,'freo_relay.apply 1 '+capability)
                time.sleep(1)
                assert not read_engine(station.slug)['selected'] and program_rms(station.slug)>.02
                state['up']=True
                wait_for(lambda: read_engine(station.slug)['connected'])
                assert not read_engine(station.slug)['selected']
                wait_for(lambda: read_engine(station.slug)['source']=='relay')
                assert _command(station.slug,'freo_program.current')==''
                wait_for(lambda: 'Relay title' in read_engine(station.slug)['title'])
                time.sleep(1.1)
                # A fallback schedule switch acknowledges prepared audio without
                # fading the relay or fabricating START evidence for that song.
                local=m.SelectionDecision(station_id=station.id,track=track,status='selected');db.session.add(local);db.session.commit()
                rid=push_decision(local)
                assert _command(station.slug,f'freo_schedule.switch aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa {rid}')=='APPLIED'
                assert read_engine(station.slug)['source']=='relay' and program_rms(station.slug)>.02
                # No new START confirmations while local audio is paused.
                before=(directory/'events.log').read_text();time.sleep(1.5)
                assert (directory/'events.log').read_text()==before
                # Upstream loss must retain playable local audio, including a stalled body.
                state['up']=failure != 'disconnect'
                state['stall']=failure == 'stall'
                levels=[]
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    levels.append(program_rms(station.slug))
                    if read_engine(station.slug)['source']=='automation': break
                    time.sleep(.1)
                assert read_engine(station.slug)['source']=='automation'
                assert min(levels)>.005
                wait_for(lambda: _command(station.slug,'freo_program.current')==str(local.id),3)
                for _ in range(10):
                    assert program_rms(station.slug)>.005
                    assert read_engine(station.slug)['source']=='automation'
                    time.sleep(.1)
                assert read_engine(station.slug)['failure']>0
                state['up']=True;state['stall']=False
                wait_for(lambda: read_engine(station.slug)['connected'])
                time.sleep(2);assert not read_engine(station.slug)['selected']
                wait_for(lambda: read_engine(station.slug)['source']=='relay')
                # DJ control overrides relay, then returns to the fresh relay.
                _command(station.slug,'freo_mixer.mode DJ_BOOTH')
                dj=m.SelectionDecision(station_id=station.id,track=track,status='selected',reason='deck_load',playback_bus='A')
                db.session.add(dj);db.session.commit();push_decision(dj)
                _command(station.slug,'freo_deck.take_a 0.000')
                wait_for(lambda: read_engine(station.slug)['source']=='dj')
                wait_for(lambda: _command(station.slug,'freo_program.current')==str(dj.id),3)
                push_decision(local)
                _command(station.slug,'freo_mixer.mode AUTO')
                wait_for(lambda: read_engine(station.slug)['source']=='relay')
                # URL replacement/disable invalidates the old transport capability.
                _command(station.slug,'freo_relay.apply 2 -');transport.configure(station.id,'')
                wait_for(lambda: read_engine(station.slug)['source']=='automation')
                assert program_rms(station.slug)>.02
                assert proc.poll() is None
                assert audio_stall[0]<3, f'Program output stalled for {audio_stall[0]:.3f}s'
            finally:
                if 'stop_probe' in locals():stop_probe.set();probe.join(timeout=2)
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
                transport.close()
