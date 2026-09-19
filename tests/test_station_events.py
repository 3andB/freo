"""Behavioral coverage for unified audio and station-local playlist events."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import uuid
import pytest
from app.extensions import db
from app import models as m
from app.services import timed_events as events
from app.services.audio_classification import classify, defaults
from app.services.event_blocks import create_playlist_execution, prepare_next, confirm_item_started, confirm_finished
from app.services.availability import available, tracks_for
from tests.test_web import app, admin_client


def station_audio():
    station=m.Station.query.filter_by(slug='test-station').one()
    station.timezone='UTC'
    return station,m.Track.query.first()


def event(station,track,kind='DAILY',**kwargs):
    return events.save_event(station.slug,name='Station event',timing_mode='SOFT',recurrence_type=kind,content_type='TRACK',content_identifier=track.uuid,local_time='10:05:00',**kwargs)


def utc(text):return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize('kind,count', [('QUARTER_HOUR',96),('HOURLY',24),('DAILY',1),('WEEKLY',1)])
def test_recurrence_has_fixed_local_targets(app,kind,count):
    with app.app_context():
        station,track=station_audio();station.timezone='Asia/Kathmandu'
        row=event(station,track,kind,weekdays=[0],starts_on='2027-01-04',ends_on='2027-01-04')
        times=events._instants(row,utc('2027-01-03T18:15'),utc('2027-01-04T18:15'))
        assert len(times)==count and len(set(times))==count
        assert {t.astimezone(ZoneInfo(station.timezone)).second for t in times}=={0}
        if kind=='QUARTER_HOUR': assert {t.astimezone(ZoneInfo(station.timezone)).minute for t in times}=={5,20,35,50}


def test_monthly_short_month_and_ordinal(app):
    with app.app_context():
        station,track=station_audio()
        row=event(station,track,'MONTHLY',month_day=31)
        assert [x.date().isoformat() for x in events._instants(row,utc('2028-02-01'),utc('2028-04-01'))]==['2028-03-31']
        row.month_nth=-1;row.month_weekday=4
        assert [x.date().isoformat() for x in events._instants(row,utc('2028-02-01'),utc('2028-03-01'))]==['2028-02-25']


def test_quarter_hour_dst_is_deduplicated(app):
    with app.app_context():
        station,track=station_audio();station.timezone='America/Denver'
        row=event(station,track,'QUARTER_HOUR',starts_on='2027-03-14',ends_on='2027-03-14')
        times=events._instants(row,utc('2027-03-14'),utc('2027-03-16'))
        assert len(times)==92 and len(set(times))==92
        row.starts_on=row.ends_on=datetime(2027,11,7).date()
        times=events._instants(row,utc('2027-11-07'),utc('2027-11-09'))
        assert len(times)==96


def test_classification_collections_and_station_privacy(app):
    from app.services.media import approved_tracks
    with app.app_context():
        station,track=station_audio();other=m.Station.query.filter_by(slug='second-station').one()
        track.available_to_all=True;db.session.commit()
        assert available(track,other.id)
        classify(track,'STATION','station_id');db.session.commit()
        assert not available(track,other.id)
        assert not tracks_for(other.id).filter_by(id=track.id).first()
        assert track not in approved_tracks(station.slug)
        assert [i.track_id for i in defaults(station.id)['STATION'].items]==[track.id]
        classify(track,'COMMERCIALS');db.session.commit()
        assert not defaults(station.id)['STATION'].items
        assert [i.track_id for i in defaults(station.id)['COMMERCIALS'].items]==[track.id]


def test_playlist_snapshot_and_confirmed_cursor(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    with app.app_context():
        station,track=station_audio();classify(track,'STATION','station_id');db.session.commit()
        playlist=defaults(station.id)['STATION']
        row=events.save_event(station.slug,name='IDs',recurrence_type='DAILY',content_type='PLAYLIST',content_identifier=playlist.id,local_time='10:00')
        occurrence=row.occurrences[-1]
        execution=create_playlist_execution(occurrence);db.session.commit()
        assert create_playlist_execution(occurrence).id==execution.id
        assert not row.playlist_state and execution.playlist_revision==playlist.revision
        item=prepare_next(execution);item.selection_decision.status='started'
        confirm_item_started(item.selection_decision,datetime.now(timezone.utc));db.session.commit()
        assert row.playlist_state['last']==track.id and occurrence.state=='STARTED'
        item.selection_decision.socket_identity='engine'
        confirm_finished(station,item.selection_decision.id,datetime.now(timezone.utc),'engine')
        assert execution.state=='COMPLETED' and occurrence.state=='COMPLETED'


def test_edit_prepared_audio_clears_old_decision_and_cancellation_is_durable(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    with app.app_context():
        station,track=station_audio();row=event(station,track)
        occurrence=row.occurrences[-1];old=events.prepare_decision(occurrence)
        events.save_event(station.slug,identifier=row.uuid,revision=row.revision,name='Changed',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='10:05')
        assert occurrence.state=='PENDING' and occurrence.selection_decision is None
        assert old.status=='failed'
        events.cancel_occurrence(occurrence,user=True);row.generated_until=None;db.session.commit()
        events.generate_occurrences(station)
        assert occurrence.state=='CANCELLED'


def test_timezone_change_rebuilds_future_only(app):
    with app.app_context():
        station,track=station_audio()
        row=event(station,track,'ONE_TIME',local_date='2028-02-01')
        events.generate_occurrences(station,utc('2028-01-31'))
        old=row.occurrences[0]
        station.timezone='Pacific/Auckland';events.timezone_changed(station,'UTC');db.session.commit()
        assert old.state=='CANCELLED'
        assert events.aware(row.scheduled_at_utc).astimezone(ZoneInfo(station.timezone)).hour==10
        events.generate_occurrences(station,utc('2028-01-31'))
        assert len([o for o in row.occurrences if o.state=='PENDING'])==1


def test_event_search_priority_filters_and_preview(app):
    client=admin_client(app)
    with app.app_context():
        station,track=station_audio();classify(track,'STATION','station_id');db.session.commit()
    base='/admin/stations/test-station/events'
    assert client.get(base+'/create').status_code==200
    data=client.get(base+'/audio').json
    assert [r['name'] for r in data['items'][:2]]==['STATION','COMMERCIALS']
    assert client.get(base+'/audio?q=station_id').json['items'][0]['kind']=='TRACK'
    assert not client.get('/admin/stations/second-station/events/audio?q=station_id').json['items']
    preview=client.get(base+'/preview?recurrence_type=MONTHLY&month_day=31&local_time=10:00&starts_on=2028-02-01').json
    assert len(preview['times'])==10 and 'UTC' in preview['summary']


def test_imaging_conversion_preserves_audio_and_references(app,tmp_path,monkeypatch):
    from app.services.media_storage import LocalMediaStorage
    from app.services.imaging_migration import convert,inventory
    monkeypatch.setattr('app.services.imaging_migration.grant_playout_read',lambda p:None)
    with app.app_context():
        station,track=station_audio();station.desired_state='stopped'
        key='b'*32+'.mp3';directory=tmp_path/station.slug/'imaging';directory.mkdir(parents=True);(directory/key).write_bytes(b'test audio')
        asset=m.ImagingAsset(station_id=station.id,uuid=str(uuid.uuid4()),name='Station ID',asset_type='STATION_ID',original_filename='id.mp3',storage_key=key,media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=10,checksum_sha256=hashlib.sha256(b'test audio').hexdigest(),enabled=True,ingest_status='accepted')
        db.session.add(asset);db.session.commit()
        row=m.TimedEvent(uuid=str(uuid.uuid4()),station_id=station.id,name='ID',recurrence_type='DAILY',content_type='IMAGING_ASSET',imaging_asset_id=asset.id,local_time=datetime.strptime('12:00','%H:%M').time(),timing_mode='SOFT',weekday=0)
        db.session.add(row);db.session.commit()
        report=convert(station,LocalMediaStorage(tmp_path))
        assert report['converted']==1 and all(n==0 for n in report['references'].values())
        db.session.refresh(row)
        assert row.content_type=='TRACK' and row.track.audio_subtype=='station_id'
        assert LocalMediaStorage(tmp_path).regular_file(station.slug,row.track.storage_key).read_bytes()==b'test audio'
        assert (directory/key).exists()
        assert convert(station,LocalMediaStorage(tmp_path))['converted']==1


def test_long_song_does_not_expire_next_boundary_event(app,monkeypatch):
    from app import automation_worker as worker
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    monkeypatch.setattr(worker,'socket_identity',lambda s:'engine')
    monkeypatch.setattr(worker,'active_ids',lambda s:{1})
    monkeypatch.setattr(worker,'queue_depth',lambda s:0)
    monkeypatch.setattr(worker,'push_decision',lambda d:99)
    monkeypatch.setattr(worker,'interrupt_for_event',lambda s:pytest.fail('must finish current song'))
    with app.app_context():
        station,track=station_audio();track.duration_ms=900000
        now=datetime.now(timezone.utc);current=m.SelectionDecision.query.filter_by(status='started').first()
        current.started_at=now;current.socket_identity='engine';current.liquidsoap_request_id=1;db.session.commit()
        row=events.save_event(station.slug,name='After long song',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,local_date=now.date().isoformat(),local_time=now.strftime('%H:%M:%S'),late_tolerance_seconds=10)
        worker.process_timed_events(station,worker.EventReader(),now)
        assert row.occurrences[0].state=='QUEUED' and row.occurrences[0].boundary_reserved
        worker.process_timed_events(station,worker.EventReader(),now+timedelta(minutes=10))
        assert row.occurrences[0].state=='QUEUED'


def test_atomic_playlist_submission_uses_saved_order(app,monkeypatch):
    from app.services.event_blocks import submit_snapshot
    from app.services.playlists import replace_order
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda s:'engine')
    submitted=[]
    monkeypatch.setattr('app.services.playout_queue.push_sequence',lambda rows:submitted.append([r.track_id for r in rows]) or list(range(90,90+len(rows))))
    with app.app_context():
        station,track=station_audio();classify(track,'COMMERCIALS')
        other=m.Track(station_id=station.id,uuid=str(uuid.uuid4()),title='Second ad',artist=station.name,original_filename='ad.mp3',storage_key='d'*32+'.mp3',media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=10,enabled=True,ingest_status='accepted')
        db.session.add(other);db.session.flush();classify(other,'COMMERCIALS');db.session.commit()
        playlist=defaults(station.id)['COMMERCIALS']
        row=events.save_event(station.slug,name='Break',recurrence_type='DAILY',content_type='PLAYLIST',content_identifier=playlist.id,local_time='12:00')
        occurrence=row.occurrences[-1];execution=create_playlist_execution(occurrence)
        replace_order(playlist,[other.id,track.id]);db.session.commit()
        submit_snapshot(execution,datetime.now(timezone.utc))
        assert submitted==[[track.id,other.id]]
        assert all(i.state=='QUEUED' for i in execution.items) and occurrence.state=='QUEUED'


def test_dj_permission_defaults_no_and_reserves_only_when_enabled(app,monkeypatch):
    from app import automation_worker as worker
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    monkeypatch.setattr('app.services.playout_queue.event_bus',lambda slug,operation='state',occurrence_id=None:calls.append(operation) or ('|WAITING' if operation=='state' else 'OK'))
    monkeypatch.setattr('app.services.playout_queue.mixer_state',lambda s:{'cart_id':None})
    monkeypatch.setattr(worker,'push_decision',lambda d:90)
    monkeypatch.setattr(worker,'socket_identity',lambda s:'engine')
    with app.app_context():
        station,track=station_audio();now=datetime.now(timezone.utc)
        row=events.save_event(station.slug,name='DJ ID',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,local_date=now.date().isoformat(),local_time=now.strftime('%H:%M:%S'))
        reader=SimpleNamespace(collect=lambda s:None)
        assert not row.interrupt_dj and not worker.process_dj_events(station,reader,now)
        assert 'arm' not in calls
        row.interrupt_dj=True;db.session.commit()
        assert worker.process_dj_events(station,reader,now)
        assert calls[-1]=='arm' and row.occurrences[0].boundary_reserved
        assert row.occurrences[0].runtime['dj'] and row.occurrences[0].state=='QUEUED'


def test_recovered_snapshot_does_not_submit_twice(app,monkeypatch):
    from app import automation_worker as worker
    from app.services.event_blocks import submit_snapshot
    from types import SimpleNamespace
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *a:'/safe')
    monkeypatch.setattr('app.services.playout_queue.socket_identity',lambda s:'engine')
    monkeypatch.setattr('app.services.playout_queue.push_sequence',lambda rows:list(range(90,90+len(rows))))
    monkeypatch.setattr(worker,'reconcile_requests',lambda s:None)
    with app.app_context():
        station,track=station_audio();classify(track,'STATION');db.session.commit()
        row=events.save_event(station.slug,name='Recover',recurrence_type='DAILY',content_type='PLAYLIST',content_identifier=defaults(station.id)['STATION'].id,local_time='12:00')
        execution=create_playlist_execution(row.occurrences[-1]);now=datetime.now(timezone.utc)
        submit_snapshot(execution,now)
        execution.state='PENDING'
        for item in execution.items:item.state='PENDING'
        db.session.commit()
        monkeypatch.setattr('app.services.playout_queue.push_sequence',lambda rows:pytest.fail('Recovered requests must not be resubmitted'))
        assert worker.process_block(station,SimpleNamespace(collect=lambda s:None),now)
        assert execution.state=='QUEUED' and all(i.state=='QUEUED' for i in execution.items)


def test_cancel_pending_dj_event_clears_engine_token(app,monkeypatch):
    from app import automation_worker as worker
    calls=[]
    def command(slug,command):
        calls.append(command)
        return '123|WAITING' if command=='freo_event.state' else '90' if command=='freo_event.queue' else 'OK'
    monkeypatch.setattr('app.services.playout_queue._command',command)
    monkeypatch.setattr(worker,'socket_identity',lambda s:'engine')
    monkeypatch.setattr(worker,'queued_ids',lambda s:set())
    with app.app_context():
        station,track=station_audio()
        decision=m.SelectionDecision(station_id=station.id,track_id=track.id,status='queued',socket_identity='engine',liquidsoap_request_id=90)
        db.session.add(decision);db.session.flush()
        job=m.EventQueueCancellation(decision_id=decision.id,station_id=station.id)
        db.session.add(job);db.session.commit()
        worker.process_event_cancellations(station)
        assert 'freo_event.cancel 123' in calls and job.processed and decision.status=='failed'


def test_duration_overlap_and_repeat_warning(app):
    with app.app_context():
        station,track=station_audio();track.duration_ms=1200000;db.session.commit()
        first=event(station,track,'QUARTER_HOUR')
        events.save_event(station.slug,name='Nearby',recurrence_type='DAILY',content_type='TRACK',content_identifier=track.uuid,local_time='10:06')
        warnings=events.conflict_warnings(first)
        assert any('longer than the repeat' in w for w in warnings)
        assert any('Nearby' in w for w in warnings)


def test_one_time_dst_input_survives_timezone_change(app):
    with app.app_context():
        station,track=station_audio();station.timezone='America/Denver'
        row=events.save_event(station.slug,name='Gap',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=track.uuid,local_date='2028-03-12',local_time='02:30')
        assert events.aware(row.scheduled_at_utc).astimezone(ZoneInfo(station.timezone)).hour==3
        station.timezone='UTC';events.timezone_changed(station,'America/Denver');db.session.commit()
        assert events.aware(row.scheduled_at_utc)==utc('2028-03-12T02:30')


def test_occurrence_pages_and_cancel_are_station_scoped(app):
    client=admin_client(app)
    with app.app_context():
        station,track=station_audio();row=event(station,track,'QUARTER_HOUR');identifier=row.uuid
        occurrence=row.occurrences[-1];occurrence_id=occurrence.id
    base=f'/admin/stations/test-station/events/{identifier}'
    assert b'Cancel occurrence' in client.get(base).data
    assert b'Next' in client.get(base).data
    assert client.post(base+f'/occurrences/{occurrence_id}/cancel').status_code==400
    assert client.post(f'/admin/stations/second-station/events/{identifier}/occurrences/{occurrence_id}/cancel',data={'csrf':'test-admin-csrf-token'}).status_code==404
    assert client.post(base+f'/occurrences/{occurrence_id}/cancel',data={'csrf':'test-admin-csrf-token'}).status_code==303
    assert b'cancelled_by_user' in client.get(base+'?view=history').data
