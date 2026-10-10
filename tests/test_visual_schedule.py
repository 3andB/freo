"""Mode isolation, recurrence, immutable compositions, and intentional looping."""
import json
import uuid
from datetime import date, datetime, timezone, timedelta
import pytest
from app.extensions import db
from app.models import (Station, Track, Playlist, PlaylistItem, ScheduleCompositionRevision,
                        ScheduleTransition, SelectionDecision, TimedEvent, ChannelSchedule)
from app.services import visual_schedule as vs
from app.services.automation import select_next
from app.services.schedule import resolve
from app.services.programming_refresh import signature
from tests.test_web import app, admin_client


def at(value='2026-09-21T09:30:00'):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def setup():
    station=Station.query.filter_by(slug='test-station').one();track=Track.query.first()
    playlist=Playlist(station_id=station.id,name='Default',mode='STRAIGHT')
    playlist.items.append(PlaylistItem(track_id=track.id,position=1));db.session.add(playlist);db.session.flush()
    p=vs.policy(station,True);p.default_playlist_id=playlist.id;p.activated=True
    db.session.commit();return station,p,dict(kind='song',id=track.id)


def rule(frequency='weekly',**extra):
    return vs.clean_rule(dict(frequency=frequency,anchor='2026-09-21',weekdays=[0,1,2,3,4],**extra))


def test_modes_do_not_leak_and_single_song_loops(app,monkeypatch):
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        s,p,ref=setup();p.calendar=[dict(id='morning',start=9*3600,end=10*3600,rule=rule(),source=ref)]
        p.mode='SIMPLE';p.simple=p.live_simple=ref;db.session.commit()
        a=select_next(s.slug,now=at());b=select_next(s.slug,now=at()+timedelta(seconds=30))
        assert a.track_id==b.track_id==ref['id'] and a.relaxation=='intentional_loop'
        assert resolve(s,at()).visual['mode']=='SIMPLE'
        p.mode='BLOCKS';db.session.commit()
        resolved=resolve(s,at()).visual
        assert resolved['source']['kind']=='playlist' and resolved['reason']=='Nothing scheduled'
        p.mode='CALENDAR';db.session.commit()
        assert resolve(s,at()).visual['source']['kind']=='song'
        assert resolve(s,at('2026-09-21T11:00')).visual['source']['kind']=='playlist'


def test_signature_stable_between_ticks_and_active_simple_requires_handoff(app):
    with app.app_context():
        s,p,ref=setup();p.mode='SIMPLE';p.live_simple=ref;p.simple=dict(kind='playlist',id=p.default_playlist_id);db.session.commit()
        assert resolve(s,at()).visual['source']['kind']=='song'
        assert signature(s,at())==signature(s,at()+timedelta(seconds=2))


def test_immutable_shows_duration_inserts_and_block_cycles(app,monkeypatch):
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        s,p,ref=setup();data=dict(kind='SHOW',name='Study',duration=3600,sections=[dict(id='music',start=0,end=3600,source=ref,inserts=[dict(id='special',at=1800,source=ref)])])
        show=vs.save_composition(s,data);db.session.flush();showref=vs.source(s,dict(kind='show',id=show.id))
        block=vs.save_composition(s,dict(kind='BLOCK',name='Weekday',sections=[dict(id='morning',start=9*3600,end=12*3600,source=showref)]));db.session.flush()
        p.mode='CALENDAR';p.calendar=[dict(id='study',start=9*3600,end=12*3600,rule=rule(),source=showref)];db.session.commit()
        resolved=resolve(s,at()).visual;assert resolved['insert']
        selected=select_next(s.slug,now=at());assert selected.selection_method=='schedule_insert'
        assert not resolve(s,at()).visual['insert']
        assert resolve(s,at('2026-09-21T10:30')).visual['insert']
        vs.save_composition(s,dict(data,id=show.id,revision=1,duration=7200));db.session.commit()
        assert ScheduleCompositionRevision.query.filter_by(composition_id=show.id,version=1).one().duration==3600
        p.mode='BLOCKS';p.assignments=[dict(id='a',rule=rule(),pattern=[vs.source(s,dict(kind='block',id=block.id),allow_block=True)])];db.session.commit()
        assert resolve(s,at('2026-09-21T09:00')).visual['source']['kind']=='song'
        with pytest.raises(ValueError):vs.save_composition(s,dict(data,duration=899))


def test_recurrence_daily_monthly_dates_and_exceptions():
    daily=rule('daily',interval=2);assert vs.matches(daily,date(2026,9,23));assert not vs.matches(daily,date(2026,9,22))
    monthly=vs.clean_rule(dict(frequency='monthly',anchor='2026-01-31',month_day=31))
    assert vs.rule_dates(monthly,date(2026,1,31),3)==['2026-01-31','2026-03-31','2026-05-31']
    last=vs.clean_rule(dict(frequency='monthly',anchor='2026-01-01',nth=-1,weekday=0))
    assert vs.matches(last,date(2026,2,23))
    once=rule('once',exceptions=['2026-09-21']);assert not vs.matches(once,date(2026,9,21))


def test_overlap_cross_midnight_and_station_access(app):
    with app.app_context():
        s,p,ref=setup()
        with pytest.raises(ValueError,match='overlap'):
            vs.clean_document(s,[dict(id='a',start=23*3600,end=26*3600,source=ref,rule=rule('daily')),dict(id='b',start=3600,end=3*3600,source=ref,rule=rule('daily'))])
        other=Station.query.filter_by(slug='second-station').one()
        with pytest.raises(ValueError):vs.source(other,ref)
        with pytest.raises(ValueError):vs.source(s,dict(kind='show',id=999))


def test_api_pagination_csrf_revision_and_transition_confirmation(app):
    client=admin_client(app);base='/admin/stations/test-station/schedule-studio/api/'
    with app.app_context():
        s,p,ref=setup();revision=p.revision
    assert client.post(base+'simple',data={'payload':json.dumps(dict(source=ref,revision=revision))}).status_code==400
    response=client.post(base+'simple',data={'csrf':'test-admin-csrf-token','payload':json.dumps(dict(source=ref,revision=revision))})
    assert response.status_code==200;revision=response.json['revision']
    payload=dict(id=str(uuid.uuid4()),mode='SIMPLE',current='CALENDAR',revision=revision,simple=ref)
    for _ in range(2):
        response=client.post(base+'transition',data={'csrf':'test-admin-csrf-token','payload':json.dumps(payload)});assert response.status_code==200
    with app.app_context():
        assert ScheduleTransition.query.count()==1
        assert ChannelSchedule.query.first().mode=='CALENDAR'
    assert client.get(base+'sources?kind=song&q=Verified').json['items'][0]['id']==ref['id']
    assert client.get(base+'sources?kind=song&page=-1').status_code==400
    assert client.get('/admin/stations/test-station/schedule-studio/simple').status_code==200


def test_hourly_events_generate_one_series_without_duplicates(app):
    from app.services.timed_events import save_event,_instants
    with app.app_context():
        s,p,ref=setup()
        event=save_event(s.slug,name='Hourly ID',timing_mode='SOFT',recurrence_type='WEEKLY',content_type='TRACK',content_identifier=Track.query.first().uuid,
            weekdays=[0],local_time='00:05:00',repeat_hours=[0,1,2,3],starts_on='2026-09-21',ends_on='2026-09-21')
        times=_instants(event,at('2026-09-21T00:00'),at('2026-09-22T00:00'))
        assert len(times)==4 and len(set(times))==4
        assert {t.minute for t in times}=={5}


def test_nested_show_insert_is_once_per_cycle_and_key_is_bounded(app,monkeypatch):
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        s,p,ref=setup()
        show=vs.save_composition(s,dict(kind='SHOW',name='Nested',duration=3600,sections=[dict(id=str(uuid.uuid4()),start=0,end=3600,source=ref,inserts=[dict(id=str(uuid.uuid4()),at=1800,source=ref)])]));db.session.flush()
        block=vs.save_composition(s,dict(kind='BLOCK',name='Full day',sections=[dict(id=str(uuid.uuid4()),start=0,end=86400,source=vs.source(s,dict(kind='show',id=show.id)))]));db.session.flush()
        p.mode='BLOCKS';p.assignments=[dict(id=str(uuid.uuid4()),rule=rule(),pattern=[vs.source(s,dict(kind='block',id=block.id),allow_block=True)])];db.session.commit()
        resolved=resolve(s,at()).visual;assert resolved['insert'] and len(resolved['key'])<=120
        select_next(s.slug,now=at())
        assert not resolve(s,at()).visual['insert']
        assert resolve(s,at('2026-09-21T10:30')).visual['insert']


def test_migration_upgrade_and_downgrade_are_isolated():
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path='migrations/versions/ab92e51c7034_visual_scheduling.py'
    spec=importlib.util.spec_from_file_location('migration',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=sa.create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        for table in ('stations','playlists','selection_decisions','timed_events'):
            connection.exec_driver_sql(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
        connection.exec_driver_sql('CREATE TABLE tracks (id INTEGER PRIMARY KEY, title VARCHAR(200))')
        context=MigrationContext.configure(connection)
        with Operations.context(context):migration.upgrade()
        tables=sa.inspect(connection).get_table_names();assert 'channel_schedules' in tables and 'schedule_transitions' in tables
        assert 'repeat_hours' in {c['name'] for c in sa.inspect(connection).get_columns('timed_events')}
        with Operations.context(context):migration.downgrade()
        assert set(sa.inspect(connection).get_table_names())=={'stations','playlists','selection_decisions','timed_events','tracks'}


def test_source_search_is_paginated(app):
    with app.app_context():
        s,p,ref=setup()
        for i in range(90):
            db.session.add(Playlist(station_id=s.id,name=f'Collection {i:03}',mode='STRAIGHT'))
        db.session.commit()
        first=vs.search_sources(s,'playlist','Collection',1);second=vs.search_sources(s,'playlist','Collection',2)
        assert len(first['items'])==len(second['items'])==40 and first['more'] and second['more']
        assert not {r['id'] for r in first['items']} & {r['id'] for r in second['items']}


@pytest.mark.parametrize('before,after',[(a,b) for a in vs.MODES for b in vs.MODES if a!=b])
def test_all_six_mode_handoffs_acknowledge_before_effective_change(app,monkeypatch,before,after):
    from app.services import schedule_switch as switch
    from app.automation_worker import EventReader
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    monkeypatch.setattr(switch,'queued_ids',lambda slug:set())
    monkeypatch.setattr(switch,'active_ids',lambda slug:set())
    monkeypatch.setattr(switch,'socket_identity',lambda slug:'isolated')
    monkeypatch.setattr(switch,'push_decision',lambda decision:99)
    monkeypatch.setattr(EventReader,'collect',lambda *a:0)
    phase=['FADING'];monkeypatch.setattr(switch,'_command',lambda *a:phase[0])
    with app.app_context():
        s,p,ref=setup();p.mode=before;p.simple=p.live_simple=ref;db.session.commit()
        command=vs.transition_request(s,dict(id=str(uuid.uuid4()),mode=after,current=before,revision=p.revision,simple=ref));db.session.commit()
        assert switch.process_transition(s,EventReader()) and p.mode==before
        phase[0]='APPLIED';command.decision.status='started';command.decision.started_at=at();db.session.commit()
        assert switch.process_transition(s,EventReader()) and p.mode==after
        assert command.state=='APPLIED'
        assert not switch.process_transition(s,EventReader())


def test_future_revision_application_preserves_today_and_simple(app):
    with app.app_context():
        s,p,ref=setup()
        show=vs.save_composition(s,dict(kind='SHOW',name='Versioned',duration=3600,sections=[dict(id='a',start=0,end=3600,source=ref)]));db.session.flush()
        original=vs.source(s,dict(kind='show',id=show.id))
        p.calendar=[dict(id='versioned',start=0,end=86400,source=original,rule=rule('daily'))]
        first_key=resolve(s,at()).visual['key']
        vs.save_composition(s,dict(id=show.id,revision=show.revision,kind='SHOW',name='Versioned',duration=7200,sections=[dict(id='b',start=0,end=7200,source=ref)]));db.session.flush()
        p.revision_updates=[dict(id=show.id,version=2,effective_on='2026-09-22')];db.session.commit()
        assert resolve(s,at()).visual['key']==first_key
        assert resolve(s,at('2026-09-22T09:30')).visual['source']['id']==ref['id']
        p.mode='SIMPLE';p.live_simple=original;db.session.commit()
        assert resolve(s,at('2026-09-22T09:30')).visual['source']['id']==ref['id']


def test_cursor_restore_only_rewinds_the_removed_selection(app,monkeypatch):
    from app.models import ScheduleCursor
    from app.services.programming_refresh import restore
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        s,p,ref=setup();p.mode='SIMPLE';p.simple=p.live_simple=ref;db.session.commit()
        unrelated=ScheduleCursor(station_id=s.id,key='unrelated',state={'last':123});db.session.add(unrelated);db.session.commit()
        chosen=select_next(s.slug,now=at())
        assert chosen.cursor_checkpoint['visual']
        restore(s,chosen.cursor_checkpoint)
        key=next(iter(chosen.cursor_checkpoint['visual']))
        assert db.session.get(ScheduleCursor,(s.id,key)).state=={}
        assert unrelated.state=={'last':123}


def test_legacy_calendar_preserves_overnight_coverage_for_370_days(app):
    from app.models import ScheduleAssignment, Clock
    from app.services.calendar import create_program
    from app.routes.schedule_studio import legacy_calendar
    from datetime import time
    with app.app_context():
        s,p,ref=setup();p.activated=False
        baseline=Clock.query.filter_by(station_id=s.id).first()
        db.session.add(ScheduleAssignment(station_id=s.id,clock_id=baseline.id,weekday=6,start_time=time(20),enabled=True))
        create_program(s,name='Sunday overnight',weekdays=['6'],start='23:00',end='02:00',category_slug='power')
        db.session.commit()
        document=vs.clean_document(s,legacy_calendar(s))
        begin=at('2026-09-20T00:00')
        for day in range(370):
            for hour in (0,1,2,19,20,23):
                now=begin+timedelta(days=day,hours=hour)
                old=resolve(s,now)
                p.calendar=document;p.activated=True
                new=resolve(s,now)
                p.activated=False
                assert new.clock.id==old.clock.id,(now,new,old)


def test_visual_boundaries_wake_at_both_dst_changes():
    from zoneinfo import ZoneInfo
    zone=ZoneInfo('America/New_York')
    spring=at('2026-03-08T06:30')
    fall=at('2026-11-01T05:30')
    assert vs.wall_boundary(spring,spring.astimezone(zone),5400)==at('2026-03-08T07:00')
    assert vs.wall_boundary(fall,fall.astimezone(zone),5400)==at('2026-11-01T06:00')
    second_fold=at('2026-11-01T06:30')
    assert vs.wall_boundary(second_fold,second_fold.astimezone(zone),1800)==at('2026-11-01T07:00')


def test_first_calendar_activation_uses_visible_legacy_import(app):
    client=admin_client(app);base='/admin/stations/test-station/schedule-studio/api/'
    preview=client.post(base+'transition-preview',data={'csrf':'test-admin-csrf-token','payload':json.dumps(dict(mode='CALENDAR'))})
    assert preview.status_code==200 and preview.json['playable']
    assert preview.json['source']['kind']=='legacy'
    with app.app_context():assert ChannelSchedule.query.count()==0
    payload=dict(id=str(uuid.uuid4()),mode='CALENDAR',current='CALENDAR',revision=1)
    response=client.post(base+'transition',data={'csrf':'test-admin-csrf-token','payload':json.dumps(payload)})
    assert response.status_code==200
    with app.app_context():
        p=ChannelSchedule.query.one();assert p.calendar_saved and p.calendar
        assert not p.activated and ScheduleTransition.query.one().state=='PENDING'
