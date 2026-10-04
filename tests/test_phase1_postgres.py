"""Phase 1 migration preservation and actual PostgreSQL selector serialization."""
import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
import sqlalchemy as sa
from app import create_app, models as m
from app.extensions import db
from app.services.automation import select_next, playback_started
from app.services.visual_schedule import policy
from tests.test_schedule_postgres import pg_app

pytestmark=pytest.mark.skipif(not os.getenv('FREO_TEST_POSTGRES_URL'),reason='Requires disposable PostgreSQL')


def test_phase1_upgrade_defaults_downgrade_and_fk_preserve_history(monkeypatch):
    monkeypatch.setenv('DATABASE_URL',os.environ['FREO_TEST_POSTGRES_URL'])
    monkeypatch.setenv('FREO_ENV_FILE','/dev/null');monkeypatch.setenv('SECRET_KEY','phase1-only')
    app=create_app('testing');runner=app.test_cli_runner()
    result=runner.invoke(args=['db','upgrade','c83d4e5f9012'])
    assert result.exit_code==0,result.output
    with app.app_context():
        db.session.execute(sa.text("INSERT INTO stations (id,name,slug,description,enabled,desired_state,timezone,target_lufs,freo_station_id,created_at,updated_at) VALUES (1,'Old station','old-station','',true,'stopped','UTC',-16,'11111111-1111-4111-8111-111111111111',now(),now())"))
        db.session.execute(sa.text("INSERT INTO playlists (id,station_id,name,description,mode,revision) VALUES (1,1,'Existing playlist','Keep me','RANDOM',7)"))
        db.session.execute(sa.text("INSERT INTO selection_decisions (id,station_id,selected_at,started_at,status,candidate_count,relaxation,reason) VALUES (1,1,now(),now(),'started',2,'none','Existing history')"))
        db.session.commit()
    result=runner.invoke(args=['db','upgrade'])
    assert result.exit_code==0,result.output
    with app.app_context():
        row=db.session.get(m.Playlist,1)
        assert row.name=='Existing playlist' and row.description=='Keep me' and row.revision==7
        assert not row.smart_enabled and row.smart_rules==row.selection_weights=={} and row.leader_track_id is None
        assert db.session.get(m.SelectionDecision,1).reason=='Existing history'
        from tests.test_music_delete import add_song
        song=add_song(db.session.get(m.Station,1));row.leader_track=song;db.session.commit()
        db.session.delete(song);db.session.commit();db.session.expire_all()
        assert row.leader_track_id is None
    result=runner.invoke(args=['db','downgrade','c83d4e5f9012'])
    assert result.exit_code==0,result.output
    result=runner.invoke(args=['db','upgrade'])
    assert result.exit_code==0,result.output
    with app.app_context():
        assert db.session.get(m.Playlist,1).revision==7
        assert db.session.get(m.SelectionDecision,1).status=='started'


def test_concurrent_selectors_issue_one_leader_then_continue(pg_app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    with pg_app.app_context():
        station=m.Station.query.one();leader=m.Track.query.one()
        from tests.test_music_delete import add_song
        member=add_song(station,2)
        row=m.Playlist(station_id=station.id,name='Concurrent',leader_track=leader,items=[m.PlaylistItem(position=1,track=member)])
        db.session.add(row);db.session.flush()
        schedule=policy(station);schedule.mode='SIMPLE';schedule.activated=True;schedule.simple=schedule.live_simple={'kind':'playlist','id':row.id};schedule.activation='review'
        db.session.commit();member_id=member.id
    barrier=Barrier(2)
    at=datetime.now(timezone.utc)
    def select(_):
        with pg_app.app_context():
            barrier.wait(timeout=10)
            result=select_next('test-station',now=at)
            return result.id if result else None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(select,range(2)))
    assert sum(value is not None for value in results)==1
    with pg_app.app_context():
        leader=m.SelectionDecision.query.filter_by(selection_method='playlist_leader').one()
        playback_started(leader.id,'test-station',at)
        assert select_next('test-station',now=at).track_id==member_id


def test_postgres_dynamic_filters_use_real_metadata_and_availability(pg_app):
    from app.services.playlists import configure, playable_tracks
    with pg_app.app_context():
        station=m.Station.query.one();song=m.Track.query.one()
        song.genre='JAZZ';song.bpm=120;song.release_year=2000;song.title='100%_ Match'
        tag=m.MusicTag(station_id=station.id,name='Night',slug='night');song.tags=[tag]
        category=m.MediaCategory(station_id=station.id,name='Power',slug='power',tracks=[song])
        row=m.Playlist(station_id=station.id,name='PG Smart');db.session.add_all([tag,category,row]);db.session.flush()
        configure(row,dict(smart_enabled=True,smart_rules={'genre':'jazz','title':'100%_',
            'bpm':{'min':120,'max':120},'release_year':{'min':2000},'tags':[tag.id],'categories':[category.id]},
            selection_weights={'tags':{str(tag.id):3}}))
        db.session.commit()
        assert playable_tracks(row,station.id)==[song]
        song.enabled=False;db.session.commit()
        assert playable_tracks(row,station.id)==[]
