"""Coverage, recurrence, traffic locks, and safe event insertion."""
from datetime import date, datetime, timedelta, timezone
import pytest

from app.extensions import db
from app.models import ScheduleAssignment, ScheduleProgram, SelectionDecision, Station, TimedEvent, TimedEventOccurrence, Track
from app.services.calendar import create_program
from app.services.planning import baseline_conversion, convert_baseline, coverage, restore_baseline, set_station_default
from app.services.timed_events import _instants, projected_occurrences, save_event
from tests.test_web import app, admin_client


def instant(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_calendar_forecast_is_read_only_and_shows_distant_multi_day_series(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        event = save_event(station.slug, name='Weekday station ID', timing_mode='SOFT', recurrence_type='WEEKLY',
            content_type='TRACK', content_identifier=Track.query.first().uuid, weekdays=['0','2','4'], local_time='09:00', late_tolerance_seconds=300)
        before = TimedEventOccurrence.query.count()
        future = projected_occurrences(station, instant('2027-01-04T00:00'), instant('2027-01-11T00:00'))
        assert len(future) == 3 and all(row.state == 'PROJECTED' for row in future)
        assert {row.event.id for row in future} == {event.id}
        assert TimedEventOccurrence.query.count() == before
    client = admin_client(app)
    response = client.get('/admin/stations/test-station/calendar?date=2027-01-04')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'schedule-studio' in body
    forecast = client.get('/admin/stations/test-station/schedule-studio/api/events?date=2027-01-04&days=7').json
    assert len(forecast['items']) == 3 and forecast['items'][0]['name'] == 'Weekday station ID'
    with app.app_context():
        assert TimedEventOccurrence.query.count() == before
    assert client.get('/admin/stations/test-station/calendar?view=day&date=2027-01-05').get_data(as_text=True).count('Edit event →') == 0


def test_series_edit_changes_all_days_and_preserves_started_history(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        track = Track.query.first()
        args = dict(name='Series', timing_mode='SOFT', recurrence_type='WEEKLY', content_type='TRACK', content_identifier=track.uuid, local_time='09:00')
        row = save_event(station.slug, weekdays=['0','1'], **args)
        recorded = row.occurrences[0]
        recorded.state = 'STARTED'; recorded.started_at = recorded.scheduled_for_utc
        db.session.commit()
        row = save_event(station.slug, identifier=row.uuid, weekdays=['2','4'], **args)
        assert row.repeat_days == [2,4] and recorded.state == 'STARTED'
        assert len(_instants(row, instant('2027-01-04T00:00'), instant('2027-01-10T23:59'))) == 2
        with pytest.raises(ValueError, match='repeat day'):
            save_event(station.slug, weekdays=[], **args)


def test_defaults_and_calendar_precedence(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        ScheduleAssignment.query.update({'enabled':False})
        set_station_default(station, 'rotation:main')
        create_program(station,name='Breakfast',weekdays=['0'],start='06:00',end='10:00',category_slug='power')
        create_program(station,name='Special',weekdays=[],on_date='2027-01-04',start='08:00',end='09:00',category_slug='power')
        db.session.commit()
        result = coverage(station,instant('2027-01-04T00:00'),instant('2027-01-05T00:00'))
        assert [row['source'] for row in result] == ['Station default','Weekly program','Dated program','Weekly program','Station default']
        assert result[0]['name'] == 'Main Rotation'
        with pytest.raises(ValueError):
            set_station_default(station, 'category:missing')


def test_baseline_conversion_preserves_week_wrap_and_cursor_and_can_restore(app):
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        create_program(station,name='Breakfast',weekdays=['0'],start='06:00',end='10:00',category_slug='power')
        db.session.commit()
        before = coverage(station, instant('2027-01-03T23:00'), instant('2027-01-05T01:00'))
        from app.services.schedule import resolve
        transition = resolve(station,instant('2027-01-05T23:59')).next_transition
        rows, token = baseline_conversion(station)
        assert len(rows) == 7
        assert convert_baseline(station,token) == 7
        db.session.commit()
        after = coverage(station, instant('2027-01-03T23:00'), instant('2027-01-05T01:00'))
        assert [(r['start'],r['end'],r['occurrence_key']) for r in before] == [(r['start'],r['end'],r['occurrence_key']) for r in after]
        assert resolve(station,instant('2027-01-05T23:59')).next_transition == transition
        assert ScheduleAssignment.query.filter_by(enabled=True).count() == 0
        assert restore_baseline(station) == 7
        db.session.commit()
        assert ScheduleAssignment.query.filter_by(enabled=True).count() == 1
        assert ScheduleProgram.query.filter_by(enabled=True).count() == 1
        with pytest.raises(ValueError,match='changed'):
            convert_baseline(station,token)


def test_event_create_multiday_form_and_navigation(app):
    client = admin_client(app)
    base = '/admin/stations/test-station'
    page = client.get(base + '/events/create').get_data(as_text=True)
    nav = page.split('aria-label="Admin sections"')[1].split('</nav>')[0]
    assert nav.index('>Music<') < nav.index('>Categories<') < nav.index('>Playlists<') < nav.index('>Shows<')
    assert 'value="300"' in page
    with app.app_context():
        track_id = Track.query.first().uuid
    data = dict(csrf='test-admin-csrf-token', name='Announcement', timing_mode='SOFT', recurrence_type='WEEKLY',
                content_type='TRACK',content_identifier=track_id,local_time='10:15',weekdays=['0','1','2','3','4'],
                repeat_days_present='1',early_tolerance_seconds='0',late_tolerance_seconds='300',missed_policy='SKIP',interrupt_policy='NEVER',priority='100')
    assert client.post(base+'/events/create',data=data).status_code == 303
    with app.app_context():
        event = TimedEvent.query.filter_by(name='Announcement').one()
        assert event.repeat_days == [0,1,2,3,4]
    assert client.get(base+'/schedule').status_code == 200
    assert client.post(base+'/schedule/default',data={'csrf':'test-admin-csrf-token','choice':'category:power'}).status_code == 303


def test_soft_event_uses_next_boundary_without_consuming_music_cursor(app,monkeypatch):
    from app.automation_worker import EventReader, process_timed_events, automatic_future_only
    from app.services.playout_queue import push_decision
    commands = []
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe/test.mp3')
    monkeypatch.setattr('app.automation_worker.socket_identity',lambda slug:'sock')
    monkeypatch.setattr('app.automation_worker.active_ids',lambda slug:{11})
    monkeypatch.setattr('app.automation_worker.queued_ids',lambda slug:{12,13})
    monkeypatch.setattr('app.automation_worker.queue_depth',lambda slug:2)
    monkeypatch.setattr('app.services.playout_queue._command',lambda slug,command:commands.append(command) or '14')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one(); track=Track.query.first()
        track.duration_ms=240000
        now=datetime.now(timezone.utc)
        current=SelectionDecision.query.filter_by(status='started').first()
        current.started_at=now-timedelta(seconds=60);current.socket_identity='sock';current.liquidsoap_request_id=11
        for rid in (12,13):
            db.session.add(SelectionDecision(station_id=station.id,track_id=track.id,status='queued',socket_identity='sock',liquidsoap_request_id=rid,selection_method='rotation'))
        db.session.commit()
        before=station.automation.next_slot_index
        event=save_event(station.slug,name='Boundary',timing_mode='SOFT',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,
                         local_date=now.date().isoformat(),local_time=(now+timedelta(seconds=10)).strftime('%H:%M:%S'),late_tolerance_seconds=300)
        process_timed_events(station,EventReader(),now)
        assert commands == []  # Never queue early under the default policy.
        process_timed_events(station,EventReader(),now+timedelta(seconds=11))
        assert event.occurrences[0].state == 'QUEUED'
        assert '.insert annotate:' in commands[0]
        assert station.automation.next_slot_index == before
        future=SelectionDecision.query.filter_by(liquidsoap_request_id=12).one()
        future.selection_method='timed_event';db.session.commit()
        assert not automatic_future_only(station)


def test_finalized_commercial_events_cannot_be_changed_through_generic_forms(app,monkeypatch):
    from tests.test_traffic import setup_traffic
    from app.services.traffic import generate_log, finalize_log
    from app.services.timed_events import set_enabled
    with app.app_context():
        station,_,_,day=setup_traffic(monkeypatch)
        log,_=generate_log(station.slug,day);finalize_log(log)
        event=TimedEvent.query.filter_by(station_id=station.id).first()
        identifier=event.uuid
        with pytest.raises(ValueError,match='Commercials'):
            set_enabled(event,False)
        with pytest.raises(ValueError,match='Commercials'):
            save_event(station.slug,identifier=identifier,name='Changed',timing_mode='SOFT',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=Track.query.first().uuid,local_date=str(day),local_time='12:00')
        forecast=projected_occurrences(station,datetime.combine(day,datetime.min.time(),timezone.utc),datetime.combine(day+timedelta(days=1),datetime.min.time(),timezone.utc))
        assert len(forecast)==2 and all(row.commercial_log.id==log.id for row in forecast)
    client=admin_client(app)
    body=client.get('/admin/stations/test-station/events/'+identifier).get_data(as_text=True)
    assert 'Open commercial log' in body and 'Save changes' not in body


def test_recovered_event_submission_is_not_pushed_again(app,monkeypatch):
    from app.automation_worker import _queue_event
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').one();track=Track.query.first()
        event=save_event(station.slug,name='Restart',timing_mode='SOFT',recurrence_type='WEEKLY',content_type='TRACK',content_identifier=track.uuid,weekday=0,local_time='09:00')
        occurrence=event.occurrences[0]
        decision=SelectionDecision(station_id=station.id,track_id=track.id,selection_method='timed_event',status='queued')
        occurrence.selection_decision=decision;occurrence.state='READY';db.session.commit()
        monkeypatch.setattr('app.automation_worker.push_decision',lambda row:pytest.fail('duplicate event'))
        _queue_event(occurrence,station.slug,datetime.now(timezone.utc))
        assert occurrence.state=='QUEUED'



def test_scheduling_station_picker_changes_scope(app):
    client=admin_client(app)
    for section in ('calendar','events','blocks','traffic'):
        response=client.get(f'/admin/{section}?station=second-station')
        assert response.status_code==302
        assert '/admin/stations/second-station/' in response.headers['Location']


def test_materialized_commercial_sequence_is_locked(app,monkeypatch):
    from tests.test_traffic import setup_traffic
    from app.services.traffic import generate_log,finalize_log
    from app.services.event_blocks import remove_item,set_enabled
    with app.app_context():
        station,_,_,day=setup_traffic(monkeypatch)
        log,_=generate_log(station.slug,day);finalize_log(log)
        event=TimedEvent.query.filter_by(station_id=station.id).first()
        block=event.event_block;slug=block.slug
        with pytest.raises(ValueError,match='Commercials'):
            remove_item(block,block.items[0].id)
        with pytest.raises(ValueError,match='Commercials'):
            set_enabled(block,False)
    response=admin_client(app).get('/admin/stations/test-station/blocks/'+slug)
    assert response.status_code==302 and '/traffic/logs/' in response.headers['Location']
