"""Real worker/engine EOF regression: measure programme tones, not backup RMS."""
import json
import math
import os
import subprocess
import time
import uuid
import wave
from array import array
from datetime import datetime, timezone

import pytest

from app.extensions import db
from app.models import AdminUser, Station, Track, LiveControlCommand, AuditEvent, SelectionDecision, BoothCue
from app.services.live_assist import request_deck, set_mode
from app.services.playout_queue import mixer_state, program_decision_id, queued_order, request_decision_id
from tests.system_harness import SystemStack, wait_for, stop_process

pytestmark = pytest.mark.skipif(os.environ.get('FREO_SYSTEM_TEST') != '1', reason='Isolated real audio regression')


@pytest.fixture
def handoff_stack(monkeypatch, tmp_path):
    from app.services import station_runtime
    original = station_runtime.render_liquidsoap
    recording = tmp_path/'handoff.wav'
    def render(*args, **kwargs):
        source = original(*args, **kwargs)
        return source.replace('output.icecast(', f'output.file(%wav, "{recording}", radio)\noutput.icecast(')
    monkeypatch.setattr(station_runtime, 'render_liquidsoap', render)
    stack = SystemStack(monkeypatch, tmp_path)
    try:
        with stack.app.app_context():
            track = db.session.get(Track, stack.track_ids[2])
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=880:duration=12',
                            str(stack.media/stack.slug/'originals'/track.storage_key)], check=True)
            track.duration_ms = 12000
            db.session.commit()
        stack.start()
        yield stack
    finally:
        stack.close()


@pytest.mark.parametrize('deck', ['A','B'])
@pytest.mark.parametrize('boundary', [False, True, 'underestimated'], ids=['ordinary','calendar-window','duration-underestimate'])
def test_natural_dj_end_has_continuous_programme(handoff_stack, deck, boundary):
    stack = handoff_stack
    if boundary=='underestimated':
        def shorten_metadata():
            db.session.get(Track,stack.track_ids[2]).duration_ms=11000
            db.session.commit()
        stack.query(shorten_metadata)
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)))
    def station(): return Station.query.filter_by(slug=stack.slug).one()
    stack.query(lambda: set_mode(station(), AdminUser.query.first(), 'DJ_BOOTH'))
    wait_for(lambda: stack.query(lambda: mixer_state(stack.slug)['mode']=='DJ_BOOTH'))
    def load():
        command = request_deck(station(), AdminUser.query.first(), deck, 'LOAD', stack.track_uuids[2],
                               '', str(uuid.uuid4()), fade_seconds=0, play_on_load=True)
        return command.target_decision_id
    identifier = stack.query(load)
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)==identifier))
    if boundary is True:
        def schedule():
            from app.services import visual_schedule as vs
            policy = vs.policy(station())
            now = datetime.now(timezone.utc)
            second = now.hour*3600+now.minute*60+now.second
            assert second+24 < 86400, 'Retry boundary fixture outside the last minute of UTC day'
            rule = dict(frequency='daily', anchor=now.date().isoformat())
            policy.calendar = vs.clean_document(station(), [dict(id=str(i),start=start,end=end,
                source=policy.live_simple,rule=rule) for i,(start,end) in enumerate([(0,second+24),(second+24,86400)])])
            policy.mode = 'CALENDAR'
            db.session.commit()
        stack.query(schedule)
    wait_for(lambda: stack.query(lambda: station().automation.operator_mode=='AUTO'), timeout=35)
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug) not in (None,identifier)), timeout=35)
    time.sleep(2)
    stack.stop_worker()
    stop_process(stack.engine)
    windows = tone_windows(stack.evidence/'handoff.wav')
    last_dj = max(i for i,(dj,_) in enumerate(windows) if dj>500)
    next_music = next(i for i in range(last_dj+1,len(windows)) if windows[i][1]>500)
    gap = (next_music-last_dj-1)/20
    (stack.evidence/'handoff-result.json').write_text(json.dumps(dict(deck=deck,boundary=boundary,gap_seconds=gap)))
    assert gap <= .25, f'Programme absent for {gap:.2f}s after DJ EOF (backup does not count as music)'


@pytest.mark.parametrize('operation', ['repeat','clear','pause','lease-expiry','worker-delay','worker-restart','schedule-edit','auto-cue'])
def test_prepared_return_respects_deck_changes_and_worker_lifetime(handoff_stack, operation):
    stack=handoff_stack
    def station():return Station.query.filter_by(slug=stack.slug).one()
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)))
    stack.query(lambda: set_mode(station(),AdminUser.query.first(),'DJ_BOOTH'))
    wait_for(lambda: stack.query(lambda: mixer_state(stack.slug)['mode']=='DJ_BOOTH'))
    def cue_edit(**data):
        from app.services.booth_cue import mutate
        cue=db.session.get(BoothCue,station().id)
        return mutate(station(),AdminUser.query.first(),dict(revision=str(cue.revision if cue else 0),nonce=str(uuid.uuid4()),**data))
    entry_id=None
    if operation=='auto-cue':
        for uuid_value in (stack.track_uuids[2],stack.track_uuids[1]):
            stack.query(lambda: cue_edit(operation='add',identifier=uuid_value))
        entry_id=stack.query(lambda: db.session.get(BoothCue,station().id).entries[0]['id'])
    identifier=stack.query(lambda: request_deck(station(),AdminUser.query.first(),'A','LOAD',stack.track_uuids[2],
        '',str(uuid.uuid4()),fade_seconds=0,play_on_load=True,cue_entry_id=entry_id).target_decision_id)
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)==identifier))
    wait_for(lambda: stack.query(lambda: mixer_state(stack.slug)['a_elapsed']>=6))
    def prepared():
        current=mixer_state(stack.slug).get('auto_id')
        if current and db.session.get(SelectionDecision,current).status=='queued':return current
        future=queued_order(stack.slug)
        return request_decision_id(stack.slug,future[0]) if future else None
    replacement=wait_for(lambda: stack.query(prepared))
    def prepared_ids():
        ids={request_decision_id(stack.slug,rid) for rid in queued_order(stack.slug)}
        current=mixer_state(stack.slug).get('auto_id')
        if current and db.session.get(SelectionDecision,current).status=='queued':ids.add(current)
        return ids
    assert stack.query(prepared_ids)=={replacement}, 'Prepared a second replacement for an already loaded request'
    assert stack.query(lambda: program_decision_id(stack.slug))==identifier, 'Test operation arrived after DJ EOF'
    assert stack.query(lambda: mixer_state(stack.slug)['a_elapsed'])<10, 'Test operation needs two seconds before EOF'
    if operation in ('repeat','clear','pause'):
        command=stack.query(lambda: request_deck(station(),AdminUser.query.first(),'A',operation.upper(),None,
            str(identifier),str(uuid.uuid4())).id)
        wait_for(lambda: stack.query(lambda: db.session.get(LiveControlCommand,command).status=='sent'))
        if operation=='repeat':
            target=stack.query(lambda: db.session.get(LiveControlCommand,command).target_decision_id)
            wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)==target))
        assert stack.query(lambda: mixer_state(stack.slug)['mode'])=='DJ_BOOTH'
        assert stack.query(lambda: AuditEvent.query.filter_by(action='live_auto_return').count())==0
    elif operation=='auto-cue':
        stack.query(lambda: cue_edit(operation='auto',enabled='true'))
        wait_for(lambda: stack.query(lambda: SelectionDecision.query.filter_by(selection_method='cue_auto',status='started').count()==1))
        assert stack.query(lambda: station().automation.operator_mode)=='DJ_BOOTH'
        assert stack.query(lambda: db.session.get(SelectionDecision,replacement).status)=='failed'
        assert stack.query(lambda: db.session.get(SelectionDecision,program_decision_id(stack.slug)).track_id)==stack.track_ids[1]
    elif operation=='schedule-edit':
        def change():
            from app.services import visual_schedule as vs
            policy=vs.policy(station())
            policy.simple=policy.live_simple=vs.source(station(),dict(kind='song',id=stack.track_ids[1]))
            db.session.commit()
            (stack.evidence/'schedule-edit-at.json').write_text(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),current=program_decision_id(stack.slug))))
        stack.query(change)
        wait_for(lambda: stack.query(lambda: station().automation.operator_mode=='AUTO'))
        current=stack.query(lambda: program_decision_id(stack.slug))
        assert current!=replacement
        assert stack.query(lambda: db.session.get(SelectionDecision,current).track_id)==stack.track_ids[1]
        assert stack.query(lambda: db.session.get(SelectionDecision,replacement).status)=='failed'
    else:
        if operation=='worker-delay':
            wait_for(lambda: stack.query(lambda: mixer_state(stack.slug)['a_elapsed']>=8.3))
        stack.stop_worker()
        if operation=='worker-delay':
            time.sleep(4)
            assert stack.query(lambda: mixer_state(stack.slug)['mode'])=='AUTO', 'Brief worker delay lost the prepared EOF handoff'
            stack.start_worker()
            wait_for(lambda: stack.query(lambda: station().automation.operator_mode=='AUTO'))
        elif operation=='lease-expiry':
            time.sleep(8)
            assert stack.query(lambda: mixer_state(stack.slug)['mode'])=='DJ_BOOTH'
            assert stack.query(lambda: program_decision_id(stack.slug))!=replacement
        else:
            stack.start_worker()
            wait_for(lambda: stack.query(lambda: station().automation.operator_mode=='AUTO'))
            assert stack.query(lambda: program_decision_id(stack.slug))==replacement
            assert stack.query(lambda: AuditEvent.query.filter_by(action='live_auto_return').count())==1
    if operation in ('clear','pause'):
        wait_for(lambda: stack.query(lambda: station().automation.operator_mode=='AUTO'))
        time.sleep(2)
        stack.stop_worker()
        stop_process(stack.engine)
        windows=tone_windows(stack.evidence/'handoff.wav')
        last=max(i for i,(dj,_) in enumerate(windows) if dj>500)
        first=next(i for i in range(last+1,len(windows)) if windows[i][1]>500)
        gap=(first-last-1)/20
        (stack.evidence/'manual-stop-result.json').write_text(json.dumps(dict(operation=operation,audio_gap=gap)))
        assert gap<=2.75, f'{operation}: {gap:.2f}s exceeds the 2s operator grace plus recovery allowance'
    if operation in ('worker-restart','worker-delay','schedule-edit'):
        target=stack.query(lambda: program_decision_id(stack.slug))
        def interval():
            rows=[line.split() for line in (stack.runtime/stack.slug/'events.log').read_text().splitlines()]
            ended=next((float(r[2]) for r in rows if r[:2]==['END',str(identifier)]),None)
            started=next((float(r[1]) for r in rows if r[0]==str(target)),None)
            return (started-ended,) if ended is not None and started is not None else None
        event_gap=wait_for(interval)[0]
        time.sleep(1)
        stack.stop_worker()
        stop_process(stack.engine)
        windows=tone_windows(stack.evidence/'handoff.wav')
        last=max(i for i,(dj,_) in enumerate(windows) if dj>500)
        first=next(i for i in range(last+1,len(windows)) if windows[i][1]>500)
        gap=(first-last-1)/20
        (stack.evidence/'recovery-result.json').write_text(json.dumps(dict(operation=operation,event_gap=event_gap,audio_gap=gap)))
        assert gap<=.25, f'{operation}: programme absent for {gap:.2f}s after EOF'


def tone_windows(path):
    with wave.open(str(path)) as recording:
        rate, channels = recording.getframerate(), recording.getnchannels()
        audio = array('h', recording.readframes(recording.getnframes()))[::channels]
    # 50 ms separates 400 Hz backup from the 440/660/880 Hz programme tones.
    size = rate//20
    windows = []
    for start in range(0,len(audio)-size,size):
        samples = audio[start:start+size:4]
        def amplitude(hz):
            real=sum(v*math.cos(2*math.pi*hz*4*i/rate) for i,v in enumerate(samples))
            imag=sum(v*math.sin(2*math.pi*hz*4*i/rate) for i,v in enumerate(samples))
            return 2*math.hypot(real,imag)/len(samples)
        windows.append((amplitude(880),max(amplitude(440),amplitude(660))))
    return windows


@pytest.mark.parametrize('boundary,lead_seconds', [
    ('calendar',12), ('calendar',14), ('calendar',16),
    ('hard-event',14), ('soft-event',14)])
def test_auto_does_not_run_empty_inside_boundary_window(handoff_stack,boundary,lead_seconds):
    stack=handoff_stack
    wait_for(lambda: stack.query(lambda: program_decision_id(stack.slug)))
    def configure():
        from datetime import timedelta
        from app.services import visual_schedule as vs
        from app.services.timed_events import save_event
        station=Station.query.filter_by(slug=stack.slug).one()
        now=datetime.now(timezone.utc)
        due=now+timedelta(seconds=lead_seconds)
        if boundary=='calendar':
            policy=vs.policy(station)
            second=due.hour*3600+due.minute*60+due.second
            assert due.date()==now.date(), 'Retry fixture outside the last minute of UTC day'
            rule=dict(frequency='daily',anchor=now.date().isoformat())
            policy.calendar=vs.clean_document(station,[dict(id=str(i),start=start,end=end,
                source=policy.live_simple,rule=rule) for i,(start,end) in enumerate([(0,second),(second,86400)])])
            policy.mode='CALENDAR'
            db.session.commit()
        else:
            save_event(stack.slug,name='Boundary continuity ID',timing_mode='HARD' if boundary=='hard-event' else 'SOFT',
                recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=stack.track_uuids[0],
                local_date=due.date().isoformat(),local_time=due.strftime('%H:%M:%S'),
                late_tolerance_seconds=60,interrupt_policy='MUSIC_ONLY' if boundary=='hard-event' else 'NEVER')
    stack.query(configure)
    time.sleep(27)
    stack.stop_worker()
    stop_process(stack.engine)
    windows=tone_windows(stack.evidence/'handoff.wav')
    present=[music>500 for _,music in windows]
    first=present.index(True)
    last=len(present)-1-present[::-1].index(True)
    longest=current=0
    for audible in present[first:last+1]:
        current=0 if audible else current+1
        longest=max(longest,current)
    (stack.evidence/'boundary-result.json').write_text(json.dumps(dict(boundary=boundary,lead_seconds=lead_seconds,gap_seconds=longest/20)))
    assert longest/20 <= .25, f'{boundary}: missing programme audio for {longest/20}s'
