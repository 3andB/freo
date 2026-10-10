"""Operator and recovery regressions from the September Events review."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import uuid
import pytest

from app.extensions import db
from app import models as m
from app.services import timed_events as events
from app.services.audio_classification import classify, defaults
from app.services.event_blocks import create_playlist_execution, finish_execution
from tests.test_web import app, admin_client


def audio():
    station=m.Station.query.filter_by(slug='test-station').one()
    station.timezone='UTC'
    return station,m.Track.query.first()


@pytest.mark.parametrize('kind',events.RECURRENCES)
def test_save_preview_and_edit_share_recurrence_validation(app,kind):
    client=admin_client(app)
    with app.app_context():
        station,track=audio();identifier=track.uuid;db.session.commit()
    form=dict(csrf='test-admin-csrf-token',name='Operator schedule',recurrence_type=kind,
        content_type='TRACK',content_identifier=identifier,local_date='2028-02-29',
        local_time='12:07:03',starts_on='2028-02-01',ends_on='2028-03-31',
        repeat_days_present='1',weekdays=['0','2'],repeat_hours=['8','12'],
        month_nth='-1',month_weekday='4',month_day='31',interrupt_dj='no',hourly='on')
    base='/admin/stations/test-station/events'
    preview=client.get(base+'/preview',query_string=form)
    assert preview.status_code==200,preview.json
    saved=client.post(base+'/create',data=form)
    assert saved.status_code==303
    with app.app_context():
        row=m.TimedEvent.query.filter_by(name=form['name']).one()
        identifier=row.uuid
        expected=[t.astimezone(ZoneInfo('UTC')).strftime('%a %d %b %Y %H:%M:%S %Z (%z)') for t in events.next_instants(row)]
        assert expected==preview.json['times']
        assert row.timing_mode=='SOFT' and not row.interrupt_dj
        form['revision']=str(row.revision)
    form.update(recurrence_type='DAILY',weekdays=[],repeat_hours=[],local_date='invalid',month_day='invalid')
    assert client.get(base+'/preview',query_string=form).status_code==200
    assert client.post(base+'/'+identifier+'/edit',data=form).status_code==303
    with app.app_context():
        row=m.TimedEvent.query.filter_by(uuid=identifier).one()
        assert row.recurrence_type=='DAILY' and row.repeat_hours is None
    assert client.post(base+'/'+identifier+'/disable',data={'csrf':form['csrf']}).status_code==303


def test_sparse_and_distant_previews_and_range_end(app):
    with app.app_context():
        station,_=audio()
        rule=events.recurrence_rule(station,'MONTHLY',local_time='12:00',month_nth=5,month_weekday=0)
        assert len(events.next_instants(rule))==10
        rule=events.recurrence_rule(station,'ONE_TIME',local_time='12:00',local_date='2040-02-01')
        assert events.next_instants(rule)==[datetime(2040,2,1,12,tzinfo=timezone.utc)]
        rule=events.recurrence_rule(station,'MONTHLY',local_time='12:00',starts_on='2028-02-01',ends_on='2028-03-31',month_day=31)
        assert events.next_instants(rule)==[datetime(2028,3,31,12,tzinfo=timezone.utc)]


@pytest.mark.parametrize('kind',['DAILY','MONTHLY'])
def test_hidden_values_cannot_reject_valid_rule(app,kind):
    with app.app_context():
        station,_=audio()
        rule=events.recurrence_rule(station,kind,local_time='12:00',weekdays=[],repeat_hours=[],local_date='invalid')
        assert rule.repeat_days==list(range(7)) and rule.repeat_hours is None


def test_starter_order_is_stable_and_custom_names_are_preserved(app):
    from app.services.playlists import seed_playlists,listing,membership,delete_playlist
    with app.app_context():
        station,track=audio()
        custom=m.Playlist(station_id=station.id,name='STATION');db.session.add(custom);db.session.flush()
        seed_playlists(station.id);seed_playlists(station.id);db.session.commit()
        rows=listing(station.id)
        assert [r.system_key for r in rows]==['PLAYLIST_1','PLAYLIST_2','STATION','COMMERCIALS',None]
        assert rows[-1].id==custom.id
        rows[0].name='Morning mix';db.session.commit()
        assert listing(station.id)[0].name=='Morning mix'
        membership(rows[0],[track],'add',1)
        assert track.audio_kind=='MUSIC'
        delete_playlist(rows[1]);db.session.commit()
        with pytest.raises(ValueError):delete_playlist(rows[2])


def test_dates_seconds_and_zone_are_visible_in_history(app):
    client=admin_client(app)
    with app.app_context():
        station,track=audio();station.timezone='Asia/Kathmandu'
        now=datetime.now(timezone.utc)
        local=(now+timedelta(days=2)).astimezone(ZoneInfo(station.timezone)).replace(hour=10,minute=20,second=37)
        row=events.save_event(station.slug,name='Visible date',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,local_date=local.date().isoformat(),local_time='10:20:37')
        identifier=row.uuid
    page=client.get('/admin/stations/test-station/events/'+identifier).get_data(as_text=True)
    assert local.strftime('%d %b %Y') in page and '10:20:37' in page and '+0545' in page


def test_search_album_pagination_and_unavailable_sequences(app):
    from app.services.event_search import search
    with app.app_context():
        station,track=audio();track.album='Campaign collection';classify(track,'COMMERCIALS')
        for i in range(35):db.session.add(m.Playlist(station_id=station.id,name=f'Custom {i:02}'))
        block=m.EventBlock(station_id=station.id,name='Invalid sequence',slug='invalid',enabled=True)
        db.session.add(block);db.session.commit()
        first=search(station);second=search(station,page=2)
        assert [r['name'] for r in first['items'][:2]]==['STATION','COMMERCIALS']
        keys=lambda data:{(r['kind'],r['identifier']) for r in data['items']}
        assert not keys(first)&keys(second)
        assert len(keys(first)|keys(second))==38
        assert search(station,query='Campaign collection')['items'][0]['identifier']==track.uuid
        assert not search(station,kind='EVENT_BLOCK')['items'][0]['playable']
        other=m.Station.query.filter_by(slug='second-station').one()
        with pytest.raises(ValueError):search(other,playlist_id=defaults(station.id)['COMMERCIALS'].id)


def test_stale_backlog_does_not_hide_due_event(app):
    with app.app_context():
        station,track=audio()
        row=events.save_event(station.slug,name='Frequent',recurrence_type='QUARTER_HOUR',content_type='TRACK',content_identifier=track.uuid,local_time='00:00')
        now=datetime.now(timezone.utc)
        row.generated_until=None;db.session.commit()
        events.generate_occurrences(station,now-timedelta(days=8))
        assert len(events.upcoming(station,limit=2000))>500
        reserved=events.upcoming(station,limit=1)[0];reserved.boundary_reserved=True;db.session.commit()
        events.expire_due(station,now)
        assert reserved.state=='PENDING'
        pending=[o for o in events.upcoming(station,limit=2000) if events.aware(o.scheduled_for_utc)<=now and not o.boundary_reserved]
        assert len(pending)<=1
        assert m.TimedEventOccurrence.query.filter_by(timed_event_id=row.id,state='MISSED').count()>500


def test_partial_and_all_failed_runs_have_distinct_outcomes(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    with app.app_context():
        station,track=audio();classify(track,'STATION');db.session.commit()
        row=events.save_event(station.slug,name='ID',recurrence_type='DAILY',content_type='PLAYLIST',content_identifier=defaults(station.id)['STATION'].id,local_time='12:00')
        run=create_playlist_execution(row.occurrences[-1]);run.items[0].state='FAILED'
        finish_execution(run,datetime.now(timezone.utc))
        assert run.state==row.occurrences[-1].state=='FAILED'
        run.items[0].state='COMPLETED'
        run.items.append(m.EventBlockItemExecution(position=2,item_type='TRACK',track=track,state='FAILED',failure_policy='SKIP_FAILED_ITEM'))
        finish_execution(run,datetime.now(timezone.utc))
        assert run.state=='COMPLETED' and row.occurrences[-1].failure_reason=='partial_playback'
        db.session.commit()
    result=app.test_cli_runner().invoke(args=['block','executions','--station','test-station'])
    assert result.exit_code==0 and 'STATION' in result.output
    result=app.test_cli_runner().invoke(args=['block','add','--help'])
    assert 'imaging' not in result.output


def test_cancellation_recovers_lost_acceptance_by_annotation(app,monkeypatch):
    from app import automation_worker as worker
    calls=[]
    def command(slug,text):
        calls.append(text)
        return '|WAITING' if text=='freo_event.state' else '42' if text=='freo_event.queue' else 'OK'
    monkeypatch.setattr('app.services.playout_queue._command',command)
    monkeypatch.setattr(worker,'queued_ids',lambda s:{77})
    monkeypatch.setattr(worker,'socket_identity',lambda s:'engine')
    with app.app_context():
        station,track=audio()
        decision=m.SelectionDecision(station_id=station.id,track_id=track.id,status='submitting')
        db.session.add(decision);db.session.flush()
        monkeypatch.setattr(worker,'request_decision_id',lambda s,r:decision.id if r==42 else 99999)
        db.session.add(m.EventQueueCancellation(decision_id=decision.id,station_id=station.id));db.session.commit()
        worker.process_event_cancellations(station)
        assert 'freo_event.remove 42' in calls and 'freo_queue.remove 77' not in calls
        assert decision.status=='failed'


def test_event_can_precede_operator_queued_audio_but_not_another_event(app,monkeypatch):
    from app import automation_worker as worker
    monkeypatch.setattr(worker,'queued_ids',lambda s:{42})
    monkeypatch.setattr(worker,'socket_identity',lambda s:'engine')
    with app.app_context():
        station,track=audio()
        row=m.SelectionDecision(station_id=station.id,track_id=track.id,admin_user_id=1,
            selection_method='manual_track',status='queued',socket_identity='engine',liquidsoap_request_id=42)
        db.session.add(row);db.session.commit()
        assert worker.automatic_future_only(station)
        row.selection_method='event_block';db.session.commit()
        assert not worker.automatic_future_only(station)


def test_timezone_cli_rebuilds_unstarted_occurrences(app):
    from app.services.clocks import set_timezone
    with app.app_context():
        station,track=audio()
        row=events.save_event(station.slug,name='Local',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='12:00')
        old=list(row.occurrences)
        set_timezone(station.slug,'Pacific/Auckland')
        assert all(o.state=='CANCELLED' for o in old)
        assert row.local_time.hour==12


def test_manual_cancellation_survives_definition_edits(app):
    with app.app_context():
        station,track=audio()
        row=events.save_event(station.slug,name='Cancelled run',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='12:00')
        occurrence=row.occurrences[-1]
        events.cancel_occurrence(occurrence,user=True);db.session.commit()
        events.save_event(station.slug,identifier=row.uuid,name='Renamed',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='12:00')
        assert occurrence.state=='CANCELLED' and occurrence.cancelled_by_user


def test_starter_migration_preserves_custom_and_renamed_playlists(app):
    with app.app_context():
        station,_=audio()
        for name in ('Playlist 1','Playlist 2','STATION'):
            db.session.add(m.Playlist(station_id=station.id,name=name))
        db.session.commit()
    runner=app.test_cli_runner()
    assert runner.invoke(args=['db','stamp','e28a91bc7304']).exit_code==0
    # This fixture already has the current schema. Exercise only the data
    # migration under test, not later migrations that add existing columns.
    result=runner.invoke(args=['db','upgrade','f38c6a902e17'])
    assert result.exit_code==0,result.output
    with app.app_context():
        rows=m.Playlist.query.order_by(m.Playlist.id).all()
        assert [r.system_key for r in rows]==['PLAYLIST_1','PLAYLIST_2',None]
        assert rows[-1].name=='STATION'


def test_engine_restart_finishes_interrupted_event_without_erasing_start(app,monkeypatch):
    from app import automation_worker as worker
    monkeypatch.setattr(worker,'socket_identity',lambda s:'new-engine')
    monkeypatch.setattr(worker,'active_ids',lambda s:set())
    monkeypatch.setattr(worker,'queued_ids',lambda s:set())
    monkeypatch.setattr('app.services.playout_queue._command',lambda *a:'')
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *a:[])
    with app.app_context():
        station,track=audio()
        row=events.save_event(station.slug,name='Interrupted',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='12:00')
        occurrence=row.occurrences[-1]
        occurrence.selection_decision=m.SelectionDecision(station_id=station.id,track_id=track.id,
            status='started',selection_method='timed_event',socket_identity='old-engine',started_at=datetime.now(timezone.utc))
        occurrence.state='STARTED';db.session.commit()
        worker.reconcile_requests(station.slug)
        assert occurrence.state=='FAILED' and occurrence.failure_reason=='playout_restarted'
        assert occurrence.selection_decision.status=='started'
        worker.process_timed_events(station,worker.EventReader())
        assert occurrence.state=='FAILED' and occurrence.failure_reason=='playout_restarted'


def test_lost_end_fails_only_absent_event_audio_and_preserves_history(app,monkeypatch):
    from app import automation_worker as worker
    monkeypatch.setattr(worker,'socket_identity',lambda s:'engine')
    active={42}
    monkeypatch.setattr(worker,'active_ids',lambda s:active)
    monkeypatch.setattr(worker,'queued_ids',lambda s:set())
    monkeypatch.setattr('app.services.playout_queue._command',lambda *a:'')
    monkeypatch.setattr('app.services.playout_queue.channel_queue',lambda *a:[])
    with app.app_context():
        station,track=audio()
        row=events.save_event(station.slug,name='Missing END',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='12:00')
        occurrence=row.occurrences[-1]
        occurrence.selection_decision=m.SelectionDecision(station_id=station.id,track_id=track.id,
            status='started',selection_method='timed_event',socket_identity='engine',liquidsoap_request_id=42,
            started_at=datetime.now(timezone.utc)-timedelta(milliseconds=track.duration_ms,seconds=180))
        occurrence.state='STARTED';db.session.commit()
        worker.reconcile_requests(station.slug)
        assert occurrence.state=='STARTED'  # Paused/active audio still owns its request.
        active.clear()
        worker.reconcile_requests(station.slug)
        assert occurrence.state=='FAILED' and occurrence.failure_reason=='missing_end_confirmation'
        assert occurrence.selection_decision.status=='started'
        worker.process_timed_events(station,worker.EventReader())
        assert occurrence.state=='FAILED'


@pytest.mark.parametrize('outcome', ['confirmed', 'vanished', 'reappeared', 'incomplete', 'restarted'])
def test_queued_event_waits_for_rendered_confirmation(app, monkeypatch, outcome):
    from app import automation_worker as worker
    from app.services.automation import playback_started
    observed = [100.0]
    identity = ['engine']
    active = set()
    monkeypatch.setattr(worker.time, 'monotonic', lambda: observed[0])
    monkeypatch.setattr(worker, 'socket_identity', lambda s: identity[0])
    monkeypatch.setattr(worker, 'active_ids', lambda s: active)
    monkeypatch.setattr(worker, 'queued_ids', lambda s: set())
    monkeypatch.setattr('app.services.playout_queue._command', lambda *a: '')
    monkeypatch.setattr('app.services.playout_queue.channel_queue', lambda *a: [])
    with app.app_context():
        station, track = audio()
        event = events.save_event(station.slug, name='Rendered confirmation', recurrence_type='DAILY',
            content_type='TRACK', content_identifier=track.uuid, local_time='12:00')
        occurrence = event.occurrences[-1]
        decision = m.SelectionDecision(station_id=station.id, track_id=track.id, status='queued',
            selection_method='timed_event', socket_identity='engine', liquidsoap_request_id=42)
        occurrence.selection_decision = decision
        occurrence.state = 'QUEUED'
        db.session.commit()
        assert worker.reconcile_requests(station.slug) == 0
        assert occurrence.state == 'QUEUED'
        observed[0] += 4
        if outcome == 'confirmed':
            playback_started(decision.id, station.slug)
        elif outcome == 'reappeared':
            active.add(42)
        elif outcome == 'incomplete':
            def unavailable(*args):
                raise OSError('socket unavailable')
            monkeypatch.setattr('app.services.playout_queue.channel_queue', unavailable)
        elif outcome == 'restarted':
            identity[0] = 'new-engine'
        worker.reconcile_requests(station.slug)
        if outcome == 'restarted':
            assert occurrence.state == 'FAILED' and occurrence.failure_reason == 'playout_restarted'
        elif outcome == 'confirmed':
            assert occurrence.state == 'STARTED' and occurrence.failure_reason is None
            assert decision.reason != 'late_event_confirmation'
        else:
            assert occurrence.state == 'QUEUED'
            active.clear()
            observed[0] = 110.0
            worker.reconcile_requests(station.slug)
            if outcome == 'vanished':
                assert occurrence.state == 'FAILED' and occurrence.failure_reason == 'request_not_started'
            else:
                assert occurrence.state == 'QUEUED'
        if outcome in ('confirmed', 'vanished', 'restarted', 'incomplete'):
            assert station.slug not in app.extensions['playout_missing_requests']


@pytest.mark.parametrize('zone,day,expected',[('Australia/Lord_Howe','2027-10-03',94),('Australia/Lord_Howe','2027-04-04',96)])
def test_half_hour_dst_intervals_do_not_duplicate(app,zone,day,expected):
    with app.app_context():
        station,_=audio();station.timezone=zone
        rule=events.recurrence_rule(station,'QUARTER_HOUR',local_time='00:00',starts_on=day,ends_on=day)
        start=datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)
        assert len(events._instants(rule,start,start+timedelta(days=2)))==expected
