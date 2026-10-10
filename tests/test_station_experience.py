"""Calendar, station identity, category safety, and shared cart regressions."""
from datetime import datetime, timezone
import uuid
import pytest
from app.extensions import db
from app.models import AdminUser, Clock, MediaCategory, ScheduleProgram, Station, Track, LiveQueueSnapshot
from app.services.calendar import create_program
from app.services.schedule import resolve
from app.services.programming import delete_category
from app.services.stations import update_station
from app.services.live_assist import assign_cart, fire_cart, set_mixer
from tests.test_web import app as app_fixture, admin_client


@pytest.fixture
def app(app_fixture):
    return app_fixture


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_category_program_loops_in_bounded_window_and_restores_default(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        rows=create_program(station,name='Morning',weekdays=['0','1'],start='09:00',end='12:00',category_slug='power')
        db.session.commit()
        active=resolve(station,at('2026-09-14T10:00'))
        assert active.program.id==rows[0].id and active.clock.slots[0].category.slug=='power'
        assert active.next_transition==at('2026-09-14T12:00')
        assert resolve(station,at('2026-09-14T12:00')).clock.slug=='music'
        assert resolve(station,at('2026-09-15T11:00')).program.id==rows[1].id
        assert resolve(station,at('2026-09-16T11:00')).program is None


def test_program_overlap_overnight_and_date_override(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        create_program(station,name='Night',weekdays=['0'],start='22:00',end='02:00',category_slug='power');db.session.commit()
        assert resolve(station,at('2026-09-15T01:00')).program.name=='Night'
        with pytest.raises(ValueError,match='overlaps'):
            create_program(station,name='Conflict',weekdays=['1'],start='01:00',end='03:00',category_slug='power')
        db.session.rollback()
        create_program(station,name='Special',weekdays=[],on_date='2026-09-15',start='00:00',end='01:30',category_slug='power');db.session.commit()
        assert resolve(station,at('2026-09-15T01:00')).program.name=='Special'
        assert resolve(station,at('2026-09-15T01:45')).program.name=='Night'


def test_category_delete_keeps_songs_and_replaces_all_programming(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        with pytest.raises(ValueError,match='used in programming'):
            delete_category(station.slug,'power')
        replacement=MediaCategory(station_id=station.id,name='New music',slug='new-music',enabled=True)
        replacement.tracks.append(Track.query.first());db.session.add(replacement);db.session.commit()
        count=Track.query.count()
        delete_category(station.slug,'power','new-music')
        assert Track.query.count()==count
        assert MediaCategory.query.filter_by(slug='power').first() is None
        assert Clock.query.filter_by(slug='music').first().slots[0].category_id==replacement.id
        assert replacement.tracks


def test_station_name_and_public_url_keep_internal_identity_and_aliases(app):
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        user=AdminUser.query.first()
        update_station(station,name='New Radio',description='New description',public_slug='new-radio',timezone_name='UTC',user=user)
        assert station.slug=='test-station' and station.stream.mount=='/test-station'
        assert station.stream.public_path=='/listen/new-radio'
        update_station(station,name='Newer Radio',description='Updated',public_slug='newer-radio',timezone_name='UTC',user=user)
        with pytest.raises(ValueError,match='already in use'):
            update_station(station,name='Wrong',description='',public_slug='second-station',timezone_name='UTC',user=user)
    client=app.test_client()
    for slug in ('test-station','new-radio','newer-radio'):
        assert client.get('/player/'+slug).status_code==200
        assert client.get('/listen/'+slug).headers['Location']=='/stream/test-station'
    assert b'Newer Radio' in client.get('/stations',follow_redirects=True).data


def test_song_cart_description_and_behavior_are_snapshotted(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first();user=AdminUser.query.first()
        db.session.add(LiveQueueSnapshot(station_id=station.id,observed_at=datetime.now(timezone.utc),queued_decision_ids=[],unknown_count=0,mixer={'mode':'AUTO'}));db.session.commit()
        cart=assign_cart(station,user,'ID',1,Track.query.first().uuid,'Hello','Our hourly introduction','OVER',65)
        assert cart.track and cart.description=='Our hourly introduction'
        row=fire_cart(station,user,'ID',1,str(uuid.uuid4()))
        assert row.playback_bus=='CART' and row.cart_mode=='OVER' and row.duck_percent==65
        assign_cart(station,user,'ID',1,Track.query.first().uuid,'Changed','Changed','TAKEOVER',0)
        assert row.cart_mode=='OVER' and row.duck_percent==65
        station.automation.operator_mode='DJ_BOOTH';db.session.commit()
        set_mixer(station,user,'crossfader','0.5')
        assert station.automation.crossfader==.5
        with pytest.raises(ValueError):set_mixer(station,user,'crossfader','nan')


def test_calendar_routes_are_authenticated_and_station_scoped(app):
    assert app.test_client().get('/admin/stations/test-station/calendar').status_code==302
    client=admin_client(app)
    assert client.get('/admin/stations/test-station/calendar').status_code==200
    payload={'csrf':'test-admin-csrf-token','name':'Daytime','weekday':['0','1'],'start':'09:00','end':'17:00','kind':'category','category':'power'}
    response=client.post('/admin/stations/test-station/calendar/create',data=payload,follow_redirects=True)
    assert response.status_code==200 and b'Daytime' in response.data
    with app.app_context():assert ScheduleProgram.query.count()==2
    client.post('/admin/stations/second-station/calendar/create',data=payload)
    with app.app_context():assert ScheduleProgram.query.count()==2


def test_calendar_program_drives_actual_selector_without_weekly_assignment(app,monkeypatch):
    from app.services.automation import select_next
    from app.services.clocks import current
    monkeypatch.setattr('app.services.automation._exists',lambda *args:True)
    with app.app_context():
        station=Station.query.filter_by(slug='test-station').first()
        create_program(station,name='Morning',weekdays=['0'],start='09:00',end='12:00',category_slug='power');db.session.commit()
        selected=select_next(station.slug,now=at('2026-09-14T10:00'))
        assert selected.track_id==Track.query.first().id
        assert selected.schedule_assignment_id is None and selected.schedule_occurrence.startswith('program:')
        assert current(station.slug,at('2026-09-14T10:00'))['source']=='calendar'
