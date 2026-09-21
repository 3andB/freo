"""Eligibility, replay protection and boundary continuity for prepared DJ return."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from app.extensions import db
from app.models import AuditEvent, SelectionDecision, BoothCue, LiveControlCommand
from app.automation_worker import EventReader, prepare_dj_return, continuity_depth
from app.services.live_assist import accept_engine_return, set_mode
from app.services.playout_queue import mixer_state
from tests.test_web import app
from tests.test_deck_controls import prepared


@pytest.mark.parametrize('gate', ['cue','auto-cue','pending','disabled','calendar','cart','other-deck','repeat','transition','too-early'])
def test_preparation_does_not_take_over_another_operation(prepared, monkeypatch, gate):
    station, track, user, snapshot = prepared
    mixer = dict(snapshot.mixer, auto_return_id=None, auto_standby=False,
                 a_elapsed=track.duration_ms/1000-4, transition={})
    if gate=='cart': mixer['cart_id']=42
    if gate=='other-deck': mixer.update(b_id=43,b_playing=True)
    if gate=='transition': mixer['transition']={'incoming':'A'}
    if gate=='too-early': mixer['a_elapsed']=0
    if gate=='auto-cue': db.session.add(BoothCue(station_id=station.id,auto_enabled=True))
    if gate=='pending': db.session.add(LiveControlCommand(station_id=station.id,action='DECK_PLAY',status='pending',idempotency_key='pending-return-test'))
    if gate=='disabled': station.automation.enabled=False
    db.session.commit()
    if gate=='calendar':
        monkeypatch.setattr('app.automation_worker.resolve',lambda *args:SimpleNamespace(next_transition=datetime.now(timezone.utc)+timedelta(seconds=2)))
    calls=[]
    monkeypatch.setattr('app.services.playout_queue._command',lambda slug,command:calls.append(command))
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[44] if gate=='repeat' else [])
    monkeypatch.setattr('app.automation_worker.refill_station',lambda *args:pytest.fail('Competing operation must retain control'))
    prepare_dj_return(station,EventReader(),mixer,cue_active=gate=='cue')
    assert calls==['freo_mixer.return_cancel']


@pytest.mark.parametrize('invalid', [None,'engine','session','station','not-started'])
def test_engine_return_is_scoped_and_consumed_once(prepared,monkeypatch,invalid):
    station,track,user,snapshot=prepared
    row=db.session.get(SelectionDecision,snapshot.current_decision_id)
    now=datetime.now(timezone.utc)
    row.started_at=now
    if invalid=='engine':row.socket_identity='old-engine'
    if invalid=='station':row.station_id=2
    if invalid=='not-started':row.status='queued'
    db.session.add(AuditEvent(station_id=station.id,action='live_mode_changed',target_type='station',
        target_id=station.slug,summary='DJ_BOOTH',created_at=now+timedelta(seconds=1 if invalid=='session' else -1)))
    db.session.commit()
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda slug:'engine')
    assert accept_engine_return(station,row.id)==(invalid is None)
    if invalid is None:
        assert station.automation.operator_mode=='AUTO'
        assert not accept_engine_return(station,row.id)
        assert AuditEvent.query.filter_by(action='live_auto_return').count()==1
    else:
        assert station.automation.operator_mode=='DJ_BOOTH'


@pytest.mark.parametrize('remaining, expected', [(20,0),(5,1),(1,1),(-1,1),(None,1)])
def test_boundary_lookahead_preserves_imminent_or_empty_output(prepared,monkeypatch,remaining,expected):
    station,track,user,snapshot=prepared
    row=db.session.get(SelectionDecision,snapshot.current_decision_id)
    now=datetime.now(timezone.utc)
    row.started_at=now-timedelta(milliseconds=track.duration_ms)+timedelta(seconds=remaining or 0)
    monkeypatch.setattr('app.services.playout_queue.program_decision_id',lambda slug:None if remaining is None else row.id)
    assert continuity_depth(station,now)==expected


@pytest.mark.parametrize('identifier', ['', '42', '-1','nan','1.5'])
def test_return_telemetry_is_validated(monkeypatch,identifier):
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:
        'AUTO|0.|false|false||||0.|0.||1.|0.|0.|false|23|1.|false|'+identifier)
    if identifier in ('','42'):
        assert mixer_state('test-station')['auto_return_id']==(int(identifier) if identifier else None)
    else:
        with pytest.raises(RuntimeError,match='return identity'):mixer_state('test-station')


def test_entering_booth_preserves_scheduled_standby(prepared,monkeypatch):
    station,track,user,snapshot=prepared
    reader=EventReader()
    reader.dj_return_prepared.add(station.slug)
    calls=[]
    monkeypatch.setattr('app.services.playout_queue._command',lambda slug,command:calls.append(command))
    monkeypatch.setattr('app.services.programming_refresh.refresh',lambda *args:pytest.fail('Standby schedule was cleared'))
    prepare_dj_return(station,reader,dict(snapshot.mixer,auto_return_id=None,auto_standby=True))
    assert calls==['freo_mixer.return_cancel']
    assert station.slug not in reader.dj_return_prepared


def test_eof_observation_does_not_cancel_or_renew_the_last_lease(prepared,monkeypatch):
    station,track,user,snapshot=prepared
    reader=EventReader();reader.dj_return_prepared.add(station.slug)
    calls=[]
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:pytest.fail('EOF lease was cancelled or renewed'))
    monkeypatch.setattr('app.services.programming_refresh.signature',lambda *args:'current')
    monkeypatch.setattr('app.services.programming_refresh.refresh',lambda *args,**kwargs:calls.append(kwargs))
    prepare_dj_return(station,reader,dict(snapshot.mixer,a_id=None,auto_return_id=None,auto_id=42,auto_standby=False))
    assert calls==[{'prepared_auto_id':42}]


def test_repeated_dj_mode_request_does_not_create_a_new_session(prepared,monkeypatch):
    station,track,user,snapshot=prepared
    row=db.session.get(SelectionDecision,snapshot.current_decision_id)
    now=datetime.now(timezone.utc)
    row.started_at=now
    db.session.add(AuditEvent(station_id=station.id,action='live_mode_changed',target_type='station',
        target_id=station.slug,summary='DJ_BOOTH',created_at=now-timedelta(seconds=1)))
    db.session.commit()
    set_mode(station,user,'DJ_BOOTH')
    assert AuditEvent.query.filter_by(action='live_mode_changed').count()==1
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda slug:'engine')
    assert accept_engine_return(station,row.id)



def test_sync_does_not_undo_eof_between_snapshot_and_mode_write(prepared, monkeypatch):
    from app.services.playout_queue import sync_mixer
    station,track,user,snapshot=prepared
    row=db.session.get(SelectionDecision,snapshot.current_decision_id)
    row.started_at=datetime.now(timezone.utc)
    db.session.commit()
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda slug:'engine')
    engine={'mode':'DJ_BOOTH','auto_return_id':None}
    snapshots=[]
    def read(slug):
        observed=dict(engine)
        if not snapshots:
            # EOF renders after the snapshot, before sync_mixer can write.
            engine.update(mode='AUTO',auto_return_id=row.id)
        snapshots.append(observed)
        return observed
    def command(slug, command):
        engine['mode']=command.split()[-1]
        if engine['mode']=='DJ_BOOTH':engine['auto_return_id']=None
    monkeypatch.setattr('app.services.playout_queue.mixer_state',read)
    monkeypatch.setattr('app.services.playout_queue._command',command)
    sync_mixer(station)
    assert engine=={'mode':'AUTO','auto_return_id':row.id}
    sync_mixer(station)
    assert station.automation.operator_mode=='AUTO'
    assert AuditEvent.query.filter_by(action='live_auto_return').count()==1
