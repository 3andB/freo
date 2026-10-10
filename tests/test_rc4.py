"""Release acceptance for station discovery, hourly inserts and durable shuffle."""
from datetime import datetime, timezone, timedelta
from io import BytesIO
from types import SimpleNamespace
import struct
import zlib
import pytest
from app.extensions import db
from app.models import Station, WebsiteSettings, WebsitePublication, WebsiteAsset
from app.services import playlists, visual_schedule as vs, website, timed_events
from tests.test_web import app, admin_client
from tests.test_homepage import form
from tests.test_playlists import setup_playlist


def png(color):
    def chunk(kind, data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data))
    rgb = b'\xff\x00\x00' if color=='red' else b'\x00\x00\xff'
    return BytesIO(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',80,40,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+rgb*80)*40))+chunk(b'IEND',b''))


def test_shuffle_cycles_boundary_membership_and_single_track():
    tracks=[SimpleNamespace(id=i) for i in range(7)]
    state={};played=[]
    for _ in range(70):
        track,state=playlists.advance(SimpleNamespace(mode='RANDOM'),tracks,state);played.append(track.id)
    for i in range(0,70,7):assert len(set(played[i:i+7]))==7
    assert all(a!=b for a,b in zip(played,played[1:]))
    track,state=playlists.advance(SimpleNamespace(mode='RANDOM'),tracks[:1],state)
    assert track.id==0 and state['played']==[0]


def test_random_source_survives_block_occurrences_and_session_restart(app,monkeypatch):
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        station,playlist,tracks=setup_playlist();playlist.mode='RANDOM';db.session.commit()
        ref=vs.source(station,dict(kind='playlist',id=playlist.id));station_id=station.id
        picked=[]
        for index in range(12):
            station=db.session.get(Station,station_id)
            resolved=dict(source=ref,key=f'daily-block-{index}',insert=None,mode='BLOCKS')
            decision=vs.select_visual(station,resolved,None,datetime.now(timezone.utc))
            picked.append(decision.track_id);db.session.commit();db.session.remove()
        for i in range(0,12,4):assert len(set(picked[i:i+4]))==4
        assert all(a!=b for a,b in zip(picked,picked[1:]))


def test_channel_image_draft_publish_replace_remove_restore(app):
    client=admin_client(app);anon=app.test_client()
    with app.app_context():key=f'channel_image_{Station.query.first().id}'
    data=form(app);data[key]=(png('red'),'red.png')
    assert client.post('/admin/website',data=data).status_code==303
    with app.app_context():
        identifier=website.config(True)[key];path=f'/website-assets/{identifier}.png'
        assert db.session.get(WebsiteAsset,identifier)
    assert anon.get(path).status_code==404
    assert client.get(path+'?preview=1').status_code==200
    assert client.post('/admin/website',data=form(app,action='publish')).status_code==303
    assert path in anon.get('/').text
    with app.app_context():publication=WebsitePublication.query.order_by(WebsitePublication.id.desc()).first().id
    data=form(app);data[key]=(png('blue'),'blue.png')
    assert client.post('/admin/website',data=data).status_code==303
    assert path in anon.get('/').text
    data=form(app,action='publish');data['remove_'+key]='yes'
    assert client.post('/admin/website',data=data).status_code==303
    assert path not in anon.get('/').text
    assert client.post('/admin/website',data=form(app,action='restore',publication=str(publication))).status_code==303
    assert path in anon.get('/').text and anon.get(path).status_code==200


def test_timezone_dropdowns_and_hourly_shortcuts(app):
    client=admin_client(app)
    for path in ['/admin/stations','/admin/stations/test-station/settings','/admin/stats']:
        response=client.get(path,follow_redirects=True)
        assert response.status_code==200
        assert '<select name="timezone"' in response.text
        assert 'Australia/Perth — Perth' in response.text
    for workspace in ['calendar','blocks','simple']:
        response=client.get('/admin/stations/test-station/schedule-studio/'+workspace)
        assert response.status_code==200 and 'recurrence=hourly' in response.text


def test_hourly_minute_preview_validation_and_dst(app):
    from app.routes.admin_events import event_local_time
    assert event_local_time(dict(recurrence_type='HOURLY',hourly_minute='10'))=='00:10:00'
    for minute in ['-1','60','oops']:
        with pytest.raises(ValueError):event_local_time(dict(recurrence_type='HOURLY',hourly_minute=minute))
    with app.app_context():
        station=Station.query.first();station.timezone='America/New_York'
        rule=timed_events.recurrence_rule(station,'HOURLY',local_time='00:10:00')
        start=datetime(2026,9,22,tzinfo=timezone.utc)
        values=timed_events._instants(rule,start,start+timedelta(days=1)-timedelta(seconds=1))
        assert len(values)==24 and all(v.minute==10 for v in values)
        for day in [datetime(2026,3,8,tzinfo=timezone.utc),datetime(2026,11,1,tzinfo=timezone.utc)]:
            values=timed_events._instants(rule,day,day+timedelta(days=1))
            assert len(values)==len(set(values)) and all(v.minute==10 for v in values)
    client=admin_client(app)
    response=client.get('/admin/stations/test-station/events/preview',query_string=[('recurrence_type','HOURLY'),('hourly_minute','10'),*[('repeat_hours',str(hour)) for hour in range(24)]])
    assert response.status_code==200 and len(response.json['times'])==10
    assert all(':10:00' in value for value in response.json['times'])
    from app.models import Track, TimedEvent
    with app.app_context():identifier=Track.query.first().uuid
    saved=client.post('/admin/stations/test-station/events/create',data=dict(
        csrf='test-admin-csrf-token',name='Ten past',recurrence_type='HOURLY',
        hourly_minute='10',local_time='00:00:00',repeat_hours=[str(hour) for hour in range(24)],
        content_type='TRACK',content_identifier=identifier,playlist_playback='ONE'))
    assert saved.status_code==303
    with app.app_context():
        event=TimedEvent.query.filter_by(name='Ten past').one()
        assert event.local_time.minute==10 and event.local_time.second==0
        assert len(event.repeat_hours)==24


def test_finite_random_run_after_partial_cycle():
    tracks=[SimpleNamespace(id=i) for i in range(6)]
    row=SimpleNamespace(mode='RANDOM');state={}
    for _ in range(2):_,state=playlists.advance(row,tracks,state)
    for _ in range(20):
        run=[]
        for index in range(len(tracks)):
            song,state=playlists.advance(row,tracks,state,exclude=set(run));run.append(song.id)
        assert len(set(run))==len(tracks)


def test_random_event_cursor_advances_on_each_confirmed_item(app,monkeypatch):
    from app.models import SelectionDecision
    from app.services.event_blocks import create_playlist_execution, confirm_item_started
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        station,playlist,tracks=setup_playlist();playlist.mode='RANDOM'
        event=timed_events.save_event(station.slug,name='Hourly shuffle',recurrence_type='HOURLY',
            content_type='PLAYLIST',content_identifier=playlist.id,local_time='00:10',playlist_playback='ALL')
        run=create_playlist_execution(event.occurrences[0]);db.session.flush()
        assert len({item.track_id for item in run.items})==len(tracks)
        assert not event.playlist_state
        first=run.items[0]
        decision=SelectionDecision(station_id=station.id,track_id=first.track_id,status='started')
        db.session.add(decision);db.session.flush();first.selection_decision_id=decision.id;db.session.flush()
        confirm_item_started(decision,datetime.now(timezone.utc))
        assert event.playlist_state['played']==[first.track_id]
        db.session.commit()


def test_visual_cursor_preserves_previous_release_progress(app,monkeypatch):
    import hashlib,json
    from app.models import ScheduleCursor
    monkeypatch.setattr('app.services.automation._exists',lambda *a:True)
    with app.app_context():
        station,playlist,tracks=setup_playlist()
        ref=vs.source(station,dict(kind='playlist',id=playlist.id))
        key=hashlib.sha256(('legacy'+json.dumps(ref,sort_keys=True)).encode()).hexdigest()
        db.session.add(ScheduleCursor(station_id=station.id,key=key,state={'last':tracks[1].id}))
        db.session.commit()
        resolved=dict(source=ref,key='legacy',insert=None,mode='CALENDAR')
        assert vs.select_visual(station,resolved,None,datetime.now(timezone.utc)).track_id==tracks[2].id
        playlist.mode='RANDOM'
        prior=db.session.get(ScheduleCursor,(station.id,key));prior.state={'played':[tracks[0].id,tracks[1].id]}
        db.session.commit()
        assert vs.select_visual(station,resolved,None,datetime.now(timezone.utc)).track_id in {tracks[2].id,tracks[3].id}
