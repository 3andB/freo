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


def test_stale_request_and_duplicate_click_cannot_control_new_song(prepared,monkeypatch):
    station,track,user,snapshot=prepared;nonce=str(uuid.uuid4())
    command=request_deck(station,user,'A','CLEAR',None,str(snapshot.current_decision_id),nonce)
    assert request_deck(station,user,'A','CLEAR',None,str(snapshot.current_decision_id),nonce).id==command.id
    with pytest.raises(ValueError,match='still being applied'):
        request_deck(station,user,'B','LOAD',track.uuid,'',str(uuid.uuid4()))
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda _:dict(snapshot.mixer,a_id=9999))
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *args:[])
    with pytest.raises(ValueError,match='Deck changed'):
        process_deck_command(station,command,'engine')


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
