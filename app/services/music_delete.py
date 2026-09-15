"""Permanent audio deletion is performed by the storage-owning ingest worker."""
import uuid
from datetime import datetime, timezone
from app.extensions import db
from app.models import (Station, Track, SelectionDecision, LiveQueueSnapshot, MediaIngestJob,
                        TimedEvent, EventBlockItem, EventBlockItemExecution)
from app.services.media_storage import LocalMediaStorage
from app.services.admin_media import audit


def ensure_deletable(song):
    if song.analysis_status=='processing':raise ValueError('Wait for this song to finish processing before deleting it')
    if SelectionDecision.query.filter(SelectionDecision.track_id==song.id,SelectionDecision.status.in_(('selected','submitting','queued'))).first():
        raise ValueError('This song is queued. Wait for playback or clear its programming references first.')
    if TimedEvent.query.filter_by(track_id=song.id).first() or EventBlockItem.query.filter_by(track_id=song.id).first():
        raise ValueError('Remove this song from Events and Blocks before deleting it.')
    if EventBlockItemExecution.query.filter(EventBlockItemExecution.track_id==song.id,EventBlockItemExecution.state.in_(('PENDING','QUEUED','STARTED'))).first():
        raise ValueError('This song belongs to an active block. Wait for the block to finish.')
    station=song.station
    if station.desired_state=='running':
        snapshot=db.session.get(LiveQueueSnapshot,station.id)
        if not snapshot or snapshot.error_code or (datetime.now(timezone.utc)-snapshot.observed_at.replace(tzinfo=timezone.utc)).total_seconds()>10 or snapshot.unknown_count:
            raise ValueError('Current playback is not confirmed. Try deletion when station status is available.')
        ids=([snapshot.current_decision_id] if snapshot.current_decision_id else [])+(snapshot.queued_decision_ids or [])
        if SelectionDecision.query.filter(SelectionDecision.id.in_(ids),SelectionDecision.track_id==song.id).first():
            raise ValueError('This song is on air or queued. Wait until it has finished before deleting it.')


def queue_delete(song,user):
    db.session.query(Station.id).filter_by(id=song.station_id).with_for_update().first()
    if song.deleted_at:raise ValueError('Song has already been permanently deleted')
    existing=MediaIngestJob.query.filter(MediaIngestJob.track_id==song.id,MediaIngestJob.kind=='delete',MediaIngestJob.status.in_(('pending','processing'))).first()
    if existing:return existing
    ensure_deletable(song)
    song.enabled=False;song.decommissioned_at=datetime.now(timezone.utc)
    song.analysis_requested=False;song.categories.clear();song.tags.clear()
    if song.station.automation and song.station.automation.cued_track_id==song.id:song.station.automation.cued_track_id=None
    job=MediaIngestJob(id=str(uuid.uuid4()),kind='delete',station_id=song.station_id,admin_user_id=user.id,original_filename=song.original_filename,track_id=song.id,status='pending')
    db.session.add(job)
    audit('music_delete_requested',user_id=user.id,station_id=song.station_id,target_id=song.uuid,summary='Permanent audio deletion requested; playback eligibility removed')
    return job


def delete_audio(song):
    ensure_deletable(song)
    storage=LocalMediaStorage()
    # approved_path verifies the opaque key and every symlink boundary even if
    # a previous attempt already removed the file before the DB commit.
    path=storage.approved_path(song.station.slug,song.storage_key)
    path.unlink(missing_ok=True)
    if song.artwork_key and not (song.catalog_album and song.catalog_album.artwork_key==song.artwork_key):
        storage.artwork_path(song.station.slug,song.artwork_key).unlink(missing_ok=True)
    song.artwork_key=None;song.notes='';song.deleted_at=datetime.now(timezone.utc)
    # Free the unique checksum so a future intentional reimport is a new song.
    song.checksum_sha256='deleted-'+song.uuid
    audit('music_permanently_deleted',station_id=song.station_id,target_id=song.uuid,summary='Audio permanently removed; historical song identity retained')
