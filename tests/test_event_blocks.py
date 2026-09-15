"""Ordered blocks are station-scoped, snapshotted, and own refill."""
from datetime import datetime, timedelta, timezone
import pytest
from app.extensions import db
from app.models import EventBlock, IMAGING_TYPES, SelectionDecision, Station, Track
from app.services.event_blocks import add_item, create_execution, reorder, save_block, set_enabled
from app.services.timed_events import prepare_decision, save_event
from tests.test_web import app as app_fixture, admin_client

@pytest.fixture
def app(app_fixture): return app_fixture

def make_block(station, track, monkeypatch, name='Top Hour'):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    block=save_block(station.slug,name=name,block_type='STOPSET',failure_policy='ABORT_BLOCK')
    add_item(block,'TRACK',track.uuid,label='First'); add_item(block,'TRACK',track.uuid,label='Second',failure_policy='SKIP_FAILED_ITEM')
    set_enabled(block,True); return block

def test_definition_reorder_snapshot_and_station_scope(app,monkeypatch):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first(); track=Track.query.first(); block=make_block(station,track,monkeypatch)
        assert block.duration_ms==track.duration_ms*2
        ids=[i.id for i in block.items]; reorder(block,reversed(ids)); assert [i.label for i in block.items]==['Second','First']
        run=create_execution(block,'MANUAL',admin_user_id=1); snapshot=[(i.position,i.label,i.failure_policy) for i in run.items]
        block.items[0].label='Changed'; db.session.commit(); assert snapshot==[(1,'Second','SKIP_FAILED_ITEM'),(2,'First','ABORT_BLOCK')]
        other=Station.query.filter_by(slug='second-station').first()
        with pytest.raises(ValueError,match='another station'):
            add_item(EventBlock(station_id=other.id,name='X',slug='x',block_type='GENERIC',failure_policy='ABORT_BLOCK'),'TRACK',track.uuid)

def test_timed_block_exactly_once_and_first_start_confirms_event(app,monkeypatch):
    from app.services.automation import playback_started
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();station.timezone='UTC';track=Track.query.first();block=make_block(station,track,monkeypatch)
        at=datetime.now(timezone.utc)+timedelta(minutes=1)
        event=save_event(station.slug,name='Block Event',timing_mode='HARD',recurrence_type='ONE_TIME',content_type='EVENT_BLOCK',content_identifier=block.slug,local_date=at.date().isoformat(),local_time=at.time().replace(microsecond=0).isoformat(),interrupt_policy='MUSIC_ONLY')
        occurrence=event.occurrences[0]; assert prepare_decision(occurrence) is block; assert occurrence.block_execution is None
        run=create_execution(block,'TIMED_EVENT',occurrence=occurrence); assert create_execution(block,'TIMED_EVENT',occurrence=occurrence).id==run.id
        item=run.items[0]; decision=SelectionDecision(station_id=station.id,track_id=track.id,selection_method='event_block',status='queued',reason='block')
        db.session.add(decision);db.session.flush();item.selection_decision_id=decision.id;item.state='QUEUED';db.session.commit()
        started=occurrence.scheduled_for_utc.replace(tzinfo=timezone.utc)+timedelta(seconds=1)
        assert playback_started(decision.id,station.slug,started); assert run.state=='STARTED' and occurrence.state=='STARTED' and occurrence.timing_offset_seconds==pytest.approx(1)

def test_worker_queues_items_in_order(app,monkeypatch):
    from app.automation_worker import EventReader, process_block
    monkeypatch.setattr('app.automation_worker.reconcile_requests',lambda slug:0);monkeypatch.setattr('app.automation_worker.socket_identity',lambda slug:'sock');monkeypatch.setattr('app.automation_worker.active_ids',lambda slug:set());queued=[]
    monkeypatch.setattr('app.automation_worker.push_decision',lambda decision: queued.append(decision.id) or 99)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();track=Track.query.first();run=create_execution(make_block(station,track,monkeypatch),'MANUAL')
        assert process_block(station,EventReader()) and len(queued)==1
        first=run.items[0];first.selection_decision.status='started';first.state='STARTED';first.started_at=datetime.now(timezone.utc);db.session.commit()
        assert process_block(station,EventReader()) and len(queued)==2; assert [i.position for i in run.items if i.selection_decision_id]==[1,2]

def test_block_admin_auth_csrf_and_idor(app,monkeypatch):
    anonymous=app.test_client();base='/admin/stations/test-station/blocks'
    assert anonymous.get(base).status_code==302 and anonymous.post(base).status_code==302
    client=admin_client(app);assert client.get(base).status_code==200;assert client.post(base).status_code==400
    data={'csrf':'test-admin-csrf-token','name':'Web Stopset','description':'','block_type':'STOPSET','failure_policy':'ABORT_BLOCK'}
    assert client.post(base,data=data).status_code==303
    with app.app_context(): add_item(EventBlock.query.filter_by(slug='web-stopset').one(),'TRACK',Track.query.first().uuid)
    assert client.get(base+'/web-stopset').status_code==200
    assert client.get('/admin/stations/second-station/blocks/web-stopset').status_code==404
    assert client.post(base+'/web-stopset/enable',data={'csrf':'wrong'}).status_code==400; assert client.get(base+'/web-stopset/disable').status_code in (404,405)

def test_commercial_is_first_class_imaging_type(app): assert 'COMMERCIAL' in IMAGING_TYPES
