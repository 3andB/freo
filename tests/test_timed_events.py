"""Timed events remain station-scoped, durable, DST-aware, and cursor-neutral."""
from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.extensions import db
from app.models import (AdminUser, AutomationState, ClockState, SelectionDecision, Station,
                        TimedEvent, TimedEventOccurrence, Track)
from app.services.timed_events import (_instants, conflict_warnings, generate_occurrences,
    prepare_decision, save_event)
from tests.test_web import app as app_fixture, admin_client


@pytest.fixture
def app(app_fixture): return app_fixture


def create_one(station, track, when, **options):
    local = when.astimezone(timezone.utc)
    return save_event(station.slug, name=options.pop('name','Test Event'), timing_mode=options.pop('timing_mode','HARD'),
        recurrence_type='ONE_TIME', content_type='TRACK', content_identifier=track.uuid,
        local_date=local.date().isoformat(), local_time=local.time().replace(microsecond=0).isoformat(),
        interrupt_policy=options.pop('interrupt_policy','MUSIC_ONLY'), **options)


def test_one_time_occurrence_unique_and_cursor_neutral(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first(); station.timezone='UTC'; track=Track.query.first()
        state=station.automation; before=state.next_slot_index
        event=create_one(station,track,datetime.now(timezone.utc)+timedelta(minutes=2))
        assert generate_occurrences(station)==0
        assert TimedEventOccurrence.query.filter_by(timed_event_id=event.id).count()==1
        occurrence=event.occurrences[0]
        assert occurrence.eligible_at_utc <= occurrence.scheduled_for_utc < occurrence.deadline_at_utc
        assert state.next_slot_index==before


def test_weekly_dst_spring_shifts_once_and_fall_fires_once(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first(); station.timezone='America/Denver'; track=Track.query.first()
        spring=save_event(station.slug,name='Spring',timing_mode='NON_INTERRUPTING',recurrence_type='WEEKLY',
            content_type='TRACK',content_identifier=track.uuid,weekday=6,local_time='02:30:00',interrupt_policy='NEVER')
        values=_instants(spring,datetime(2026,3,7,tzinfo=timezone.utc),datetime(2026,3,10,tzinfo=timezone.utc))
        assert len(values)==1 and values[0].astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).hour==3
        fall=save_event(station.slug,name='Fall',timing_mode='NON_INTERRUPTING',recurrence_type='WEEKLY',
            content_type='TRACK',content_identifier=track.uuid,weekday=6,local_time='01:30:00',interrupt_policy='NEVER')
        values=_instants(fall,datetime(2026,10,31,tzinfo=timezone.utc),datetime(2026,11,3,tzinfo=timezone.utc))
        assert len(values)==1 and values[0].astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).fold==0


def test_content_station_scope_validation_and_collision(app):
    with app.app_context():
        one=Station.query.filter_by(slug='test-station').first(); one.timezone='UTC'; two=Station.query.filter_by(slug='second-station').first(); track=Track.query.first()
        with pytest.raises(ValueError,match='another station'):
            save_event(two.slug,name='IDOR',timing_mode='HARD',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,
                local_date='2026-09-15',local_time='12:00:00',interrupt_policy='MUSIC_ONLY')
        at=datetime.now(timezone.utc)+timedelta(minutes=5)
        first=create_one(one,track,at,name='First'); second=create_one(one,track,at,name='Second',priority=50)
        assert any('First' in warning for warning in conflict_warnings(second))


def test_event_routes_auth_csrf_and_idor(app):
    anonymous=app.test_client(); base='/admin/stations/test-station/events'
    assert anonymous.get(base).status_code==302 and anonymous.post(base+'/create').status_code==302
    client=admin_client(app)
    assert client.get(base).status_code==200
    assert client.post(base+'/create').status_code==400
    with app.app_context(): track=Track.query.first(); identifier=track.uuid
    data={'csrf':'test-admin-csrf-token','name':'Web Event','timing_mode':'HARD','recurrence_type':'ONE_TIME',
          'content_type':'TRACK','content_identifier':identifier,'local_date':'2026-09-16','local_time':'12:00:00',
          'early_tolerance_seconds':'0','late_tolerance_seconds':'5','missed_policy':'SKIP','interrupt_policy':'MUSIC_ONLY','priority':'100'}
    assert client.post(base+'/create',data=data).status_code==303
    with app.app_context(): event=TimedEvent.query.filter_by(name='Web Event').first(); eid=event.uuid
    assert client.get(base+'/'+eid).status_code==200
    assert client.get('/admin/stations/second-station/events/'+eid).status_code==404
    assert client.get(base+'/'+eid+'/disable').status_code in (404,405)
    assert client.post(base+'/'+eid+'/disable',data={'csrf':'wrong'}).status_code==400
    assert client.post(base+'/'+eid+'/disable',data={'csrf':'test-admin-csrf-token'}).status_code==303


def test_playback_confirmation_links_occurrence_and_separation(app, monkeypatch):
    from app.services.automation import playback_started, _choose
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first(); station.timezone='UTC'; track=Track.query.first()
        event=create_one(station,track,datetime.now(timezone.utc)+timedelta(seconds=2)); occurrence=event.occurrences[0]
        decision=prepare_decision(occurrence); decision.status='queued'; db.session.commit()
        at=occurrence.scheduled_for_utc.replace(tzinfo=timezone.utc)+timedelta(seconds=1)
        assert playback_started(decision.id,station.slug,at)
        assert occurrence.state=='STARTED' and occurrence.timing_offset_seconds==pytest.approx(1)
        other=Track(id=999,title='Other',artist='Other',album='',original_filename='x',storage_key='0'*32+'.mp3',media_type='mp3',duration_ms=1,sample_rate_hz=1,channels=1,file_size_bytes=1,checksum_sha256='b'*64)
        chosen,_,_=_choose([track,other],[decision],at,300,300)
        assert chosen is other


def test_hard_interrupts_only_automated_music_and_collision_priority(app, monkeypatch):
    from app.automation_worker import EventReader, process_timed_events
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    calls=[]
    monkeypatch.setattr('app.automation_worker.socket_identity',lambda slug:'sock')
    monkeypatch.setattr('app.automation_worker.active_ids',lambda slug:{77})
    monkeypatch.setattr('app.automation_worker.interrupt_for_event',lambda slug:calls.append('interrupt'))
    monkeypatch.setattr('app.automation_worker.push_decision',lambda decision:88)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first(); station.timezone='UTC'; track=Track.query.first()
        current=SelectionDecision.query.filter_by(status='started').first(); current.socket_identity='sock';current.liquidsoap_request_id=77;db.session.commit()
        at=datetime.now(timezone.utc)
        high=create_one(station,track,at,name='High',priority=200,late_tolerance_seconds=5)
        low=create_one(station,track,at,name='Low',priority=50,late_tolerance_seconds=5)
        process_timed_events(station,EventReader(),at)
        assert calls==['interrupt'] and high.occurrences[0].state=='QUEUED' and low.occurrences[0].state=='PENDING'
        # A manual current item is protected even for MUSIC_ONLY.
        high.occurrences[0].state='STARTED'; current.admin_user_id=AdminUser.query.first().id; db.session.commit()
        process_timed_events(station,EventReader(),at+timedelta(seconds=1))
        assert calls==['interrupt']


def test_stale_skip_policy_marks_missed_without_queue(app, monkeypatch):
    from app.automation_worker import EventReader, process_timed_events
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();station.timezone='UTC';track=Track.query.first();now=datetime.now(timezone.utc)
        event=create_one(station,track,now-timedelta(seconds=20),late_tolerance_seconds=3)
        occurrence=event.occurrences[0]; process_timed_events(station,EventReader(),now)
        assert occurrence.state=='MISSED' and occurrence.selection_decision_id is None


def test_soft_and_non_interrupting_queue_without_skip_inside_window(app, monkeypatch):
    from app.automation_worker import EventReader, process_timed_events
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    monkeypatch.setattr('app.automation_worker.socket_identity',lambda slug:'sock')
    monkeypatch.setattr('app.automation_worker.active_ids',lambda slug:set())
    monkeypatch.setattr('app.automation_worker.queue_depth',lambda slug:0)
    monkeypatch.setattr('app.automation_worker.push_decision',lambda decision:91)
    monkeypatch.setattr('app.automation_worker.interrupt_for_event',lambda slug:pytest.fail('must not interrupt'))
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();station.timezone='UTC';track=Track.query.first();now=datetime.now(timezone.utc)
        soft=save_event(station.slug,name='Soft',timing_mode='SOFT',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,
            local_date=now.date().isoformat(),local_time=now.time().replace(microsecond=0).isoformat(),interrupt_policy='NEVER',missed_policy='PLAY_LATE',late_tolerance_seconds=30,priority=200)
        process_timed_events(station,EventReader(),now)
        assert soft.occurrences[0].state=='QUEUED'
        soft.occurrences[0].state='STARTED';db.session.commit()
        non=save_event(station.slug,name='Non',timing_mode='NON_INTERRUPTING',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,
            local_date=now.date().isoformat(),local_time=now.time().replace(microsecond=0).isoformat(),interrupt_policy='NEVER',late_tolerance_seconds=30)
        process_timed_events(station,EventReader(),now)
        assert non.occurrences[0].state=='QUEUED'


def test_event_cli_and_api_do_not_expose_paths(app, monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();station.timezone='UTC';track=Track.query.first();
        event=create_one(station,track,datetime.now(timezone.utc)+timedelta(hours=1))
        identifier=event.uuid
    runner=app.test_cli_runner()
    assert runner.invoke(args=['event','list','--station','test-station']).exit_code==0
    shown=runner.invoke(args=['event','show','--station','test-station',identifier])
    assert shown.exit_code==0 and 'storage_key' not in shown.output and '/var/' not in shown.output
