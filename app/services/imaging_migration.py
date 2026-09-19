"""Resumable offline conversion of retired Imaging audio; originals are retained."""
import hashlib
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.extensions import db
from app import models as m
from app.services.audio_classification import classify, defaults
from app.services.media_storage import LocalMediaStorage, grant_playout_read


def inventory(station, storage=None):
    storage=storage or LocalMediaStorage()
    assets=m.ImagingAsset.query.filter_by(station_id=station.id).all()
    rows=[]
    for asset in assets:
        mapped=m.Track.query.filter_by(legacy_imaging_id=asset.id).first()
        collision=m.Track.query.filter_by(station_id=station.id,checksum_sha256=asset.checksum_sha256).first()
        problem=None
        try:
            source=storage.imaging_file(station.slug,asset.storage_key)
            with source.open('rb') as file: checksum=hashlib.file_digest(file,'sha256').hexdigest()
            if checksum!=asset.checksum_sha256:problem='checksum_mismatch'
        except (OSError,ValueError):problem='missing_or_invalid_file'
        rows.append(dict(id=asset.id,uuid=asset.uuid,name=asset.name,kind='COMMERCIALS' if asset.asset_type=='COMMERCIAL' else 'STATION',mapped=mapped.uuid if mapped else None,collision=collision.uuid if collision and not mapped else None,file_problem=problem,enabled=asset.enabled))
    references={}
    for model in (m.TimedEvent,m.EventBlockItem,m.EventBlockItemExecution,m.SelectionDecision,m.LiveCartSlot,m.CommercialCreative,m.TrafficStopsetItem,m.MediaIngestJob,m.ClockSlot):
        references[model.__tablename__]=model.query.filter(model.imaging_asset_id.in_([a.id for a in assets])).count()
    return dict(station=station.slug,assets=rows,references=references,groups=m.ImagingGroup.query.filter_by(station_id=station.id).count(),pending_jobs=m.MediaIngestJob.query.filter_by(station_id=station.id).filter(m.MediaIngestJob.kind.in_(('imaging','img_verify','img_enable')),m.MediaIngestJob.status.in_(('pending','processing'))).count())


def convert(station, storage=None, mapping=None):
    """Caller must stop playout/ingest for this station before applying."""
    storage=storage or LocalMediaStorage();mapping=mapping or {}
    db.session.query(m.Station.id).filter_by(id=station.id).with_for_update().first()
    report=inventory(station,storage)
    if station.desired_state!='stopped' or report['pending_jobs']:
        raise ValueError('Stop this station and finish pending Imaging jobs before conversion')
    if m.SelectionDecision.query.filter_by(station_id=station.id).filter(m.SelectionDecision.status.in_(('queued','submitting'))).first():
        raise ValueError('Clear or reconcile queued requests before conversion')
    for row in report['assets']:
        if row['collision'] and str(row['id']) not in mapping:
            raise ValueError(f"Audio {row['id']} duplicates an existing track. Supply its UUID in the reviewed mapping file")
        if row['file_problem'] and row['enabled']:
            raise ValueError(f"Enabled audio {row['id']} has {row['file_problem']}; repair or disable it first")
    defaults(station.id)
    converted={}
    for item in report['assets']:
        asset=db.session.get(m.ImagingAsset,item['id'])
        track=m.Track.query.filter_by(legacy_imaging_id=asset.id).first()
        if not track:
            explicit=mapping.get(str(asset.id))
            track=m.Track.query.filter_by(station_id=station.id,uuid=explicit).first() if explicit else None
            if explicit and (not track or track.checksum_sha256!=asset.checksum_sha256):raise ValueError('Mapped audio must belong to this station and match the checksum')
            if not track:
                key=uuid.uuid5(uuid.NAMESPACE_URL,'freo-imaging:'+asset.uuid).hex+'.mp3'
                if not item['file_problem']:
                    source=storage.imaging_file(station.slug,asset.storage_key)
                    target=storage.approved_path(station.slug,key);target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists():
                        with target.open('rb') as file:
                            if hashlib.file_digest(file,'sha256').hexdigest()!=asset.checksum_sha256:raise ValueError('Migration destination checksum mismatch')
                    else:
                        fd,name=tempfile.mkstemp(prefix='.convert-',dir=target.parent)
                        try:
                            with os.fdopen(fd,'wb') as out,source.open('rb') as src:
                                shutil.copyfileobj(src,out);out.flush();os.fsync(out.fileno())
                            os.chown(name,-1,source.stat().st_gid);grant_playout_read(name);os.replace(name,target)
                        finally:Path(name).unlink(missing_ok=True)
                track=m.Track(station_id=station.id,uuid=asset.uuid if not m.Track.query.filter_by(uuid=asset.uuid).first() else str(uuid.uuid4()),title=asset.name,artist=station.name,album='',original_filename=asset.original_filename,storage_key=key,media_type=asset.media_type,duration_ms=asset.duration_ms,bitrate_kbps=asset.bitrate_kbps,sample_rate_hz=asset.sample_rate_hz,channels=asset.channels,file_size_bytes=asset.file_size_bytes,checksum_sha256=asset.checksum_sha256,enabled=asset.enabled,ingest_status=asset.ingest_status,decommissioned_at=asset.decommissioned_at,notes=asset.description,analysis_status='pending')
                db.session.add(track);db.session.flush()
            # A reviewed duplicate must not make retired or disabled legacy audio playable.
            track.enabled = track.enabled and asset.enabled
            track.decommissioned_at = track.decommissioned_at or asset.decommissioned_at
            if asset.ingest_status != 'accepted':track.ingest_status=asset.ingest_status
            track.legacy_imaging_id=asset.id
            classify(track,item['kind'],asset.asset_type.lower() if item['kind']=='STATION' else '',asset.cart_code)
        converted[asset.id]=track
    db.session.flush()
    for asset_id,track in converted.items():
        for model in (m.TimedEvent,m.EventBlockItem,m.EventBlockItemExecution,m.SelectionDecision,m.LiveCartSlot,m.CommercialCreative,m.TrafficStopsetItem,m.MediaIngestJob):
            for row in model.query.filter_by(imaging_asset_id=asset_id).all():
                row.track_id=track.id;row.imaging_asset_id=None
                if isinstance(row,m.TimedEvent):row.content_type='TRACK';row.generated_until=None
                if isinstance(row,(m.EventBlockItem,m.EventBlockItemExecution)):row.item_type='TRACK'
                if isinstance(row,m.TrafficStopsetItem):row.item_type='FIXED_AUDIO'
        for slot in m.ClockSlot.query.filter_by(imaging_asset_id=asset_id).all():
            collection=m.Playlist(station_id=station.id,name=track.title[:120],description='Migrated station audio clock item',purpose=track.audio_kind)
            collection.items.append(m.PlaylistItem(track_id=track.id,position=1));db.session.add(collection);db.session.flush()
            slot.slot_type='PLAYLIST';slot.playlist_id=collection.id;slot.imaging_asset_id=None
    for group in m.ImagingGroup.query.filter_by(station_id=station.id).all():
        playlist=m.Playlist.query.filter_by(station_id=station.id,legacy_imaging_group_id=group.id).first()
        if playlist is None:
            playlist=m.Playlist(station_id=station.id,name=group.name,description=group.description,purpose='STATION',legacy_imaging_group_id=group.id,minimum_separation_seconds=group.minimum_separation_seconds,deleted_at=None if group.enabled else datetime.now(timezone.utc))
            for i,asset in enumerate(group.assets,1):playlist.items.append(m.PlaylistItem(track_id=converted[asset.id].id,position=i))
            db.session.add(playlist);db.session.flush()
        for slot in m.ClockSlot.query.filter_by(imaging_group_id=group.id):
            slot.slot_type='PLAYLIST';slot.playlist_id=playlist.id;slot.imaging_group_id=None
    db.session.commit()
    return dict(converted=len(converted),files_retained=True,references=inventory(station,storage)['references'])
