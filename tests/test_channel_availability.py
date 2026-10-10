"""Cross-channel media discovery, inherited access, and retained storage."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import uuid
import pytest

from app.extensions import db
from app.models import (Album, Artist, Station, Track, MediaCategory, SelectionDecision,
                        AdminUser, MusicArtwork, EventBlock, EventBlockItem, TimedEvent)
from app.services.availability import available, playable, tracks_for, set_sharing
from app.services.music_catalog import organize_song, bulk_categories
from app.services.stations import create_station, request_delete
from app.services.station_lifecycle import process_station
from app.services.playout_queue import push_decision
from tests.test_station_lifecycle import app, station_app
from tests.test_web import admin_client


@pytest.fixture
def library(app,tmp_path,monkeypatch):
    monkeypatch.setenv('FREO_MEDIA_ROOT',str(tmp_path/'media'))
    with app.app_context():
        owner=create_station('Owner','owner');other=create_station('Other','other')
        songs=[]
        for i in range(3):
            key=str(i)*32+'.mp3'
            song=Track(station_id=owner.id,uuid=str(uuid.uuid4()),title=f'Song {i}',artist='Artist',album='Album' if i<2 else 'Other album',original_filename=key,storage_key=key,media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=10,checksum_sha256=str(i)*64,ingest_status='accepted',enabled=True)
            db.session.add(song);organize_song(song);songs.append(song)
            parent=tmp_path/'media'/'owner'/'originals';parent.mkdir(parents=True,exist_ok=True);(parent/key).write_bytes(b'0123456789')
        db.session.commit()
        yield owner,other,songs


@pytest.mark.parametrize('kind,expected', [('song',1),('album',2),('artist',3)])
def test_inheritance_and_future_channels(app,library,kind,expected):
    owner,other,songs=library
    target={'song':songs[0],'album':songs[0].catalog_album,'artist':songs[0].catalog_artist}[kind]
    assert tracks_for(other.id).count()==0
    set_sharing(target,True);db.session.commit()
    assert tracks_for(other.id).count()==expected
    future=create_station('Future','future')
    assert tracks_for(future.id).count()==expected
    assert tracks_for(owner.id).count()==3
    set_sharing(target,False);db.session.commit()
    assert tracks_for(other.id).count()==0


def test_future_upload_and_overlapping_inheritance(app,library):
    owner,other,songs=library
    artist=songs[0].catalog_artist;album=songs[0].catalog_album
    set_sharing(artist,True);set_sharing(album,True);set_sharing(songs[0],True);db.session.commit()
    set_sharing(songs[0],False);set_sharing(album,False);db.session.commit()
    assert available(songs[0],other.id)
    new=Track(station_id=owner.id,uuid=str(uuid.uuid4()),title='Future song',artist='Artist',album='New Album',original_filename='new.mp3',storage_key='a'*32+'.mp3',media_type='mp3',duration_ms=1000,sample_rate_hz=44100,channels=2,file_size_bytes=10,checksum_sha256='a'*64)
    db.session.add(new);organize_song(new);db.session.commit()
    assert available(new,other.id)
    assert tracks_for(other.id).count()==4


def test_shared_does_not_enable_unapproved_deleted_or_disabled_audio(app,library):
    owner,other,songs=library;song=songs[0]
    set_sharing(song,True);db.session.commit()
    for key,value in [('enabled',False),('ingest_status','rejected'),('decommissioned_at',datetime.now(timezone.utc)),('deleted_at',datetime.now(timezone.utc))]:
        original=getattr(song,key);setattr(song,key,value)
        assert not playable(song,other.id)
        setattr(song,key,original)
    assert playable(song,other.id)


def test_shared_playout_uses_owner_storage_after_owner_deleted(app,library,monkeypatch):
    owner,other,songs=library;song=songs[0]
    set_sharing(song,True);db.session.commit()
    request_delete(owner);process_station(owner)
    assert tracks_for(other.id).count()==1
    decision=SelectionDecision(station_id=other.id,track=song,status='selected')
    db.session.add(decision);db.session.commit()
    commands=[]
    monkeypatch.setattr('app.services.playout_queue._command',lambda slug,command: commands.append((slug,command)) or '42')
    assert push_decision(decision)==42
    assert commands[0][0]=='other'
    assert '/owner/originals/'+song.storage_key in commands[0][1]
    assert '/other/originals/' not in commands[0][1]
    assert owner.deleted_at and song.enabled
    client=admin_client(app)
    url=f'/admin/stations/other/media/{song.uuid}/audition'
    result=client.get(url,headers={'Range':'bytes=0-3'})
    assert result.status_code==206 and result.data==b'0123'
    data=client.get('/admin/api/stations/other/music').json['songs'][0]
    assert '/other/' in data['audition'] and '/other/' in data['detail']


def test_channel_categories_stay_independent(app,library):
    owner,other,songs=library;song=songs[0]
    set_sharing(song,True)
    first=MediaCategory(station_id=owner.id,name='Own',slug='own')
    second=MediaCategory(station_id=other.id,name='Other',slug='other')
    db.session.add_all([first,second]);db.session.commit()
    bulk_categories(owner,[song],first);bulk_categories(other,[song],second);db.session.commit()
    client=admin_client(app)
    result=client.post(f'/admin/stations/other/media/{song.uuid}/categories',data={'csrf':'test-admin-csrf-token'})
    assert result.status_code==303
    db.session.refresh(song)
    assert [c.id for c in song.categories]==[first.id]


def test_revoke_blocks_queued_audio_then_validators_reject_access(app,library,monkeypatch):
    owner,other,songs=library;song=songs[0];set_sharing(song,True);db.session.commit()
    decision=SelectionDecision(station_id=other.id,track=song,status='queued');db.session.add(decision);db.session.commit()
    with pytest.raises(ValueError,match='in use'):
        set_sharing(song,False)
    db.session.rollback()
    assert song.available_to_all
    decision.status='failed';db.session.commit()
    set_sharing(song,False);db.session.commit()
    with pytest.raises(ValueError,match='not approved'):
        push_decision(decision)
    assert tracks_for(other.id).count()==0


def test_shared_artist_detail_hides_private_siblings_and_artwork_survives(app,library):
    owner,other,songs=library;song=songs[0]
    set_sharing(song,True)
    art=MusicArtwork(id=str(uuid.uuid4()),station_id=owner.id,image=b'jpeg');db.session.add(art);song.catalog_album.cover_id=art.id;db.session.commit()
    client=admin_client(app)
    artist_url=f'/admin/stations/other/media/artists/{song.artist_id}'
    body=client.get(artist_url).data
    assert b'Other album' not in body
    album_url=f'/admin/stations/other/media/albums/{song.album_id}'
    body=client.get(album_url).data
    assert b'Song 0' in body and b'Song 1' not in body
    request_delete(owner);process_station(owner)
    response=client.get(f'/admin/stations/other/artwork/{art.id}')
    assert response.status_code==200 and response.data==b'jpeg'
    assert client.get(f'/admin/stations/other/media/{songs[1].uuid}').status_code==404


def test_sharing_controls_and_authentication(app,library):
    owner,other,songs=library;song=songs[0];client=admin_client(app)
    for kind,row,page in [('song',song,song.uuid),('artist',song.catalog_artist,f'artists/{song.artist_id}'),('album',song.catalog_album,f'albums/{song.album_id}')]:
        url=f'/admin/stations/owner/media/sharing/{kind}/{row.id}'
        assert b'Available to all channels' in client.get('/admin/stations/owner/media/'+page).data
        assert app.test_client().post(url).status_code==302
        assert client.post(url).status_code==400
        result=client.post(url,data={'csrf':'test-admin-csrf-token','available_to_all':'on'})
        assert result.status_code==303
        db.session.refresh(row);assert row.available_to_all


def test_shared_song_can_be_permanently_deleted(app,library):
    from app.services.music_delete import ensure_deletable
    owner,other,songs=library
    set_sharing(songs[0].catalog_artist,True);db.session.commit()
    ensure_deletable(songs[0])


def test_auto_events_and_blocks_select_shared_audio_after_owner_deletion(app,library):
    from app.services import automation, event_blocks, timed_events
    owner,other,songs=library;song=songs[0]
    set_sharing(song,True);db.session.commit()
    automation.category_create('other','Shared','shared')
    automation.assign_track('other',song.uuid,'shared')
    automation.rotation_create('other','Main','main')
    automation.add_slot('other','main','shared')
    automation.activate('other','main')
    automation.set_automation('other',True,0,0)
    block=event_blocks.save_block('other',name='Shared block')
    event_blocks.add_item(block,'TRACK',song.uuid)
    event=timed_events.save_event('other',name='Shared event',timing_mode='SOFT',recurrence_type='ONE_TIME',content_type='TRACK',content_identifier=song.uuid,local_date='2027-01-01',local_time='12:00')
    request_delete(owner);process_station(owner)
    assert automation.preview('other',1)[0]['track']==song.uuid
    assert event_blocks.validate_block(block)==[]
    assert timed_events.validate_content(event).id==song.id
    selection=automation.select_next('other')
    assert selection.track_id==song.id and selection.station_id==other.id
    selection.status='failed';db.session.commit()
    set_sharing(song,False);db.session.commit()
    assert automation.preview('other',1)[0]['track'] is None
    assert event_blocks.validate_block(block)
    with pytest.raises(ValueError,match='unavailable'):
        timed_events.validate_content(event)


def test_pending_ingest_is_rejected_when_station_deleted(app,library):
    from app.models import MediaIngestJob
    owner,other,songs=library
    job=MediaIngestJob(id=str(uuid.uuid4()),station_id=owner.id,kind='ingest',original_filename='pending.mp3',status='pending')
    db.session.add(job);db.session.commit()
    request_delete(owner);process_station(owner)
    db.session.refresh(job)
    assert job.status=='rejected' and job.error_code=='station_deleted'
    assert other.enabled


def test_socket_boundary_requires_exact_shared_decision_and_storage_key(app,library,monkeypatch):
    from app.services.playout_queue import _command
    from app.services.media_storage import LocalMediaStorage
    owner,other,songs=library;song=songs[0];set_sharing(song,True);db.session.commit()
    decision=SelectionDecision(station_id=other.id,track=song,status='selected');db.session.add(decision);db.session.commit()
    class Socket:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,*args):pass
        def connect(self,path):assert path.endswith('/other/control.sock')
        def sendall(self,command):self.command=command
        def recv(self,size):return b'42\r\nEND\r\n'
    monkeypatch.setattr('app.services.playout_queue.socket.socket',lambda *args:Socket())
    assert push_decision(decision)==42
    path=LocalMediaStorage().regular_file('owner',song.storage_key)
    command=f'freo_queue.push annotate:freo_decision={decision.id}:{path}'
    assert _command('other',command)=='42'
    with pytest.raises(ValueError,match='not approved'):
        _command('other',command.replace(song.storage_key,songs[1].storage_key))
    with pytest.raises(ValueError,match='not approved'):
        _command('other',command.replace(f'freo_decision={decision.id}', 'freo_decision=99999'))
    song.available_to_all=False;db.session.commit()
    with pytest.raises(ValueError,match='not approved'):
        _command('other',command)
    with pytest.raises(ValueError,match='allowlisted'):
        _command('other',command.replace('/owner/originals/','/../originals/'))
