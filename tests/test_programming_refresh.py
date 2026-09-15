"""Refresh queue intent and selection cursors without touching active audio."""
from datetime import datetime,timezone
from app.extensions import db
from app import models as m
from app.services.programming_refresh import signature,refresh,checkpoint
from app.services.automation import select_next
from app.automation_worker import EventReader
from tests.test_web import app


def station():return m.Station.query.filter_by(slug='test-station').one()


def fake_engine(monkeypatch,queued,active=None):
    from app.services import playout_queue as queue
    monkeypatch.setattr(queue,'queued_ids',lambda slug:set(queued))
    monkeypatch.setattr(queue,'active_ids',lambda slug:set(active or []))
    monkeypatch.setattr(queue,'socket_identity',lambda slug:'test-engine')
    monkeypatch.setattr(queue,'remove_future',lambda slug,ids:queued.difference_update(ids))
    monkeypatch.setattr(EventReader,'collect',lambda *args:0)
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')


def queue_row(station,request_id,**kwargs):
    row=select_next(station.slug)
    row.status='queued';row.socket_identity='test-engine';row.liquidsoap_request_id=request_id
    for key,value in kwargs.items():setattr(row,key,value)
    db.session.commit();return row


def test_category_membership_refresh_restores_cursor_preserves_manual_and_active(app,monkeypatch):
    queued={11,12,13};fake_engine(monkeypatch,queued,{10})
    with app.app_context():
        s=station();song=m.Track.query.first();category=song.categories[0]
        clock=m.Clock.query.first();clock.slots.append(m.ClockSlot(position=2,slot_type='CATEGORY',category=category));db.session.commit()
        first=queue_row(s,11);second=queue_row(s,12)
        manual=m.SelectionDecision(station_id=s.id,track_id=song.id,status='queued',admin_user_id=m.AdminUser.query.first().id,selection_method='manual_track',socket_identity='test-engine',liquidsoap_request_id=13)
        db.session.add(manual);db.session.commit()
        before=signature(s);category.tracks.remove(song);db.session.commit()
        after=signature(s);assert after!=before
        reader=EventReader();reader.starved_until[s.slug]=999999999
        assert refresh(s,reader,after)
        assert queued=={13} and manual.status=='queued'
        assert first.reason==second.reason=='programming_changed'
        assert m.ClockState.query.first().next_slot_index==0
        assert s.slug not in reader.starved_until
        assert m.SelectionDecision.query.filter_by(status='started').count()==1
        assert not refresh(s,reader,after)


def test_refresh_after_boundary_never_rewinds_already_started_slot(app,monkeypatch):
    queued={11,12};active={11};fake_engine(monkeypatch,queued,active)
    with app.app_context():
        s=station();category=m.Track.query.first().categories[0]
        clock=m.Clock.query.first()
        for pos in (2,3):clock.slots.append(m.ClockSlot(position=pos,slot_type='CATEGORY',category=category))
        db.session.commit()
        first=queue_row(s,11);second=queue_row(s,12)
        category.name='Changed';db.session.commit()
        def remove(slug,ids):
            first.status='started';first.started_at=datetime.now(timezone.utc)
            queued.clear();db.session.commit()
        monkeypatch.setattr('app.services.playout_queue.remove_future',remove)
        assert refresh(s,EventReader(),signature(s))
        assert first.status=='started' and second.status=='failed'
        assert m.ClockState.query.first().next_slot_index==1


def test_refresh_resumes_after_worker_dies_following_engine_removal(app,monkeypatch):
    queued=set();fake_engine(monkeypatch,queued)
    with app.app_context():
        s=station();row=queue_row(s,11)
        row.reason='programming_refresh_pending';row.status='failed';db.session.commit()
        assert refresh(s,EventReader(),signature(s))
        assert row.reason=='programming_changed'
        assert not refresh(s,EventReader(),signature(s))


def test_signature_tracks_cli_bulk_edits_inheritance_and_station_isolation(app):
    with app.app_context():
        s=station();song=m.Track.query.first();other=m.Station.query.filter_by(slug='second-station').one()
        db.session.add(m.AutomationState(station_id=other.id));db.session.commit()
        baseline=signature(s)
        other.name='Unrelated';db.session.commit();assert signature(s)==baseline
        m.ClockSlot.query.update({'label':'Bulk change'});db.session.commit();assert signature(s)!=baseline
        baseline=signature(s)
        m.ScheduleAssignment.query.update({'weekday':2});db.session.commit();assert signature(s)!=baseline
        other_category=m.MediaCategory(station_id=other.id,name='Other category',slug='other-category')
        other_category.tracks.append(song);db.session.add(other_category);db.session.commit()
        baseline=signature(other)
        song.available_to_all=True;db.session.commit();assert signature(other)!=baseline
        baseline=signature(other)
        song.enabled=False;db.session.commit();assert signature(other)!=baseline
        baseline=signature(s)
        song.notes='Review notes do not alter programming';db.session.commit();assert signature(s)==baseline


def test_non_music_programming_changes_and_events_are_preserved(app,monkeypatch):
    queued={11,12};fake_engine(monkeypatch,queued)
    with app.app_context():
        s=station();song=m.Track.query.first();first=queue_row(s,11)
        event=m.SelectionDecision(station_id=s.id,track_id=song.id,status='queued',selection_method='timed_event',socket_identity='test-engine',liquidsoap_request_id=12)
        db.session.add(event);db.session.commit()
        before=signature(s)
        rotation=m.Rotation.query.first();rotation.slots[0].enabled=False;db.session.commit()
        assert signature(s)!=before
        refresh(s,EventReader(),signature(s));assert queued=={12} and event.status=='queued'
        assert first.status=='failed'


import pytest


@pytest.mark.parametrize('change',['clock','schedule_update','schedule_add','category_members','rotation'])
def test_next_selection_uses_new_programming_after_each_edit(app,monkeypatch,change):
    queued={11};fake_engine(monkeypatch,queued)
    with app.app_context():
        s=station();old=m.Track.query.first();power=old.categories[0]
        quiet=m.MediaCategory(station_id=s.id,name='Quiet',slug='quiet',enabled=True)
        replacement=m.Track(station_id=s.id,uuid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',title='Replacement',artist='Other',original_filename='b.mp3',storage_key='b'*32+'.mp3',media_type='mp3',duration_ms=10000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='b'*64,enabled=True,ingest_status='accepted')
        quiet.tracks.append(replacement)
        alternate=m.Clock(station_id=s.id,name='Quiet Clock',slug='quiet-clock',enabled=True)
        alternate.slots.append(m.ClockSlot(position=1,slot_type='CATEGORY',category=quiet))
        db.session.add_all([quiet,replacement,alternate]);db.session.commit()
        if change=='rotation':
            m.ScheduleAssignment.query.update({'enabled':False});db.session.commit()
        row=queue_row(s,11);assert row.track_id==old.id
        if change=='clock':m.ClockSlot.query.filter(m.ClockSlot.clock_id==m.Clock.query.filter_by(slug='music').one().id).update({'category_id':quiet.id})
        elif change=='schedule_update':m.ScheduleAssignment.query.update({'clock_id':alternate.id})
        elif change=='schedule_add':
            from app.services.calendar import create_program
            now=datetime.now(timezone.utc)
            create_program(s,name='New program',weekdays=[],on_date=now.date().isoformat(),start='00:00',end='23:59',category_slug='quiet')
        elif change=='category_members':power.tracks.remove(old);power.tracks.append(replacement)
        else:m.RotationSlot.query.update({'category_id':quiet.id})
        db.session.commit()
        assert refresh(s,EventReader(),signature(s))
        next_row=select_next(s.slug)
        assert next_row.track_id==replacement.id
        assert row.status=='failed' and row.reason=='programming_changed'


def test_refresh_recovers_push_before_database_commit(app,monkeypatch):
    queued={11};fake_engine(monkeypatch,queued)
    with app.app_context():
        s=station();row=select_next(s.slug)
        m.MediaCategory.query.first().name='Edited after push';db.session.commit()
        monkeypatch.setattr('app.services.playout_queue.request_decision_id',lambda slug,rid:row.id)
        assert refresh(s,EventReader(),signature(s))
        assert not queued and row.reason=='programming_changed'


def test_unrelated_shared_library_song_does_not_refresh_station(app):
    with app.app_context():
        s=station();other=m.Station.query.filter_by(slug='second-station').one()
        unrelated=m.Track(station_id=other.id,uuid='cccccccc-cccc-4ccc-8ccc-cccccccccccc',title='Unassigned shared song',artist='Other',original_filename='c.mp3',storage_key='c'*32+'.mp3',media_type='mp3',duration_ms=10000,sample_rate_hz=44100,channels=2,file_size_bytes=100,checksum_sha256='c'*64,enabled=True,ingest_status='accepted',available_to_all=True)
        baseline=signature(s);db.session.add(unrelated);db.session.commit()
        assert signature(s)==baseline
        unrelated.enabled=False;db.session.commit();assert signature(s)==baseline
