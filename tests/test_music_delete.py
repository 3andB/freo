"""Master-library deletion removes references without manual operator cleanup."""
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid
import pytest
from app.extensions import db
from app import models as m
from app.services.music_delete import queue_delete, clear_deleted_playback
from app.ingest_worker import process_one
from tests.test_web import app, admin_client
from tests.test_import_postgres import pg_app


def add_song(station, number=1):
    song=m.Track(station_id=station.id,uuid=str(uuid.uuid4()),title=f'Song {number}',artist='Artist',
        original_filename='song.mp3',storage_key=str(number)*32+'.mp3',media_type='mp3',duration_ms=2000,
        sample_rate_hz=44100,channels=2,file_size_bytes=10,checksum_sha256=str(number)*64,enabled=True)
    db.session.add(song);db.session.flush();return song


def exercise_references(application,tmp_path,monkeypatch):
    root=tmp_path/'media';monkeypatch.setenv('FREO_MEDIA_ROOT',str(root))
    with application.app_context():
        station=m.Station.query.filter_by(slug='test-station').one();station.desired_state='stopped'
        other=m.Station(name='Shared',slug='shared',desired_state='stopped');db.session.add(other);db.session.flush()
        song=add_song(station);keep=add_song(station,2);identifier=song.id
        song.available_to_all=True
        legacy=m.ImagingAsset(station_id=station.id,uuid=str(uuid.uuid4()),name='Legacy song',asset_type='CART',original_filename='legacy.mp3',storage_key='c'*32+'.mp3',media_type='mp3',duration_ms=2000,sample_rate_hz=44100,channels=2,file_size_bytes=10,checksum_sha256='c'*64,enabled=True)
        db.session.add(legacy);db.session.flush();song.legacy_imaging_id=legacy.id;legacy_id=legacy.id
        old_audio=root/station.slug/'imaging'/legacy.storage_key;old_audio.parent.mkdir(parents=True);old_audio.write_bytes(b'legacy audio')
        db.session.add(m.SelectionDecision(station_id=station.id,imaging_asset_id=legacy.id,status='started'))
        originals=root/station.slug/'originals';originals.mkdir(parents=True)
        path=originals/song.storage_key;path.write_bytes(b'audio')
        block=m.EventBlock(station_id=other.id,name='Block',slug='block',enabled=True)
        block.items=[m.EventBlockItem(position=1,item_type='TRACK',track_id=song.id),m.EventBlockItem(position=2,item_type='TRACK',track_id=keep.id)]
        playlist=m.Playlist(station_id=other.id,name='Playlist',items=[m.PlaylistItem(position=1,track_id=song.id)])
        event=m.TimedEvent(uuid=str(uuid.uuid4()),station_id=other.id,name='Play song',timing_mode='SOFT',content_type='TRACK',track_id=song.id,recurrence_type='ONE_TIME',scheduled_at_utc=datetime.now(timezone.utc))
        db.session.add_all([block,playlist,event]);db.session.flush()
        decision=m.SelectionDecision(station_id=other.id,track_id=song.id,status='queued')
        db.session.add(decision);db.session.flush()
        execution=m.EventBlockExecution(station_id=other.id,event_block_id=block.id,source='MANUAL',state='QUEUED',items=[m.EventBlockItemExecution(position=1,item_type='TRACK',track_id=song.id,event_block_item_id=block.items[0].id,selection_decision_id=decision.id,failure_policy='ABORT_BLOCK',state='QUEUED')])
        db.session.add_all([execution,m.LiveCartSlot(station_id=other.id,role='HOT',position=1,track_id=song.id,label='Song label'),m.BoothCue(station_id=other.id,entries=[{'id':'entry','track_id':song.id}],saved_order=[song.id]),m.SavedBoothCue(station_id=other.id,name='Set',tracks=[song.id,keep.id]),m.ChannelSchedule(station_id=other.id,calendar=[{'id':'a','source':{'kind':'song','id':song.id}}, {'id':'b','source':{'kind':'song','id':keep.id}}])])
        db.session.commit()
        job=queue_delete(song,m.AdminUser.query.first(),other);job_id=job.id;db.session.commit()
        assert song.deleted_at and not song.enabled
        assert m.TimedEvent.query.filter_by(track_id=identifier).count()==0
        assert m.EventBlockItem.query.filter_by(track_id=identifier).count()==0
        assert m.EventBlockItemExecution.query.filter_by(track_id=identifier).count()==0
        assert m.PlaylistItem.query.filter_by(track_id=identifier).count()==0
        assert m.LiveCartSlot.query.filter_by(track_id=identifier).count()==0
        assert m.BoothCue.query.filter_by(station_id=other.id).one().entries==[]
        assert m.SavedBoothCue.query.one().tracks==[keep.id]
        assert len(m.ChannelSchedule.query.one().calendar)==1
        assert queue_delete(song,m.AdminUser.query.first()).id==job_id
        assert process_one()
        db.session.expire_all()
        assert db.session.get(m.Track,identifier) is None
        assert db.session.get(m.MediaIngestJob,job_id).status=='accepted'
        assert not path.exists()
        assert not old_audio.exists() and db.session.get(m.ImagingAsset,legacy_id) is None
        assert db.session.get(m.Track,keep.id) is not None
        assert m.EventBlock.query.filter_by(id=block.id).one().items[0].track_id==keep.id
        assert m.SelectionDecision.query.filter_by(track_id=identifier).count()==0
        assert db.session.get(m.MediaIngestJob,job_id).track_id is None


def test_delete_all_references(app,tmp_path,monkeypatch):
    exercise_references(app,tmp_path,monkeypatch)


def test_delete_all_references_postgres(pg_app,tmp_path,monkeypatch):
    exercise_references(pg_app,tmp_path,monkeypatch)


def test_playback_cleanup_waits_then_retries_file_failure(app,tmp_path,monkeypatch):
    root=tmp_path/'media';monkeypatch.setenv('FREO_MEDIA_ROOT',str(root))
    with app.app_context():
        song=m.Track.query.first();song.storage_key='a'*32+'.mp3'
        original=root/song.station.slug/'originals';original.mkdir(parents=True);path=original/song.storage_key;path.write_bytes(b'audio')
        job=queue_delete(song,m.AdminUser.query.first());db.session.commit();identifier=song.id
        assert not process_one()  # Engine has not acknowledged removal yet.
        assert path.exists()
        for pending in m.EventQueueCancellation.query.all():pending.processed=True
        db.session.commit()
        from app.services.media_storage import LocalMediaStorage
        real=LocalMediaStorage.approved_path
        monkeypatch.setattr(LocalMediaStorage,'approved_path',lambda *args:(_ for _ in ()).throw(PermissionError('file denied')))
        assert process_one();assert job.status=='error';assert path.exists()
        monkeypatch.setattr(LocalMediaStorage,'approved_path',real)
        retry=admin_client(app).post(f'/admin/stations/test-station/media/jobs/{job.id}/retry-delete',data={'csrf':'test-admin-csrf-token'})
        assert retry.status_code==303
        assert process_one()
        assert not path.exists() and db.session.get(m.Track,identifier) is None


def test_engine_removes_only_deleted_song_and_waits_for_ack(monkeypatch):
    from app.services import playout_queue as q
    commands=[];active=[{70},set()]
    def command(slug,cmd):
        commands.append(cmd)
        return '80' if cmd=='freo_queue.queue' else ''
    monkeypatch.setattr(q,'_command',command)
    monkeypatch.setattr(q,'request_decision_id',lambda slug,rid:{70:7,80:8}[rid])
    monkeypatch.setattr(q,'mixer_state',lambda slug:{'auto_id':7,'a_id':8})
    monkeypatch.setattr(q,'active_ids',lambda slug:active.pop(0))
    job=SimpleNamespace(decision_id=7,processed=False,decision=SimpleNamespace(playback_bus='A',status='queued'))
    clear_deleted_playback(SimpleNamespace(slug='test'),[job])
    assert not job.processed
    clear_deleted_playback(SimpleNamespace(slug='test'),[job])
    assert 'freo_music.remove 7' in commands
    assert not any('remove 8' in command or 'skip' in command for command in commands)
    assert job.processed and job.decision.reason=='song_deleted'


def test_processing_permission_error_is_actionable(app,monkeypatch,caplog):
    from app.services.audio_analysis import analyze_song
    with app.app_context():
        song=m.Track.query.first()
        storage=SimpleNamespace(regular_file=lambda *args:(_ for _ in ()).throw(PermissionError('denied')))
        analyze_song(song,storage)
        assert song.analysis_status=='failed'
        assert 'permissions' in song.analysis_error
        assert song.uuid in caplog.text
