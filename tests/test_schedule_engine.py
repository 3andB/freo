"""Isolated installed-engine proof of a confirmed scheduling fade and retry."""
import os
import subprocess
import time
import uuid
import pytest
from app.extensions import db
from app.models import Station, Track, SelectionDecision
from app.services.station_runtime import render_liquidsoap
from app.services.visual_schedule import policy, transition_request
from app.services.schedule_switch import process_transition
from app.services.playout_queue import push_decision, socket_identity, program_rms, program_decision_id
from app.automation_worker import EventReader
from tests.test_web import app

pytestmark=pytest.mark.skipif(os.environ.get('FREO_ENGINE_TEST')!='1',reason='Explicit isolated Liquidsoap integration')


@pytest.mark.parametrize('target_mode', ['SIMPLE', 'BLOCKS', 'CALENDAR', 'SIMPLE_BLOCK'])
@pytest.mark.parametrize('event_phase', ['none', 'waiting', 'playing'])
def test_confirmed_switch_fades_immediately_and_retry_does_not_restart(app,tmp_path,monkeypatch,event_phase,target_mode):
    media=tmp_path/'media';runtime=tmp_path/'runtime';directory=runtime/'test-station';directory.mkdir(parents=True)
    originals=media/'test-station'/'originals';originals.mkdir(parents=True);key='a'*32+'.mp3'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=40','-y',str(originals/key)],check=True)
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(media));monkeypatch.setattr('app.services.playout_queue.SOCKET_ROOT',runtime);monkeypatch.setattr('app.automation_worker.EVENT_ROOT',runtime)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();song=Track.query.first();song.storage_key=key;song.duration_ms=40000
        p=policy(station,True)
        if target_mode!='SIMPLE':
            from app.services import visual_schedule as vs
            from datetime import datetime, timezone
            block=vs.save_composition(station,dict(kind='BLOCK',name='Engine Block',sections=[dict(id='song',start=0,end=86400,source=dict(kind='song',id=song.id))]));db.session.flush()
            ref=vs.source(station,dict(kind='block',id=block.id),allow_block=True)
            rule=dict(frequency='once',anchor=datetime.now(timezone.utc).date().isoformat())
            p.assignments=vs.clean_document(station,[dict(id='today',rule=rule,pattern=[ref])],assignments=True)
            p.calendar=vs.clean_document(station,[dict(id='today',rule=rule,start=0,end=86400,source=ref)])
            p.calendar_saved=True
        db.session.commit()
        source=render_liquidsoap(station,'test-only').replace('/run/freo/playout/test-station',str(directory))
        source='settings.init.allow_root := true\n'+source[:source.index('output.icecast(')]+f'output.file(%wav,"{tmp_path}/recording.wav",radio)\n'
        config=tmp_path/'engine.liq';config.write_text(source)
        with (tmp_path/'engine.log').open('w') as log:
            proc=subprocess.Popen(['liquidsoap',str(config)],stdout=log,stderr=log)
            try:
                for _ in range(900):
                    if (directory/'control.sock').exists():break
                    if proc.poll() is not None:pytest.fail((tmp_path/'engine.log').read_text()[-3000:])
                    time.sleep(.1)
                assert (directory/'control.sock').exists(),(tmp_path/'engine.log').read_text()[-3000:]
                current=SelectionDecision(station_id=station.id,track_id=song.id,status='selected');db.session.add(current);db.session.commit()
                current.liquidsoap_request_id=push_decision(current);current.socket_identity=socket_identity(station.slug);current.status='queued';db.session.commit()
                reader=EventReader()
                for _ in range(100):
                    reader.collect(station.slug)
                    if current.status=='started' and program_rms(station.slug)>.03:break
                    time.sleep(.1)
                assert current.status=='started'
                from app.services.playout_queue import _command, event_bus
                if event_phase != 'none':
                    event = SelectionDecision(station_id=station.id,track_id=song.id,status='queued',selection_method='timed_event')
                    db.session.add(event);db.session.commit()
                    event.liquidsoap_request_id=int(_command(station.slug,f'freo_event.push annotate:freo_decision={event.id}:{originals/key}'))
                    event.socket_identity=socket_identity(station.slug);db.session.commit()
                    assert event_bus(station.slug,'arm',123)=='OK'
                    if event_phase == 'playing':
                        _command(station.slug,'freo_queue.skip')
                        for _ in range(50):
                            reader.collect(station.slug)
                            if event.status=='started':break
                            time.sleep(.1)
                        assert event.status=='started'
                    assert event_bus(station.slug)==f'123|{event_phase.upper()}'
                mode='SIMPLE' if target_mode=='SIMPLE_BLOCK' else target_mode
                simple=ref if target_mode=='SIMPLE_BLOCK' else dict(kind='song',id=song.id)
                payload=dict(id=str(uuid.uuid4()),mode=mode,current='CALENDAR',revision=p.revision,simple=simple)
                command=transition_request(station,payload);db.session.commit();began=time.monotonic();levels=[]
                for _ in range(50):
                    process_transition(station,reader);levels.append(program_rms(station.slug))
                    if command.state=='APPLIED':break
                    time.sleep(.1)
                assert command.state=='APPLIED',command.error
                assert time.monotonic()-began<8 # outgoing song still has over 30 seconds remaining
                assert p.mode==mode and p.activated
                assert event_bus(station.slug)=='|WAITING'
                assert _command(station.slug,'freo_event.queue')==''
                if event_phase == 'playing':
                    assert not any(line.startswith(f'END {event.id} ') for line in (directory/'events.log').read_text().splitlines())
                assert min(levels)<max(levels)*.7,levels
                identifier=command.decision_id;assert program_decision_id(station.slug)==identifier
                assert transition_request(station,payload).id==command.id
                assert not process_transition(station,reader)
                time.sleep(.3);assert program_decision_id(station.slug)==identifier
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
