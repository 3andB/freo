"""Restoration must preserve operator documents, including after a failed live run."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.extensions import db
from app.models import Station, ScheduleComposition
from app.services import visual_schedule as vs
from tests.test_web import app
from tests.test_block_scheduling import seed_block

spec=importlib.util.spec_from_file_location('live_stress',Path(__file__).parents[1]/'scripts/stress-live-stations.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def restoration(app,tmp_path):
    runner=module.LiveStress.__new__(module.LiveStress)
    runner.app=app;runner.root=tmp_path;calls=[]
    runner.live=lambda *args,**kwargs:calls.append(('live',args,kwargs))
    runner.switch=lambda *args,**kwargs:calls.append(('switch',args,kwargs))
    runner.event=lambda *args,**kwargs:calls.append(('event',args,kwargs))
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        p=vs.policy(station,True);p.mode='SIMPLE';p.activated=True
        block,_=seed_block(station,'Temporary stress block')
        original=dict(mode='SIMPLE',calendar=[],assignments=[],calendar_saved=False,
            activation='original',activated=True,live_simple=None,temporary_block_id=block.id,
            installed_calendar=[{'id':'owned-calendar'}],installed_assignments=[{'id':'owned-assignment'}])
        p.calendar=copy.deepcopy(original['installed_calendar'])
        p.assignments=copy.deepcopy(original['installed_assignments'])
        p.calendar_saved=True;p.activation='test-activation'
        db.session.commit()
    module.write_json(tmp_path/'originals.json',{'test-station':original})
    return runner,calls,original


def test_restore_removes_only_owned_fixtures_and_is_idempotent(restoration):
    runner,calls,original=restoration
    runner.restore()
    with runner.app.app_context():
        p=vs.policy(Station.query.filter_by(slug='test-station').one())
        assert p.calendar==[] and p.assignments==[] and not p.calendar_saved
        assert p.activation=='original'
        assert db.session.get(ScheduleComposition,original['temporary_block_id']).archived
    assert json.loads((runner.root/'restoration.json').read_text())['status']=='restored'
    before=len(calls);runner.restore();assert len(calls)==before


@pytest.mark.parametrize('field',['calendar','assignments'])
def test_restore_does_not_overwrite_an_operator_edit(restoration,field):
    runner,calls,original=restoration
    with runner.app.app_context():
        p=vs.policy(Station.query.filter_by(slug='test-station').one())
        setattr(p,field,[{'id':'operator-change'}]);db.session.commit()
    with pytest.raises(RuntimeError,match='Restoration needs review'):
        runner.restore()
    assert calls==[]  # No playback change before ownership is checked.
    with runner.app.app_context():
        p=vs.policy(Station.query.filter_by(slug='test-station').one())
        assert getattr(p,field)==[{'id':'operator-change'}]
        assert not db.session.get(ScheduleComposition,original['temporary_block_id']).archived


def test_existing_output_cannot_restore_another_active_run(tmp_path):
    runner=module.LiveStress.__new__(module.LiveStress)
    runner.root=tmp_path
    runner.preflight=lambda:None
    runner.restore=lambda:pytest.fail('Must not restore a different run')
    with pytest.raises(RuntimeError,match='new output directory'):
        runner.run()


@pytest.fixture
def authenticated_runner(app, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'create_app', lambda: app)
    runner=module.LiveStress(SimpleNamespace(output=tmp_path))
    runner.base='https://station.example.test'
    return runner


def test_runner_renews_expired_cookie_without_changing_application_policy(authenticated_runner, monkeypatch):
    from itsdangerous import TimestampSigner, SignatureExpired
    runner=authenticated_runner
    now=TimestampSigner.get_timestamp
    monkeypatch.setattr(TimestampSigner,'get_timestamp',lambda self:now(self)-3601)
    runner.authenticate()
    old=runner.cookie
    monkeypatch.setattr(TimestampSigner,'get_timestamp',now)
    serializer=runner.app.session_interface.get_signing_serializer(runner.app)
    with pytest.raises(SignatureExpired):serializer.loads(old,max_age=3600)
    with runner.app.test_request_context('/',headers={'Cookie':runner.cookie_name+'='+old}):
        from flask import request
        assert not runner.app.session_interface.open_session(runner.app,request)
    runner.auth_until=0
    cookies=[]
    runner.driver=SimpleNamespace(add_cookie=lambda cookie:cookies.append(cookie))
    runner.authenticate(browser=True)
    assert serializer.loads(runner.cookie,max_age=3600)['admin_user_id']==runner.admin_id
    assert cookies[0]['value']==runner.cookie and runner.cookie!=old
    assert runner.app.permanent_session_lifetime.total_seconds()==3600


def test_unexpected_html_does_not_replay_mutation(authenticated_runner):
    from io import BytesIO
    runner=authenticated_runner
    calls=[]
    response=BytesIO(b'<html>Sign in</html>')
    response.url=runner.base+'/admin/login';response.status=200
    response.headers={'Content-Type':'text/html'}
    def open_request(request,timeout):
        calls.append(request)
        return response
    runner.opener=SimpleNamespace(open=open_request)
    with pytest.raises(RuntimeError,match='expected authenticated JSON'):
        runner.api('/admin/stations/test-station/live/deck',{'operation':'LOAD'})
    assert len(calls)==1


def test_redirect_is_not_followed_for_a_mutation():
    assert module.NoRedirect().redirect_request(None,None,302,'Found',{},'/admin/login') is None


def test_stop_hook_reports_success_without_erasing_failed_run(restoration):
    runner,_,_=restoration
    module.write_json(runner.root/'run.json',{'status':'failed','failure':'original error'})
    runner.restore()
    result=json.loads((runner.root/'run.json').read_text())
    assert result['status']=='failed' and result['failure']=='original error'
    assert result['cleanup_status']=='restored'



def test_a_different_playing_request_cannot_count_as_a_successful_dj_session(authenticated_runner):
    runner=authenticated_runner
    runner.metrics['stations']['test-station']={'dj_returns':0}
    runner.sessions['test-station']={'kind':4,'deck':'A','expected_decision':42,
        'seen_playing':False,'modified':False,'began':module.time.monotonic(),
        'deadline':module.time.monotonic()+60}
    runner.session('test-station',{'mode':'AUTO','mixer':{'a_id':43,'a_playing':True}})
    assert runner.metrics['stations']['test-station']['dj_returns']==0
    assert not runner.sessions['test-station']['seen_playing']


def test_failed_load_is_detected_before_waiting_for_eof(authenticated_runner, monkeypatch):
    runner=authenticated_runner
    runner.originals={'test-station':{'station_id':1}}
    runner.event=lambda *args,**kwargs:None
    states=iter([{'mixer':{}},{'deck_command':{'id':5,'status':'failed','error':'control_failed'}}])
    runner.status=lambda slug:next(states)
    runner.live=lambda *args,**kwargs:None
    query=SimpleNamespace(filter_by=lambda **kwargs:SimpleNamespace(one=lambda:SimpleNamespace(id=5,target_decision_id=42)))
    monkeypatch.setattr(module,'LiveControlCommand',SimpleNamespace(query=query))
    with pytest.raises(RuntimeError,match='LOAD failed'):
        runner.deck('test-station','A','LOAD',{'uuid':'track'})


def test_existing_event_edit_is_preserved_before_cleanup(restoration):
    runner,calls,original=restoration
    from app.models import TimedEvent,Track
    with runner.app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        original['station_id']=station.id
        original['temporary_event_names']=['owned event']
        row=TimedEvent(uuid='owned-test-event',station_id=station.id,name='owned event',revision=2,
            timing_mode='SOFT',recurrence_type='ONE_TIME',scheduled_at_utc=module.datetime.now(module.timezone.utc),
            content_type='TRACK',track_id=Track.query.first().id)
        db.session.add(row);db.session.commit()
    module.write_json(runner.root/'originals.json',{'test-station':original})
    with pytest.raises(RuntimeError,match='edited'):
        runner.restore()
    assert calls==[]



def test_temporary_hard_and_soft_events_are_durable_and_disabled_on_restore(authenticated_runner, restoration):
    runner=authenticated_runner
    original_runner,_,original=restoration
    runner.app=original_runner.app;runner.root=original_runner.root
    from app.models import Track,TimedEvent
    with runner.app.app_context():
        station=Station.query.filter_by(slug='test-station').one()
        original['station_id']=station.id
        runner.plan={'test-station':{'event_track':Track.query.first().uuid,'event_audio_kind':'MUSIC'}}
    runner.args.stations=['test-station']
    runner.originals={'test-station':original}
    runner.switch=lambda *args,**kwargs:None
    runner.live=lambda *args,**kwargs:None
    runner.install_events()
    saved=json.loads((runner.root/'originals.json').read_text())['test-station']
    assert len(saved['temporary_event_names'])==2
    with runner.app.app_context():
        assert {e.timing_mode for e in TimedEvent.query.filter_by(enabled=True)}=={'HARD','SOFT'}
    runner.restore()
    with runner.app.app_context():
        assert TimedEvent.query.filter_by(enabled=True).count()==0



def test_only_rendered_request_counts_for_dj_playback(authenticated_runner):
    runner=authenticated_runner
    runner.metrics['stations']['test-station']={'dj_returns':0}
    runner.sessions['test-station']={'kind':4,'deck':'A','expected_decision':42,
        'seen_playing':False,'modified':False,'began':module.time.monotonic(),
        'deadline':module.time.monotonic()+60}
    # A prepared deck with PLAY intent does not prove that its audio reached air.
    state={'mode':'DJ_BOOTH','mixer':{'a_id':42,'a_playing':True},'_rendered_decision_id':41}
    runner.session('test-station',state)
    assert not runner.sessions['test-station']['seen_playing']
    state['_rendered_decision_id']=42
    runner.session('test-station',state)
    assert runner.sessions['test-station']['seen_playing']
