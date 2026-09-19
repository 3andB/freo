"""Master-library deletion, with worker-owned playback and file cleanup."""
import uuid
from datetime import datetime, timezone
from app.extensions import db
from app import models as m
from app.services.media_storage import LocalMediaStorage
from app.services.admin_media import audit


def ensure_deletable(song):
    # References are removed by deletion, never prerequisites for the operator.
    if song is None:
        raise ValueError('Song no longer exists')


def _prune_source(value, song_id):
    """Remove song sections/inserts without disturbing unrelated schedule data."""
    if isinstance(value, list):
        return [clean for item in value if (clean := _prune_source(item, song_id)) is not None]
    if isinstance(value, dict):
        if value.get('kind') == 'song' and str(value.get('id')) == str(song_id):
            return None
        if isinstance(value.get('source'), dict) and _prune_source(value['source'], song_id) is None:
            return None
        return {key: _prune_source(item, song_id) for key, item in value.items()}
    return value


def remove_references(song):
    """Detach programming in the same transaction as loss of eligibility."""
    legacy = db.session.get(m.ImagingAsset, song.legacy_imaging_id) if song.legacy_imaging_id else None
    if legacy:
        legacy.enabled = False
        legacy.decommissioned_at = datetime.now(timezone.utc)
        legacy.groups.clear()
        # Retired Imaging identities may still exist in old history or jobs.
        # Fold these onto the master song before applying the same cleanup.
        for model in (m.TimedEvent, m.EventBlockItem, m.EventBlockItemExecution,
                      m.SelectionDecision, m.LiveCartSlot, m.CommercialCreative,
                      m.TrafficStopsetItem, m.MediaIngestJob):
            for row in model.query.filter_by(imaging_asset_id=legacy.id):
                row.track_id, row.imaging_asset_id = song.id, None
                if isinstance(row, m.TimedEvent): row.content_type = 'TRACK'
                if isinstance(row, (m.EventBlockItem, m.EventBlockItemExecution)): row.item_type = 'TRACK'
                if isinstance(row, m.TrafficStopsetItem): row.item_type = 'FIXED_AUDIO'
        for slot in m.ClockSlot.query.filter_by(imaging_asset_id=legacy.id):
            db.session.delete(slot)
    for playlist in m.Playlist.query.join(m.PlaylistItem).filter(m.PlaylistItem.track_id == song.id):
        playlist.revision += 1
    # Delete children before parents, including check-constrained target rows.
    for model in (m.EventBlockItemExecution, m.EventBlockItem, m.TimedEvent,
                  m.TrafficStopsetItem, m.PlaylistItem, m.SongFlag, m.ListenerVote,
                  m.ListenerFeedbackEvent, m.FeedbackTransition):
        for row in model.query.filter_by(track_id=song.id).all():
            db.session.delete(row)
    for row in m.CommercialCreative.query.filter_by(track_id=song.id):
        row.track_id = None
        row.enabled = False
        row.name = 'Deleted audio'
    for row in m.LiveCartSlot.query.filter_by(track_id=song.id):
        row.track_id = None
        row.label = row.description = ''
    m.AutomationState.query.filter_by(cued_track_id=song.id).update({'cued_track_id': None})
    song.categories.clear()
    song.tags.clear()
    for cue in m.BoothCue.query.all():
        entries = [entry for entry in cue.entries if entry.get('track_id') != song.id]
        saved_order = [identifier for identifier in cue.saved_order if identifier != song.id]
        if entries != cue.entries or saved_order != cue.saved_order:
            cue.entries = entries
            cue.saved_order = saved_order
            cue.revision += 1
    for cue in m.SavedBoothCue.query.all():
        cue.tracks = [identifier for identifier in cue.tracks if identifier != song.id]
    for model, column in ((m.PlaylistCursor, 'state'), (m.ScheduleCursor, 'state'),
                          (m.TimedEvent, 'playlist_state')):
        for row in model.query.all():
            state = dict(getattr(row, column) or {})
            if state.get('last') == song.id:
                state.pop('last')
            if 'played' in state:
                state['played'] = [identifier for identifier in state['played'] if identifier != song.id]
            setattr(row, column, state)
    for model, columns in ((m.ChannelSchedule, ('calendar','simple','live_simple')),
                           (m.ScheduleCompositionRevision, ('sections',)),
                           (m.ScheduleTransition, ('simple',))):
        for row in model.query.all():
            changed = False
            for column in columns:
                old = getattr(row, column)
                new = _prune_source(old, song.id)
                if new != old:
                    setattr(row, column, new)
                    changed = True
            if changed and isinstance(row, m.ChannelSchedule):
                row.revision += 1
    # Undo must never put a deleted song back into the catalog.
    for edit in m.MusicEdit.query.filter_by(undone=False):
        if any(change.get('uuid') == song.uuid or str(change.get('song')) == song.uuid or change.get('id') == song.id
               or change.get('song') == song.id or (edit.kind == 'playlist' and
                   (song.id in change.get('before', []) or song.id in change.get('after', []))) for change in edit.changes if isinstance(change, dict)):
            edit.undone = True
            edit.changes = []


def queue_delete(song, user, station=None):
    from app.services.stations import allocation_lock
    allocation_lock()  # Serializes with the final playout handoff.
    db.session.refresh(song)
    existing = m.MediaIngestJob.query.filter_by(track_id=song.id, kind='delete').order_by(m.MediaIngestJob.created_at.desc()).first()
    if existing:
        if existing.status in ('error', 'rejected'):
            existing.status = 'pending'
            existing.error_code = None
            existing.finished_at = None
        return existing
    ensure_deletable(song)
    song.enabled = song.auto_enable_pending = song.analysis_requested = False
    song.decommissioned_at = song.deleted_at = datetime.now(timezone.utc)
    remove_references(song)
    for decision in m.SelectionDecision.query.filter_by(track_id=song.id):
        if not db.session.get(m.EventQueueCancellation, decision.id):
            db.session.add(m.EventQueueCancellation(decision_id=decision.id, station_id=decision.station_id))
    job = m.MediaIngestJob(id=str(uuid.uuid4()), kind='delete', station_id=(station or song.station).id,
        admin_user_id=user.id, original_filename='Deleted song', track_id=song.id, status='pending')
    db.session.add(job)
    audit('music_delete_requested', user_id=user.id, station_id=job.station_id,
          target_id=song.uuid, summary='Master-library deletion requested across all channels')
    return job


def playback_cleanup_pending(song):
    return m.EventQueueCancellation.query.join(m.SelectionDecision).join(
        m.Station, m.EventQueueCancellation.station_id == m.Station.id).filter(
        m.SelectionDecision.track_id == song.id, m.EventQueueCancellation.processed.is_(False),
        m.Station.enabled.is_(True), m.Station.desired_state == 'running', m.Station.deleted_at.is_(None)).first() is not None


def delete_audio(song):
    if song is None:  # Repeating a completed operation is harmless.
        return
    storage = LocalMediaStorage()
    storage.approved_path(song.station.slug, song.storage_key).unlink(missing_ok=True)
    if song.preview_key:
        storage.preview_path(song.station.slug, song.preview_key).unlink(missing_ok=True)
        song.preview_key = None
    if song.artwork_key and not m.Album.query.filter_by(artwork_key=song.artwork_key).first() and not m.Track.query.filter(m.Track.id != song.id, m.Track.artwork_key == song.artwork_key).first():
        storage.artwork_path(song.station.slug, song.artwork_key).unlink(missing_ok=True)
    remove_references(song)  # Also covers references committed during an interrupted attempt.
    if song.legacy_imaging_id:
        legacy = db.session.get(m.ImagingAsset, song.legacy_imaging_id)
        if legacy:
            storage.imaging_path(legacy.station.slug, legacy.storage_key).unlink(missing_ok=True)
            db.session.flush()
            db.session.execute(db.delete(m.ImagingAsset).where(m.ImagingAsset.id == legacy.id))
    # Remove history and import metadata; the operation log retains only its generic result.
    for decision in m.SelectionDecision.query.filter_by(track_id=song.id).all():
        # Clear ORM backrefs with constrained event targets already removed above.
        db.session.execute(db.delete(m.CuePlayback).where(m.CuePlayback.decision_id == decision.id))
        db.session.execute(db.delete(m.EventQueueCancellation).where(m.EventQueueCancellation.decision_id == decision.id))
        db.session.execute(db.update(m.LiveControlCommand).where(m.LiveControlCommand.target_decision_id == decision.id).values(target_decision_id=None, status='failed', error_code='song_deleted'))
        db.session.execute(db.update(m.LiveControlCommand).where(m.LiveControlCommand.expected_decision_id == decision.id).values(expected_decision_id=None, status='failed', error_code='song_deleted'))
        db.session.execute(db.update(m.ScheduleTransition).where(m.ScheduleTransition.decision_id == decision.id).values(decision_id=None))
        db.session.execute(db.update(m.TimedEventOccurrence).where(m.TimedEventOccurrence.selection_decision_id == decision.id).values(selection_decision_id=None))
        db.session.execute(db.delete(m.SelectionDecision).where(m.SelectionDecision.id == decision.id))
    for job in m.MediaIngestJob.query.filter_by(track_id=song.id):
        for item in m.MusicImportItem.query.filter_by(job_id=job.id):
            from app.services.admin_media import staged_path
            if item.preview_id:
                staged_path(item.preview_id).unlink(missing_ok=True)
            staged_path(item.id).unlink(missing_ok=True)
            db.session.delete(item)
        job.track = None
        job.original_filename = 'Deleted song'
        job.import_metadata = {}
        if job.kind != 'delete' and job.status in ('pending', 'processing'):
            job.status = 'rejected'
            job.error_code = 'song_deleted'
    m.DMCACase.query.filter_by(track_id=song.id).update({'track_id': None})
    identifier, station_id, cover_id = song.uuid, song.station_id, song.cover_id
    db.session.flush()
    db.session.execute(db.delete(m.Track).where(m.Track.id == song.id))
    if cover_id and not m.Track.query.filter_by(cover_id=cover_id).first() and not m.Album.query.filter_by(cover_id=cover_id).first():
        db.session.execute(db.delete(m.MusicArtwork).where(m.MusicArtwork.id == cover_id))
    audit('music_permanently_deleted', station_id=station_id, target_id=identifier,
          summary='Song, audio, and music references permanently removed across all channels')


def clear_deleted_playback(station, jobs):
    """Called only by the socket-owning worker; identities are checked by the engine."""
    from app.services.playout_queue import _command, request_decision_id, active_ids
    for job in jobs:
        _command(station.slug, f'freo_music.remove {job.decision_id}')
    # A source may finish the skip on its next audio frame. Retry until acknowledged.
    remaining = {request_decision_id(station.slug, rid) for rid in active_ids(station.slug)}
    for bus in ('queue', 'event', 'a', 'b', 'cart'):
        remaining.update(request_decision_id(station.slug, int(rid))
                         for rid in _command(station.slug, f'freo_{bus}.queue').split())
    for job in jobs:
        if job.decision_id not in remaining:
            job.processed = True
            job.decision.status, job.decision.reason = 'failed', 'song_deleted'
