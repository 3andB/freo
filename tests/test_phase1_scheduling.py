"""Phase 1 follows the existing occurrence, history, and cursor contracts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import importlib.util
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.extensions import db
from app import models as m
from app.services import playlists, smart_playlists
from app.services.automation import select_next, playback_started
from app.services.selection_policy import eligible, recent
from app.services.programming_refresh import signature, checkpoint, restore
from app.services.visual_schedule import select_visual, source_tracks
from app.services.media_storage import LocalMediaStorage
from tests.test_web import app, admin_client
from tests.test_playlists import setup_playlist, program
from tests.test_sound_room import action

AT = datetime(2026, 9, 16, 9, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def files(monkeypatch):
    monkeypatch.setattr(LocalMediaStorage, 'regular_file', lambda *a: '/safe')


def started(station, track, at=AT, **kwargs):
    row=m.SelectionDecision(station_id=station.id,track=track,status='started',started_at=at,
                            selected_at=at-timedelta(days=2),**kwargs)
    db.session.add(row);db.session.flush()
    return row


@pytest.mark.parametrize('mode',['STRAIGHT','RANDOM'])
def test_leader_retry_confirm_restart_refresh_and_new_occurrence(app, mode):
    with app.app_context():
        station,row,songs=setup_playlist();row.mode=mode;row.leader_track=songs[-1]
        playlists.replace_order(row,[s.id for s in songs[:-1]])
        program(station,row,AT);program(station,row,AT+timedelta(days=1));db.session.commit()
        leader=select_next(station.slug,now=AT)
        assert leader.selection_method=='playlist_leader' and leader.track_id==songs[-1].id
        assert m.PlaylistCursor.query.count()==0
        assert select_next(station.slug,now=AT) is None
        leader.status='failed';leader.reason='queue_failed';db.session.commit()
        retry=select_next(station.slug,now=AT)
        assert retry.id!=leader.id and retry.leader_key==leader.leader_key
        assert playback_started(retry.id,station.slug,AT)
        saved=checkpoint(station)
        first=select_next(station.slug,now=AT)
        assert first.selection_method=='playlist'
        restore(station,saved);db.session.commit()
        assert select_next(station.slug,now=AT).selection_method=='playlist'
        slug=station.slug;leader_id=songs[-1].id;leader_key=retry.leader_key
        db.session.remove()
        assert select_next(slug,now=AT).selection_method=='playlist'
        next_day=select_next(slug,now=AT+timedelta(days=1))
        assert next_day.selection_method=='playlist_leader' and next_day.track_id==leader_id
        assert next_day.leader_key!=leader_key


def test_visual_leader_occurrences_keep_shuffle_cycle(app):
    with app.app_context():
        station,row,songs=setup_playlist();row.mode='RANDOM';row.leader_track=songs[-1]
        playlists.replace_order(row,[s.id for s in songs[:-1]]);db.session.commit()
        ref=dict(kind='playlist',id=row.id)
        resolved=dict(source=ref,key='activation-one')
        leader=select_visual(station,resolved,LocalMediaStorage(),AT);db.session.commit()
        assert select_visual(station,resolved,LocalMediaStorage(),AT) is None
        playback_started(leader.id,station.slug,AT)
        first=select_visual(station,resolved,LocalMediaStorage(),AT);db.session.commit()
        saved=dict(m.ScheduleCursor.query.one().state)
        resolved['key']='activation-two'
        second_leader=select_visual(station,resolved,LocalMediaStorage(),AT);db.session.commit()
        assert second_leader.selection_method=='playlist_leader'
        assert m.ScheduleCursor.query.one().state==saved
        playback_started(second_leader.id,station.slug,AT)
        second=select_visual(station,resolved,LocalMediaStorage(),AT)
        assert first.track_id!=second.track_id


def test_unavailable_leader_is_visible_and_does_not_start_late(app):
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1];songs[-1].enabled=False
        program(station,row,AT);db.session.commit()
        assert select_next(station.slug,now=AT).track_id==songs[0].id
        failure=m.SelectionDecision.query.filter_by(reason='playlist_leader_unavailable').one()
        assert failure.status=='failed' and failure.started_at is None
        songs[-1].enabled=True;db.session.commit()
        assert select_next(station.slug,now=AT).selection_method=='playlist'


def test_station_audio_leader_and_delete_cleanup(app):
    from app.services.audio_classification import classify
    from app.services.music_delete import remove_references
    with app.app_context():
        station,row,songs=setup_playlist();classify(songs[-1],'STATION')
        playlists.configure(row,dict(leader_track_id=songs[-1].id));db.session.commit()
        assert playlists.leader_track(row).audio_kind=='STATION'
        remove_references(songs[-1]);db.session.flush()
        assert row.leader_track_id is None


@pytest.mark.parametrize('path',['playlist','visual','category'])
def test_separation_shared_paths_use_start_time_and_pending_holds(app,path):
    with app.app_context():
        station,row,songs=setup_playlist();station.automation.artist_separation_seconds=600;station.automation.track_separation_seconds=600
        songs[1].artist='  TEST   ARTIST '
        started(station,songs[0]);db.session.commit()
        if path=='playlist':
            program(station,row,AT);db.session.commit();chosen=select_next(station.slug,now=AT)
        elif path=='visual':
            chosen=select_visual(station,dict(source=dict(kind='playlist',id=row.id),key='one'),LocalMediaStorage(),AT)
        else:
            from app.services.automation import _select_category
            category=songs[0].categories[0];category.tracks=list(songs)
            chosen=_select_category(station,category,station.automation,LocalMediaStorage(),AT,{})
        assert chosen.track_id==songs[2].id and chosen.relaxation=='none'
        chosen.status='submitting';db.session.flush()
        pool,relaxation,_=eligible(songs,recent(station,station.automation,AT),AT,600,600)
        assert [s.id for s in pool]==[songs[3].id]


def test_separation_boundary_failed_cross_station_blank_artist_and_fallback(app):
    with app.app_context():
        station,row,songs=setup_playlist();songs[0].artist=songs[1].artist=''
        started(station,songs[0],AT-timedelta(seconds=600))
        pool,relaxation,_=eligible(songs[:2],recent(station,station.automation,AT),AT,600,600)
        assert len(pool)==2 and relaxation=='none'
        started(station,songs[0]);songs[1].artist=songs[0].artist='Same'
        pool,relaxation,_=eligible(songs[:2],recent(station,station.automation,AT),AT,600,600)
        assert pool==[songs[1]] and relaxation=='artist'
        started(station,songs[1]);db.session.flush()
        pool,relaxation,_=eligible(songs[:2],recent(station,station.automation,AT),AT,600,600)
        assert len(pool)==2 and relaxation=='track'
        other=m.Station.query.filter_by(slug='second-station').one()
        failed=started(station,songs[2]);failed.status='failed'
        started(other,songs[3]);db.session.flush()
        pool,relaxation,_=eligible(songs[2:],recent(station,station.automation,AT),AT,600,600)
        assert len(pool)==2 and relaxation=='none'


def test_smart_membership_live_metadata_filters_availability_and_signature(app):
    with app.app_context():
        station,row,songs=setup_playlist();tag=m.MusicTag(station_id=station.id,name='Night',slug='night');db.session.add(tag);db.session.flush()
        songs[1].genre='Jazz';songs[1].bpm=120;songs[1].release_year=2001;songs[1].tags=[tag]
        playlists.configure(row,dict(smart_enabled=True,smart_rules={'genre':'jazz','bpm':{'min':100,'max':130},'release_year':{'min':2000},'tags':[tag.id]}));db.session.commit()
        assert playlists.playable_tracks(row,station.id)==[songs[1]]
        before=signature(station,AT)
        songs[2].genre='JAZZ';songs[2].bpm=110;songs[2].release_year=2002;songs[2].tags=[tag];db.session.commit()
        assert signature(station,AT)!=before
        assert source_tracks(station,dict(kind='playlist',id=row.id))==songs[1:3]
        songs[1].enabled=False;db.session.commit()
        assert playlists.playable_tracks(row,station.id)==[songs[2]]
        before=signature(station,AT);songs[2].tags=[];db.session.commit()
        assert signature(station,AT)!=before and not playlists.playable_tracks(row,station.id)
        assert len(row.items)==4  # Static membership is retained when switching back.


def test_weighted_shuffle_preserves_cycle_and_default_choice(app,monkeypatch):
    with app.app_context():
        station,row,songs=setup_playlist();row.mode='RANDOM'
        category=songs[0].categories[0]
        row.selection_weights={'categories':{str(category.id):8}}
        observed=[]
        def choices(pool,weights,k):
            observed.append(weights);return [pool[weights.index(max(weights))]]
        monkeypatch.setattr(smart_playlists.random,'choices',choices)
        saved={};picks=[]
        for _ in songs:
            track,saved=playlists.advance(row,songs,saved);picks.append(track.id)
        assert observed[0]==[8,1,1,1] and len(set(picks))==4
        row.selection_weights={}
        monkeypatch.setattr(smart_playlists.random,'choice',lambda pool:pool[-1])
        assert playlists.advance(row,songs,{})[0]==songs[-1]


@pytest.mark.parametrize('data',[
    {'smart_rules':{'sql':'DROP'}}, {'smart_rules':{'bpm':{'min':130,'max':100}}},
    {'smart_rules':{'tags':[True]}}, {'smart_rules':{'genre':[]}},{'smart_enabled':'yes'},
    {'selection_weights':{'tags':{'1':0}}}, {'selection_weights':{'categories':{'1':float('nan')}}},
    {'leader_track_id':True}, {'leader_track_id':99999},
])
def test_invalid_config_is_rejected_atomically(app,data):
    client=admin_client(app)
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id;revision=row.revision
    response=action(client,'edit-playlist',dict(id=identifier,revision=revision,name='Must roll back',**data))
    assert response.status_code==409
    with app.app_context():
        row=db.session.get(m.Playlist,identifier)
        assert row.name!='Must roll back' and row.revision==revision


def test_editor_api_smart_catalog_separation_scope_and_csrf(app):
    client=admin_client(app)
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id;revision=row.revision
        other=m.Station.query.filter_by(slug='second-station').one()
        tag=m.MusicTag(station_id=other.id,name='Private',slug='private');db.session.add(tag);db.session.commit();tag_id=tag.id
    assert action(client,'edit-playlist',dict(id=identifier,revision=revision,name='Smart',smart_rules={'tags':[tag_id]})).status_code==409
    assert action(client,'edit-playlist',dict(id=identifier,revision=revision,name='Smart',smart_enabled=True,smart_rules={'title':'Song 2'})).status_code==200
    detail=client.get(f'/admin/api/stations/test-station/playlists/{identifier}').json
    assert detail['smart_enabled'] and detail['count']==1 and detail['songs'][0]['title']=='Song 2'
    assert action(client,'separation',dict(track_seconds=300,artist_seconds=600)).status_code==200
    assert action(client,'separation',dict(track_seconds=True,artist_seconds=600)).status_code==409
    assert client.post('/admin/api/stations/test-station/music/actions/separation',data={'data':'{}'}).status_code==400
    assert client.get('/admin/api/stations/test-station/playlists').json['separation']==dict(track_seconds=300,artist_seconds=600)
    assert client.get('/admin/api/stations/second-station/playlists').json['separation']==dict(track_seconds=0,artist_seconds=0)


def test_timed_snapshot_leader_does_not_commit_member_cursor(app):
    from app.services.timed_events import save_event
    from app.services.event_blocks import create_playlist_execution, prepare_next
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1];row.smart_enabled=True;row.smart_rules={'title':'Song 2'};db.session.commit()
        event=save_event(station.slug,name='Smart event',recurrence_type='DAILY',content_type='PLAYLIST',content_identifier=row.id,local_time='12:00',playlist_playback='ONE')
        occurrence=event.occurrences[-1];execution=create_playlist_execution(occurrence);db.session.commit()
        assert [i.track_id for i in execution.items]==[songs[-1].id,songs[1].id]
        assert create_playlist_execution(occurrence).id==execution.id
        first=prepare_next(execution);playback_started(first.selection_decision_id,station.slug,AT)
        assert event.playlist_state=={}
        second=prepare_next(execution);playback_started(second.selection_decision_id,station.slug,AT)
        assert event.playlist_state['last']==songs[1].id


def test_additive_migration_roundtrip_preserves_existing_data(tmp_path):
    engine=sa.create_engine(f'sqlite:///{tmp_path}/migration.sqlite')
    spec=importlib.util.spec_from_file_location('phase1_migration','migrations/versions/f106a1b2c3d4_smart_playlists.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE tracks (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE playlists (id INTEGER PRIMARY KEY, name TEXT NOT NULL)'))
        connection.execute(sa.text('CREATE TABLE selection_decisions (id INTEGER PRIMARY KEY, status TEXT)'))
        connection.execute(sa.text("INSERT INTO playlists VALUES (1,'Existing')"))
        connection.execute(sa.text("INSERT INTO selection_decisions VALUES (1,'started')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            row=connection.execute(sa.text('SELECT name,leader_track_id,smart_enabled,smart_rules,selection_weights FROM playlists')).one()
            assert tuple(row)==('Existing',None,0,'{}','{}')
            migration.downgrade();migration.upgrade()
            assert connection.execute(sa.text('SELECT status FROM selection_decisions')).scalar()=='started'
    engine.dispose()


def test_worker_pending_leader_does_not_trigger_starvation_backoff(app,monkeypatch):
    from app import automation_worker as worker
    monkeypatch.setattr(worker,'reconcile_requests',lambda slug:None)
    monkeypatch.setattr(worker,'queue_depth',lambda slug:1)
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1];program(station,row,AT);db.session.commit()
        leader=select_next(station.slug,now=AT);leader.status='queued';db.session.commit()
        monkeypatch.setattr(worker,'select_next',lambda slug:select_next(slug,now=AT))
        reader=SimpleNamespace(collect=lambda slug:None,starved_until={})
        assert worker.refill_station(station.slug,reader)==0
        assert not reader.starved_until


def test_refresh_replaces_queued_leader_but_never_confirmed_leader(app,monkeypatch):
    from tests.test_programming_refresh import fake_engine
    from app.services.programming_refresh import refresh
    from app.automation_worker import EventReader
    from app.services.calendar import create_program
    queued={12};fake_engine(monkeypatch,queued,set())
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1]
        at=datetime.now(timezone.utc)
        create_program(station,name='All day',weekdays=[],on_date=at.date().isoformat(),start='00:00',end='00:00',playlist_id=row.id)
        db.session.commit()
        leader=select_next(station.slug,now=at);leader.status='queued';leader.socket_identity='test-engine';leader.liquidsoap_request_id=12;db.session.commit()
        row.description='Refresh';db.session.commit()
        assert refresh(station,EventReader(),signature(station,at))
        assert leader.status=='failed' and not queued
        replacement=select_next(station.slug,now=at)
        assert replacement.selection_method=='playlist_leader' and replacement.leader_key==leader.leader_key
        playback_started(replacement.id,station.slug,at)
        assert select_next(station.slug,now=at).selection_method=='playlist'


def test_smart_rules_literal_text_and_shared_library_scope(app):
    with app.app_context():
        station,row,songs=setup_playlist();row.smart_enabled=True;row.smart_rules={'title':'100%_'}
        songs[1].title='100%_ literal';songs[2].title='10000 different'
        other=m.Station.query.filter_by(slug='second-station').one();songs[1].station_id=other.id;db.session.commit()
        assert playlists.playable_tracks(row,station.id)==[]
        songs[1].available_to_all=True;db.session.commit()
        assert playlists.playable_tracks(row,station.id)==[songs[1]]
        songs[1].audio_kind='STATION';db.session.commit()
        assert playlists.playable_tracks(row,station.id)==[]


def test_preview_includes_leader_policy_without_writing(app):
    from app.services.clocks import preview_clock
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1];station.automation.track_separation_seconds=600
        program_row=program(station,row,AT);db.session.commit()
        before=checkpoint(station);decisions=m.SelectionDecision.query.count()
        result=preview_clock(station.slug,program_row.clock.slug,count=3,at=AT)
        assert result[0]['track']==songs[-1].uuid and result[1]['track']==songs[0].uuid
        assert checkpoint(station)==before and m.SelectionDecision.query.count()==decisions


def test_empty_playlist_leader_then_existing_fallback(app):
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1];program(station,row,AT)
        playlists.replace_order(row,[]);db.session.commit()
        leader=select_next(station.slug,now=AT)
        assert leader.selection_method=='playlist_leader'
        playback_started(leader.id,station.slug,AT)
        fallback=select_next(station.slug,now=AT)
        assert fallback.track_id==songs[0].id and fallback.selection_method=='music'


def test_smart_playlist_searches_show_dynamic_counts(app):
    from app.services.event_search import search
    from app.services.visual_schedule import search_sources
    with app.app_context():
        station,row,songs=setup_playlist();playlists.replace_order(row,[])
        row.smart_enabled=True;row.smart_rules={'title':'Song'};db.session.commit()
        event=next(i for i in search(station,kind='PLAYLIST')['items'] if i['identifier']==str(row.id))
        visual=next(i for i in search_sources(station,'playlist')['items'] if i['id']==row.id)
        assert event['count']==visual['count']==3 and event['playable']
        assert next(i for i in playlists.summaries(station.id) if i['id']==row.id)['count']==3


def test_cross_station_and_commercial_leaders_are_rejected(app):
    with app.app_context():
        station,row,songs=setup_playlist();other=m.Station.query.filter_by(slug='second-station').one()
        songs[-1].station_id=other.id;db.session.commit()
        with pytest.raises(ValueError):playlists.configure(row,{'leader_track_id':songs[-1].id})
        songs[-1].available_to_all=True;db.session.commit()
        playlists.configure(row,{'leader_track_id':songs[-1].id})
        songs[-1].audio_kind='STATION';db.session.commit()
        with pytest.raises(ValueError):playlists.configure(row,{'leader_track_id':songs[-1].id})
        songs[-1].station_id=station.id;songs[-1].audio_kind='COMMERCIALS';db.session.commit()
        with pytest.raises(ValueError):playlists.configure(row,{'leader_track_id':songs[-1].id})
