"""Simple can select a saved Block and loop its format from activation time."""
import copy
import uuid
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models import Station, Track, ChannelSchedule, ScheduleTransition
from app.services import visual_schedule as vs
from tests.test_web import app, admin_client
from tests.test_block_scheduling import seed_block
from tests.test_schedule_autosave import post


def test_simple_block_save_preview_and_explicit_handoff(app):
    client=admin_client(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        block,_=seed_block(station);ref=dict(kind='block',id=block.id,version=1)
        db.session.commit();revision=policy.revision
    result=post(client,'simple',revision=revision,base=None,source=ref)
    assert result.status_code==200,result.json
    saved=result.json['source'];assert saved['kind']=='block' and saved['name']=='Chill Night'
    preview=post(client,'transition-preview',mode='SIMPLE',simple=saved)
    assert preview.status_code==200 and preview.json['playable']
    assert preview.json['program']=='Chill Night' and preview.json['reason'] is None
    with app.app_context():
        policy=ChannelSchedule.query.first()
        assert policy.live_simple is None and policy.mode=='CALENDAR'
        assert policy.assignments==[] and policy.default_playlist_id is None
    response=post(client,'transition',id=str(uuid.uuid4()),current='CALENDAR',mode='SIMPLE',revision=result.json['revision'],simple=saved)
    assert response.status_code==200,response.json
    with app.app_context():
        command=ScheduleTransition.query.one()
        assert command.simple==saved and command.state=='PENDING'
        assert ChannelSchedule.query.first().mode=='CALENDAR'


def test_simple_block_uses_elapsed_time_loops_and_pins_version(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();station.timezone='America/Denver'
        policy=vs.policy(station,True);block,playlist=seed_block(station,end=21600)
        data=vs.composition_json(block)
        data['sections'].append(dict(id='later',start=21600,end=86400,source=dict(kind='song',id=Track.query.first().id)))
        block=vs.save_composition(station,data);db.session.flush()
        ref=vs.source(station,dict(kind='block',id=block.id),allow_block=True)
        began=datetime(2026,9,21,20,30,tzinfo=timezone.utc)
        command=ScheduleTransition(id=str(uuid.uuid4()),station_id=station.id,mode='SIMPLE',previous_mode='CALENDAR',revision=1,state='APPLIED',created_at=began,completed_at=began)
        db.session.add(command);policy.mode='SIMPLE';policy.activated=True;policy.activation=command.id;policy.simple=policy.live_simple=ref;db.session.commit()
        first=vs.resolve_visual(station,began)
        assert first['source']['kind']=='playlist' and first['source']['id']==playlist.id
        assert first['next_transition']==began+timedelta(hours=6)
        assert vs.resolve_visual(station,began+timedelta(hours=6))['source']['kind']=='song'
        repeated=vs.resolve_visual(station,began+timedelta(hours=24))
        assert repeated['source']==first['source'] and repeated['key']!=first['key']
        data=vs.composition_json(block);data['sections']=[];vs.save_composition(station,data)
        policy.revision_updates=[dict(id=block.id,version=block.revision,effective_on='2026-09-22')];db.session.commit();db.session.remove()
        station=Station.query.filter_by(slug='test-station').one()
        after_restart=vs.resolve_visual(station,began+timedelta(hours=24))
        assert after_restart['source']==first['source'] and after_restart['key']==repeated['key']


def test_simple_blocks_reject_foreign_or_invalid_versions(app):
    client=admin_client(app)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();policy=vs.policy(station,True)
        block,_=seed_block(station);ref=dict(kind='block',id=block.id,version=99)
        other=Station.query.filter_by(slug='second-station').one()
        foreign=vs.save_composition(other,dict(kind='BLOCK',name='Foreign',sections=[]));db.session.commit()
        foreign_ref=dict(kind='block',id=foreign.id,version=1);revision=policy.revision
    for source in [ref,foreign_ref]:
        result=post(client,'simple',revision=revision,base=None,source=source)
        assert result.status_code==400
    with app.app_context():assert ChannelSchedule.query.first().simple is None
