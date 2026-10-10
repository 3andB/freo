"""Regression cases identified in the independent Phase 1 completion review."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from app import models as m
from app.extensions import db
from app.services.automation import select_next
from tests.test_web import app
from tests.test_playlists import setup_playlist, program


def inventory(monkeypatch, requests, *, complete=True):
    from app import automation_worker as worker
    monkeypatch.setattr(worker,'socket_identity',lambda slug:'review-engine')
    monkeypatch.setattr(worker,'queued_ids',lambda slug:set(requests))
    monkeypatch.setattr(worker,'active_ids',lambda slug:set())
    monkeypatch.setattr(worker,'request_decision_id',lambda slug,rid:requests[rid])
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *a:[])
    def command(*args):
        if not complete: raise OSError('Incomplete inventory')
        return ''
    monkeypatch.setattr('app.services.playout_queue._command',command)
    return worker


@pytest.mark.parametrize('status',['selected','submitting','failed'])
@pytest.mark.parametrize('accepted',[False,True])
def test_leader_crash_window_reconciles_without_programming_change(app,monkeypatch,status,accepted):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist();row.leader_track=songs[-1];program(station,row,at);db.session.commit()
        leader=select_next(station.slug,now=at)
        leader.status=status;leader.reason='queue_failed' if status=='failed' else '';db.session.commit()
        requests={77:leader.id} if accepted else {}
        worker=inventory(monkeypatch,requests)
        tick=[100.0];monkeypatch.setattr(worker.time,'monotonic',lambda:tick[0])
        worker.reconcile_requests(station.slug)
        if accepted:
            assert leader.status=='queued' and leader.liquidsoap_request_id==77
            assert leader.started_at is None
            assert select_next(station.slug,now=at) is None
        else:
            tick[0]+=11
            worker.reconcile_requests(station.slug)
            assert leader.status=='failed'
            retry=select_next(station.slug,now=at)
            assert retry is not None and retry.id!=leader.id and retry.leader_key==leader.leader_key


def test_incomplete_inventory_cannot_fail_untracked_leader(app,monkeypatch):
    with app.app_context():
        station,row,songs=setup_playlist()
        leader=m.SelectionDecision(station_id=station.id,track_id=songs[0].id,selection_method='playlist_leader',status='selected',leader_key='a'*64)
        db.session.add(leader);db.session.commit()
        worker=inventory(monkeypatch,{},complete=False)
        tick=[100.0];monkeypatch.setattr(worker.time,'monotonic',lambda:tick[0])
        worker.reconcile_requests(station.slug);tick[0]+=20;worker.reconcile_requests(station.slug)
        assert leader.status=='selected'


def test_pending_leader_uses_existing_fast_worker_cadence(app):
    from app.automation_worker import EventReader, worker_delay
    with app.app_context():
        station,row,songs=setup_playlist()
        leader=m.SelectionDecision(station_id=station.id,track_id=songs[0].id,selection_method='playlist_leader',status='queued')
        db.session.add(leader);db.session.commit()
        assert worker_delay(EventReader())==.25
        leader.status='started';db.session.commit()
        assert worker_delay(EventReader())==2


@pytest.mark.parametrize('rules',[
    {'artist':'Match Artist'},{'title':'Match Title'},{'album':'Match Album'},{'genre':'Match Genre'},
    {'bpm':{'min':120,'max':120}},{'release_year':{'min':1999,'max':1999}},
    {'duration_ms':{'min':12345,'max':12345}},'category','tag',
])
def test_each_supported_smart_rule_matches_current_metadata(app,rules):
    from app.services.playlists import configure, playable_tracks
    with app.app_context():
        station,row,songs=setup_playlist();target=songs[1]
        target.artist='Match Artist';target.title='Match Title';target.album='Match Album';target.genre='Match Genre'
        target.bpm=120;target.release_year=1999;target.duration_ms=12345
        if rules=='category':
            category=m.MediaCategory(station_id=station.id,name='Review category',slug='review-category',tracks=[target]);db.session.add(category);db.session.flush()
            rules={'categories':[category.id]}
        elif rules=='tag':
            tag=m.MusicTag(station_id=station.id,name='Review tag',slug='review-tag');target.tags=[tag];db.session.add(tag);db.session.flush()
            rules={'tags':[tag.id]}
        configure(row,{'smart_enabled':True,'smart_rules':rules});db.session.commit()
        assert playable_tracks(row,station.id)==[target]
        target.enabled=False;db.session.commit()
        assert playable_tracks(row,station.id)==[]


def test_full_window_history_is_not_truncated_and_unknown_artists_are_independent(app):
    from app.services.selection_policy import eligible, recent
    with app.app_context():
        station,row,songs=setup_playlist();station.automation.track_separation_seconds=86400
        now=datetime.now(timezone.utc)
        records=[m.SelectionDecision(station_id=station.id,track_id=songs[0].id,status='started',selected_at=now-timedelta(days=2),started_at=now-timedelta(hours=20))]
        records += [m.SelectionDecision(station_id=station.id,track_id=songs[2].id,status='started',selected_at=now,started_at=now-timedelta(seconds=i)) for i in range(501)]
        db.session.add_all(records);db.session.commit()
        pool,_,_=eligible(songs,recent(station,station.automation,now),now,86400,0)
        assert songs[0] not in pool and songs[1] in pool
        songs[0].artist=songs[1].artist=''
        pool,_,_=eligible(songs[:2],records,now,86400,86400)
        assert pool==[songs[1]]


def test_weights_favor_matching_tags_and_categories_without_changing_membership(app,monkeypatch):
    import random
    from app.services.smart_playlists import weighted_choice
    with app.app_context():
        station,row,songs=setup_playlist();tag=m.MusicTag(station_id=station.id,name='Favored',slug='favored');songs[0].tags=[tag];db.session.add(tag);db.session.flush()
        category=songs[0].categories[0]
        weights={'tags':{str(tag.id):4},'categories':{str(category.id):5}}
        generator=random.Random(20261004)
        monkeypatch.setattr('app.services.smart_playlists.random.choices',generator.choices)
        draws=[weighted_choice(songs[:2],weights).id for _ in range(2000)]
        assert set(draws)=={s.id for s in songs[:2]}
        assert .86 < draws.count(songs[0].id)/len(draws) < .94


def test_direct_visual_leader_refresh_preserves_unrelated_clock_cursors(app,monkeypatch):
    from app.services.visual_schedule import select_visual
    from app.services.media_storage import LocalMediaStorage
    from app.services.programming_refresh import refresh, checkpoint
    from app.automation_worker import EventReader
    from tests.test_programming_refresh import fake_engine
    queued={99};fake_engine(monkeypatch,queued,set())
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist();program(station,row,at);db.session.commit()
        prior=select_next(station.slug,now=at);prior.status='started';db.session.commit()
        before=checkpoint(station)
        row.leader_track=songs[-1];db.session.commit()
        leader=select_visual(station,dict(source={'kind':'playlist','id':row.id},key='explicit-switch'),LocalMediaStorage(),at)
        leader.status='queued';leader.liquidsoap_request_id=99;leader.socket_identity='test-engine';db.session.commit()
        assert refresh(station,EventReader(),'changed-programming')
        assert not queued and leader.status=='failed'
        assert checkpoint(station)==before
