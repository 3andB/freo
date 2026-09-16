"""Deck intent is scoped to the displayed deck and rechecked by the worker."""
import uuid
from datetime import datetime,timezone
import pytest
from app.extensions import db
from app.models import Station,Track,AdminUser,LiveQueueSnapshot,SelectionDecision,LiveControlCommand
from app.services.live_assist import request_deck,status
from app.automation_worker import process_deck_command
from tests.test_web import app,admin_client

@pytest.fixture
def prepared(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.automation.operator_mode='DJ_BOOTH'
        track=Track.query.first();current=SelectionDecision.query.filter_by(status='started').first();current.socket_identity='engine';current.liquidsoap_request_id=11
        snapshot=LiveQueueSnapshot(station_id=station.id,current_decision_id=current.id,queued_decision_ids=[],observed_at=datetime.now(timezone.utc),mixer=dict(mode='DJ_BOOTH',a_id=current.id,b_id=None,cart_id=None,a_playing=True,b_playing=False,a_elapsed=2,b_elapsed=0,crossfader=0))
        db.session.add(snapshot);db.session.commit()
        yield station,track,AdminUser.query.first(),snapshot


def test_load_waits_for_worker_and_prepared_deck_does_not_claim_live(prepared,monkeypatch):
    station,track,user,snapshot=prepared;calls=[]
    command=request_deck(station,user,'B','LOAD',track.uuid,'',str(uuid.uuid4()))
    assert command.target_decision.playback_bus=='B' and command.target_decision.status=='selected'
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:snapshot.mixer)
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    monkeypatch.setattr('app.services.playout_queue.deck_control',lambda *args:calls.append(args))
    monkeypatch.setattr('app.automation_worker.push_decision',lambda _:22)
    process_deck_command(station,command,'engine')
    assert calls==[(station.slug,'B','clear')]
    observed=status(station)
    assert observed['mixer']['b']['decision_id']==command.target_decision.id
    assert observed['mixer']['b_playing'] is False
    assert observed['current']['decision_id']==snapshot.current_decision_id


@pytest.mark.parametrize('operation,engine_action',[('PLAY','take'),('PAUSE','pause'),('CLEAR','clear'),('FADE','fade')])
def test_each_button_targets_its_own_deck(prepared,monkeypatch,operation,engine_action):
    station,track,user,snapshot=prepared;calls=[]
    command=request_deck(station,user,'A',operation,None,str(snapshot.current_decision_id),str(uuid.uuid4()))
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:snapshot.mixer)
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    monkeypatch.setattr('app.services.playout_queue.deck_control',lambda *args:calls.append(args))
    process_deck_command(station,command,'engine')
    assert calls==[(station.slug,'A',engine_action,*([3.0] if operation in ('PLAY','FADE') else []))] and command.status=='sent'


def test_repeat_replaces_lookahead_on_same_deck(prepared,monkeypatch):
    station,track,user,snapshot=prepared;calls=[]
    command=request_deck(station,user,'A','REPEAT',None,str(snapshot.current_decision_id),str(uuid.uuid4()))
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:snapshot.mixer)
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    monkeypatch.setattr('app.services.playout_queue.deck_control',lambda *args:calls.append(args))
    monkeypatch.setattr('app.automation_worker.push_decision',lambda _:23)
    process_deck_command(station,command,'engine')
    assert calls==[(station.slug,'A','future')]
    assert command.target_decision.track_id==track.id and command.target_decision.playback_bus=='A'


@pytest.mark.parametrize('actual_decision', [9999, None], ids=['new-song', 'track-ended'])
def test_stale_request_and_duplicate_click_cannot_control_new_song(prepared,monkeypatch,actual_decision):
    station,track,user,snapshot=prepared;nonce=str(uuid.uuid4())
    command=request_deck(station,user,'A','CLEAR',None,str(snapshot.current_decision_id),nonce)
    assert request_deck(station,user,'A','CLEAR',None,str(snapshot.current_decision_id),nonce).id==command.id
    with pytest.raises(ValueError,match='still being applied'):
        request_deck(station,user,'B','LOAD',track.uuid,'',str(uuid.uuid4()))
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:dict(snapshot.mixer,a_id=actual_decision))
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    commands=[]
    monkeypatch.setattr('app.services.playout_queue.deck_control',lambda *args:commands.append(args))
    with pytest.raises(ValueError,match='Deck changed'):
        process_deck_command(station,command,'engine')
    assert commands==[]


def test_deck_endpoint_requires_csrf_and_dj_queue_is_rejected(app,prepared):
    client=admin_client(app);base='/admin/stations/test-station/live'
    assert client.post(base+'/deck',data={}).status_code==400
    response=client.post(base+'/queue-track',data={'csrf':'test-admin-csrf-token'},headers={'Accept':'application/json'})
    assert response.status_code==409 and 'Load songs onto a deck' in response.json['message']


def test_dj_does_not_start_an_obsolete_up_next_request(prepared,monkeypatch):
    from app.automation_worker import process_manual
    from types import SimpleNamespace
    station,track,user,snapshot=prepared
    old=SelectionDecision(station_id=station.id,track=track,playback_bus='A',admin_user_id=user.id,selection_method='manual_track',status='selected')
    db.session.add(old);db.session.commit()
    monkeypatch.setattr('app.automation_worker.reconcile_requests',lambda *args:None)
    monkeypatch.setattr('app.automation_worker.socket_identity',lambda *args:'engine')
    monkeypatch.setattr('app.automation_worker.queued_ids',lambda *args:set())
    monkeypatch.setattr('app.automation_worker.active_ids',lambda *args:set())
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    monkeypatch.setattr('app.automation_worker.push_decision',lambda *args:pytest.fail('An obsolete queue request reached air'))
    process_manual(station,SimpleNamespace(collect=lambda *args:None))
    assert old.status=='failed' and old.reason=='dj_decks_only'


@pytest.mark.parametrize('duration', [-1, 10.1, 'nan', 'inf', 'bad', None])
def test_invalid_fade_is_rejected(prepared, duration):
    station, track, user, snapshot = prepared
    with pytest.raises(ValueError, match='fade between'):
        request_deck(station,user,'B','LOAD',track.uuid,'',str(uuid.uuid4()),fade_seconds=duration)


def test_live_replacement_requires_confirmation_and_worker_starts_it(prepared, monkeypatch):
    station,track,user,snapshot=prepared;calls=[]
    expected=str(snapshot.current_decision_id)
    with pytest.raises(ValueError,match='Confirm replacement'):
        request_deck(station,user,'A','LOAD',track.uuid,expected,str(uuid.uuid4()))
    command=request_deck(station,user,'A','LOAD',track.uuid,expected,str(uuid.uuid4()),fade_seconds=1.5,play_on_load=True)
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:snapshot.mixer)
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    monkeypatch.setattr('app.services.playout_queue.deck_control',lambda *args:calls.append(args))
    monkeypatch.setattr('app.automation_worker.push_decision',lambda _:22)
    process_deck_command(station,command,'engine')
    assert calls==[(station.slug,'A','clear'),(station.slug,'A','take',1.5)]
    assert command.status=='sent'


def test_prepared_replacement_is_refused_if_deck_starts_before_worker(prepared, monkeypatch):
    station,track,user,snapshot=prepared
    snapshot.mixer=dict(snapshot.mixer,a_playing=False);db.session.commit()
    command=request_deck(station,user,'A','LOAD',track.uuid,str(snapshot.current_decision_id),str(uuid.uuid4()))
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:dict(snapshot.mixer,a_playing=True))
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    with pytest.raises(ValueError,match='started playing'):
        process_deck_command(station,command,'engine')


@pytest.mark.parametrize('duration',[0,0.5,10])
def test_fade_adapter_forwards_bounded_duration(monkeypatch,duration):
    from app.services.playout_queue import deck_control
    calls=[]
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:calls.append(args))
    deck_control('test-station','B','take',duration)
    assert calls==[('test-station',f'freo_deck.take_b {duration:.3f}')]


def test_prepared_or_empty_deck_does_not_inherit_elapsed(prepared):
    station,track,user,snapshot=prepared
    target=SelectionDecision(station_id=station.id,track=track,playback_bus='B',status='queued',selection_method='manual_track')
    db.session.add(target);db.session.flush()
    for identifier in (None,target.id):
        snapshot.mixer=dict(snapshot.mixer,b_id=identifier,b_playing=False,b_elapsed=75)
        db.session.commit()
        observed=status(station)
        assert observed['mixer']['b']['decision_id']==target.id
        assert observed['mixer']['b_elapsed']==0


def test_mixer_transition_telemetry_is_validated(monkeypatch):
    from app.services.playout_queue import mixer_state
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:'DJ_BOOTH|0.|true|true|1|2||4.|1.|B|0.5|0.5|0.5')
    assert mixer_state('test-station')['transition']==dict(incoming='B',progress=.5,a_gain=.5,b_gain=.5)
    for suffix in ('C|0.5|0.5|0.5','B|nan|0.5|0.5','B|0.5|2|0'):
        monkeypatch.setattr('app.services.playout_queue._command',lambda *args:'DJ_BOOTH|0.|true|true|1|2||4.|1.|'+suffix)
        with pytest.raises(RuntimeError,match='transition'):mixer_state('test-station')


def test_dj_stopping_returns_to_schedule_after_grace(prepared):
    from app.automation_worker import EventReader,return_to_auto_if_stopped
    from app.models import AuditEvent
    station,track,user,snapshot=prepared
    reader=EventReader();playing=dict(snapshot.mixer)
    assert not return_to_auto_if_stopped(station,reader,playing,now=1)
    # A worker restart must not disable stop detection for the current session.
    reader=EventReader()
    stopped=dict(playing,a_id=None,a_playing=False,b_id=None,b_playing=False)
    assert not return_to_auto_if_stopped(station,reader,stopped,now=2)
    assert not return_to_auto_if_stopped(station,reader,stopped,now=3)
    assert return_to_auto_if_stopped(station,reader,stopped,now=4)
    assert station.automation.operator_mode=='AUTO' and station.automation.enabled and not station.automation.hold
    assert 'DJ music stopped' in status(station)['mode_notice']['message']
    assert not return_to_auto_if_stopped(station,reader,stopped,now=8)
    assert AuditEvent.query.filter_by(action='live_auto_return').count()==1


def test_auto_return_allows_preparation_and_dj_handover(prepared):
    from app.automation_worker import EventReader,return_to_auto_if_stopped
    station,track,user,snapshot=prepared
    reader=EventReader();empty=dict(snapshot.mixer,a_id=None,a_playing=False)
    for now in (1,10,100):assert not return_to_auto_if_stopped(station,reader,empty,now=now)
    assert not return_to_auto_if_stopped(station,reader,snapshot.mixer,now=101)
    assert not return_to_auto_if_stopped(station,reader,empty,now=102)
    playing_b=dict(empty,b_id=123,b_playing=True)
    assert not return_to_auto_if_stopped(station,reader,playing_b,now=103)
    assert not return_to_auto_if_stopped(station,reader,empty,now=104)
    assert not return_to_auto_if_stopped(station,reader,dict(empty,cart_id=456),now=107)
    assert not return_to_auto_if_stopped(station,reader,empty,now=108)
    assert station.automation.operator_mode=='DJ_BOOTH'


def test_scheduled_queue_is_not_shown_on_empty_dj_decks(prepared):
    station,track,user,snapshot=prepared
    snapshot.mixer=dict(snapshot.mixer,a_id=None,a_playing=False,auto_id=snapshot.current_decision_id,auto_standby=True,auto_gain=1)
    scheduled=SelectionDecision(station_id=station.id,track=track,playback_bus='A',status='queued',selection_method='music')
    db.session.add(scheduled);db.session.commit()
    observed=status(station)
    assert observed['mixer']['a'] is None and observed['mixer']['b'] is None
    assert observed['current'] is not None
    from app.automation_worker import EventReader,return_to_auto_if_stopped
    reader=EventReader();reader.dj_has_played.add(station.slug)
    assert not return_to_auto_if_stopped(station,reader,snapshot.mixer,now=20)
    assert station.automation.operator_mode=='DJ_BOOTH'


def test_manual_deck_a_and_schedule_use_separate_engine_queues(prepared,monkeypatch):
    from app.services.playout_queue import push_decision
    station,track,user,snapshot=prepared;calls=[]
    monkeypatch.setattr('app.services.playout_queue._command',lambda slug,command:calls.append(command) or '1')
    command=request_deck(station,user,'A','LOAD',track.uuid,str(snapshot.current_decision_id),str(uuid.uuid4()),play_on_load=True)
    push_decision(command.target_decision)
    scheduled=SelectionDecision(station_id=station.id,track=track,playback_bus='A',status='selected',selection_method='music')
    db.session.add(scheduled);db.session.flush();push_decision(scheduled)
    assert calls[0].startswith('freo_a.push ') and calls[1].startswith('freo_queue.push ')


def test_worker_keeps_refilling_schedule_during_dj_standby(prepared,monkeypatch):
    from app import automation_worker as worker
    station,track,user,snapshot=prepared;station.automation.hold=True;db.session.commit()
    mixer=dict(snapshot.mixer,auto_standby=True,auto_id=snapshot.current_decision_id,a_id=None,a_playing=False)
    calls=[]
    monkeypatch.setattr('app.services.playout_queue.sync_mixer',lambda _:mixer)
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:mixer)
    monkeypatch.setattr(worker,'heartbeat',lambda:None)
    monkeypatch.setattr(worker,'process_manual',lambda *args:None)
    monkeypatch.setattr(worker,'observe_queue',lambda *args:None)
    monkeypatch.setattr(worker,'queue_depth',lambda *args:0)
    monkeypatch.setattr(worker,'process_timed_events',lambda *args:None)
    monkeypatch.setattr(worker,'process_block',lambda *args:False)
    monkeypatch.setattr(worker,'refill_station',lambda *args:calls.append(args[0]))
    reader=worker.EventReader();worker.tick(reader)
    assert calls==[station.slug]
    mixer.update(auto_standby=False,a_id=snapshot.current_decision_id,a_playing=True)
    worker.tick(reader)
    assert calls==[station.slug]


def test_auto_standby_engine_observation_is_validated(monkeypatch):
    from app.services.playout_queue import mixer_state
    response='DJ_BOOTH|0.|false|false||||0.|0.||1.|0.|0.|true|42|1.'
    monkeypatch.setattr('app.services.playout_queue._command',lambda *args:response)
    assert mixer_state('test-station')['auto_standby']
    assert mixer_state('test-station')['auto_id']==42
    for response in (response.rsplit('|',1)[0]+'|nan',response.replace('|true|42|','|maybe|42|')):
        with pytest.raises(RuntimeError,match='Auto source'):
            mixer_state('test-station')
