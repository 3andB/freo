"""Playlist V1 membership, calendar playback, isolation, and queue recovery."""
from datetime import datetime, timezone, timedelta
import pytest
from app.extensions import db
from app import models as m
from app.services import playlists as service
from app.services.automation import select_next
from app.services.calendar import create_program
from app.services.programming_refresh import checkpoint, restore, signature
from tests.test_web import app, admin_client
from tests.test_sound_room import action


def setup_playlist():
    station = m.Station.query.filter_by(slug='test-station').one()
    service.seed_playlists(station.id)
    row = service.listing(station.id)[0]
    first = m.Track.query.first()
    songs = [first]
    for number in range(2, 5):
        song = m.Track(station_id=station.id, uuid=f'00000000-0000-4000-8000-{number:012d}',
            title=f'Song {number}', artist=f'Artist {number}', original_filename=f'{number}.mp3',
            storage_key=f'{number}.mp3', media_type='mp3', duration_ms=20000, sample_rate_hz=44100,
            channels=2, file_size_bytes=1000, checksum_sha256=str(number)*64, enabled=True, ingest_status='accepted')
        db.session.add(song); songs.append(song)
    db.session.flush()
    service.membership(row, songs, 'add', m.AdminUser.query.first().id)
    db.session.commit()
    return station, row, songs


def program(station, row, at):
    return create_program(station, name='Playlist hour', weekdays=[], on_date=at.date().isoformat(),
                          start='09:00', end='10:00', playlist_id=str(row.id))[0]


def test_crud_membership_order_undo_and_no_audio_deletion(app):
    client = admin_client(app)
    with app.app_context():
        station, row, songs = setup_playlist(); identifier=row.id; ids=[song.uuid for song in songs]
    base='/admin/api/stations/test-station/playlists'
    assert client.get('/admin/stations/test-station/playlists').status_code == 200
    assert client.get('/admin/stations/test-station/sound-room').location.endswith('/playlists')
    assert len(client.get(base).json['playlists']) == 2
    detail=client.get(f'{base}/{identifier}').json
    assert detail['count']==4 and detail['duration_ms']==80000
    duplicate=action(client,'assign',dict(kind='playlist',target=identifier,songs=ids,operation='add'))
    assert duplicate.status_code==200 and duplicate.json['undo'] is None
    assert action(client,'playlist-reorder',dict(id=identifier,revision=detail['revision'],songs=ids[::-1])).status_code==200
    assert [s['uuid'] for s in client.get(f'{base}/{identifier}').json['songs']]==ids[::-1]
    assert action(client,'playlist-reorder',dict(id=identifier,revision=detail['revision'],songs=ids)).status_code==409
    removal=action(client,'playlist-remove',dict(id=identifier,songs=ids[1:3])).json
    assert client.get(f'{base}/{identifier}').json['count']==2
    assert action(client,'undo',dict(id=removal['undo'])).status_code==200
    assert [s['uuid'] for s in client.get(f'{base}/{identifier}').json['songs']]==ids[::-1]
    assert action(client,'undo',dict(id=removal['undo'])).status_code==409
    assert action(client,'delete-playlist',dict(id=identifier,confirm=identifier)).status_code==200
    assert client.get(f'{base}/{identifier}').status_code==404
    with app.app_context():assert m.Track.query.count()==4


def test_snapshot_sources_deduplicate_and_do_not_follow_library_changes(app):
    client=admin_client(app)
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id
        artist=m.Artist(station_id=station.id,name='Collection artist',normalized_name='collection artist')
        album=m.Album(station_id=station.id,artist=artist,title='Collection album',normalized_title='collection album')
        songs[0].catalog_artist=artist;songs[0].catalog_album=album
        category=songs[0].categories[0]
        empty=service.listing(station.id)[1];empty_id=empty.id
        db.session.commit();sources=[('artist',artist.id),('album',album.id),('category',category.id)]
    for kind,source in sources:
        result=action(client,'playlist-source',dict(id=empty_id,kind=kind,source=source))
        assert result.status_code==200
    with app.app_context():
        empty=db.session.get(m.Playlist,empty_id);assert len(empty.items)==1
        category=m.MediaCategory.query.first();category.tracks.append(m.Track.query.order_by(m.Track.id.desc()).first());db.session.commit()
        assert len(empty.items)==1


def test_station_scope_csrf_deleted_members_and_conflicting_undo(app):
    client=admin_client(app)
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id;ids=[song.uuid for song in songs]
    assert client.post('/admin/api/stations/test-station/music/actions/create-playlist',data={'data':'{}'}).status_code==400
    assert app.test_client().get('/admin/api/stations/test-station/playlists').status_code==302
    assert client.get(f'/admin/api/stations/second-station/playlists/{identifier}').status_code==404
    assert action(client,'assign',dict(kind='playlist',target=identifier,songs=[ids[0]],operation='add'),'second-station').status_code==409
    removed=action(client,'playlist-remove',dict(id=identifier,songs=[ids[0]])).json
    action(client,'playlist-remove',dict(id=identifier,songs=[ids[1]]))
    assert action(client,'undo',dict(id=removed['undo'])).status_code==409
    with app.app_context():
        song=m.Track.query.filter_by(uuid=ids[2]).one();song.deleted_at=datetime.now(timezone.utc);db.session.commit()
    detail=client.get(f'/admin/api/stations/test-station/playlists/{identifier}').json
    unavailable=next(s for s in detail['songs'] if s['uuid']==ids[2]);assert not unavailable['playable'] and 'audition' not in unavailable
    assert action(client,'playlist-remove',dict(id=identifier,songs=[ids[2]])).status_code==200


def test_new_station_gets_two_starters(app):
    from app.services.stations import create_station
    with app.app_context():
        station=create_station('New station','new-station')
        assert [row.name for row in service.listing(station.id)]==['Playlist 1','Playlist 2']
        assert all(not row.items for row in service.listing(station.id))


def test_straight_order_repeat_restart_and_new_occurrence(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist();ids=[s.id for s in songs];program(station,row,at);db.session.commit()
        first=select_next(station.slug,now=at);assert first.track_id==ids[0];playlist_id=row.id
        # A fresh session emulates restarting the worker without losing progress.
        db.session.remove()
        assert [select_next('test-station',now=at).track_id for _ in range(4)]==ids[1:]+ids[:1]
        station=m.Station.query.filter_by(slug='test-station').one();row=db.session.get(m.Playlist,playlist_id)
        program(station,row,at+timedelta(days=1));db.session.commit()
        assert select_next(station.slug,now=at+timedelta(days=1)).track_id==ids[0]


def test_random_no_repeat_and_checkpoint_restore(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist();row.mode='RANDOM';program(station,row,at);db.session.commit()
        picks=[select_next(station.slug,now=at).track_id for _ in range(4)]
        assert set(picks)=={song.id for song in songs}
        select_next(station.slug,now=at)
        saved=checkpoint(station)
        before=dict(m.PlaylistCursor.query.one().state)
        select_next(station.slug,now=at)
        restore(station,saved);db.session.commit()
        assert m.PlaylistCursor.query.one().state==before
        remaining=[select_next(station.slug,now=at).track_id for _ in range(3)]
        assert set(remaining).isdisjoint(before['played']) and len(set(remaining))==3


def test_unavailable_songs_skip_and_empty_playlist_falls_back(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist()
        # Keep the category's first song available as the station fallback.
        service.replace_order(row,[s.id for s in songs[1:]])
        songs[1].enabled=False;program(station,row,at);db.session.commit()
        assert select_next(station.slug,now=at).track_id==songs[2].id
        songs[2].enabled=False;songs[3].enabled=False;db.session.commit()
        assert select_next(station.slug,now=at).track_id==songs[0].id
        assert m.SelectionDecision.query.filter_by(reason='empty_or_unavailable_playlist').count()==1


def test_schedule_boundaries_validation_delete_and_rehearsal(app,monkeypatch):
    from app.services.clocks import preview_clock
    from app.services.schedule import resolve
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id
        empty=service.listing(station.id)[1]
        with pytest.raises(ValueError,match='enabled song'):program(station,empty,at)
        scheduled=program(station,row,at);db.session.commit()
        assert resolve(station,at).program.id==scheduled.id
        assert resolve(station,at.replace(hour=10,minute=0)).program is None
        before=checkpoint(station)
        preview=preview_clock(station.slug,scheduled.clock.slug,count=5)
        assert [p['track'] for p in preview]==[s.uuid for s in songs]+[songs[0].uuid]
        assert checkpoint(station)==before
    client=admin_client(app)
    assert action(client,'delete-playlist',dict(id=identifier,confirm=identifier)).status_code==409
    with app.app_context():
        m.ScheduleProgram.query.update({'enabled':False});db.session.commit()
    assert action(client,'delete-playlist',dict(id=identifier,confirm=identifier)).status_code==200


def test_calendar_form_and_signature_include_playlist_changes(app):
    client=admin_client(app)
    with app.app_context():
        station,row,songs=setup_playlist();identifier=row.id
        before=signature(station);service.replace_order(row,[s.id for s in songs[::-1]]);db.session.commit()
        assert signature(station)!=before
        before=signature(station);songs[-1].enabled=False;db.session.commit();assert signature(station)!=before
    response=client.post('/admin/stations/test-station/calendar/create',data=dict(csrf='test-admin-csrf-token',kind='playlist',playlist=identifier,name='Morning',weekday='2',start='09:00',end='10:00'),follow_redirects=True)
    assert response.status_code==200 and b'Published 1 calendar' in response.data
    assert b'id="schedule-initial"' in response.data and b'Morning' in response.data


def test_empty_playlist_uses_complete_default_clock_pattern(app,monkeypatch):
    monkeypatch.setattr('app.services.media_storage.LocalMediaStorage.regular_file',lambda *args:'/safe')
    at=datetime(2026,9,16,9,30,tzinfo=timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist()
        program(station,row,at)
        service.replace_order(row,[])
        second=m.MediaCategory(station_id=station.id,name='Second',slug='second',enabled=True)
        second.tracks.append(songs[1])
        clock=m.Clock(station_id=station.id,name='Default',slug='default',enabled=True)
        clock.slots=[m.ClockSlot(position=1,slot_type='CATEGORY',category=songs[0].categories[0]),m.ClockSlot(position=2,slot_type='CATEGORY',category=second)]
        station.automation.default_clock=clock;db.session.add_all([second,clock]);db.session.commit()
        assert [select_next(station.slug,now=at).track_id for _ in range(3)]==[songs[0].id,songs[1].id,songs[0].id]


def test_queue_refresh_restores_playlist_progress_without_repeating_active_song(app,monkeypatch):
    from tests.test_programming_refresh import fake_engine
    from app.services.programming_refresh import refresh
    from app.automation_worker import EventReader
    queued={12,13};fake_engine(monkeypatch,queued,{11})
    at=datetime.now(timezone.utc)
    with app.app_context():
        station,row,songs=setup_playlist()
        create_program(station,name='All day playlist',weekdays=[],on_date=at.date().isoformat(),start='00:00',end='00:00',playlist_id=row.id)
        db.session.commit()
        first=select_next(station.slug,now=at);first.status='started';first.socket_identity='test-engine';first.liquidsoap_request_id=11;db.session.commit()
        for request_id in (12,13):
            decision=select_next(station.slug,now=at);decision.status='queued';decision.socket_identity='test-engine';decision.liquidsoap_request_id=request_id;db.session.commit()
        # Metadata edit refreshes future requests, but preserves the first song.
        row.description='Updated';row.revision+=1;db.session.commit()
        assert refresh(station,EventReader(),signature(station,at))
        assert not queued and first.status=='started'
        assert select_next(station.slug,now=at).track_id==songs[1].id


def test_album_snapshot_uses_disc_track_order_across_performing_artists(app):
    with app.app_context():
        station,row,songs=setup_playlist()
        artist=m.Artist(station_id=station.id,name='Various artists',normalized_name='various artists')
        album=m.Album(station_id=station.id,artist=artist,title='Compilation',normalized_title='compilation')
        for song,performer,disc,number in zip(songs,['A','Z','B','Y'],[2,1,1,2],[2,2,1,1]):
            song.catalog_album=album;song.artist=performer;song.disc_number=disc;song.track_number=number
        db.session.commit()
        assert [song.id for song in service.source_songs(station.id,'album',album.id)]==[songs[2].id,songs[1].id,songs[3].id,songs[0].id]
