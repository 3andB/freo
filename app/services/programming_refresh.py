"""Detect committed programming changes and replace only automatic lookahead.

Signatures are computed from station configuration rather than UI callbacks, so
CLI edits, bulk SQL updates and inherited shared-library changes are covered.
Each selection retains the cursor positions from before it was selected.
"""
import hashlib
import json
from sqlalchemy import select
from app.extensions import db
from app import models as m
from app.services.availability import track_scope


def signature(station,now=None):
    from app.services.schedule import resolve
    programming=resolve(station,now)
    state=station.automation
    values=[station.timezone,station.target_lufs,programming.occurrence_key,
            state.active_rotation_id,state.default_clock_id,state.track_separation_seconds,state.artist_separation_seconds]
    schedule=db.session.get(m.ChannelSchedule,station.id)
    if schedule:
        values.append([schedule.revision,schedule.mode,schedule.activation,schedule.default_playlist_id,{key:programming.visual[key] for key in ('source','key','reason')} if programming.visual else None])
    # Core rows avoid relationship caches and do not load audio/artwork blobs.
    for model in (m.Playlist,m.MediaCategory,m.Rotation,m.Clock,m.ScheduleAssignment,m.ScheduleProgram,m.ImagingAsset,m.ImagingGroup,m.EventBlock,m.TimedEvent):
        table=model.__table__
        columns=[c for c in table.c if c.name not in ('created_at','updated_at')]
        values.append([list(row) for row in db.session.execute(select(*columns).where(table.c.station_id==station.id).order_by(table.c.id))])
    for model,parent,key in ((m.PlaylistItem,m.Playlist,'playlist_id'),(m.ClockSlot,m.Clock,'clock_id'),(m.RotationSlot,m.Rotation,'rotation_id')):
        table=model.__table__;parent_table=parent.__table__
        values.append([list(row) for row in db.session.execute(select(table).join(parent_table,table.c[key]==parent_table.c.id).where(parent_table.c.station_id==station.id).order_by(table.c.id))])
    # Include category members even when their availability has just been revoked.
    members=m.track_categories
    values.append([list(row) for row in db.session.execute(select(members).join(m.MediaCategory,m.MediaCategory.id==members.c.category_id).where(m.MediaCategory.station_id==station.id).order_by(members.c.category_id,members.c.track_id))])
    # Visual schedules can select songs, artists and albums without any legacy
    # category or playlist membership. Include their current candidates, even
    # disabled ones, so availability and ordering edits invalidate lookahead.
    visual_ref = programming.visual.get('source') if programming.visual else None
    visual_scope = m.Track.id.in_([])
    if visual_ref:
        kind, identifier = visual_ref['kind'], visual_ref['id']
        if kind == 'song':
            visual_scope = m.Track.id == identifier
        elif kind == 'artist':
            visual_scope = m.Track.artist_id.in_(visual_ref.get('artists', [identifier]))
        elif kind == 'album':
            visual_scope = m.Track.album_id == identifier
    tracks=db.session.query(m.Track.id,m.Track.enabled,m.Track.decommissioned_at,m.Track.ingest_status,m.Track.storage_key,
        m.Track.artist,m.Track.title,m.Track.duration_ms,m.Track.loudness_lufs,m.Track.true_peak_db,
        m.Track.audio_kind,m.Track.artist_id,m.Track.album_id,m.Track.disc_number,m.Track.track_number).filter(track_scope(station.id),db.or_(
            visual_scope,
            m.Track.id.in_(select(m.PlaylistItem.track_id).join(m.Playlist,m.Playlist.id==m.PlaylistItem.playlist_id).where(m.Playlist.station_id==station.id)),
            m.Track.categories.any(m.MediaCategory.station_id==station.id),
            m.Track.id.in_(select(m.EventBlockItem.track_id).join(m.EventBlock,m.EventBlock.id==m.EventBlockItem.event_block_id).where(m.EventBlock.station_id==station.id)),
            m.Track.id.in_(select(m.TimedEvent.track_id).where(m.TimedEvent.station_id==station.id)))).order_by(m.Track.id).all()
    values.append([list(row) for row in tracks])
    # Group and block memberships are programming too (including bulk edits).
    for table,parent,key in ((m.imaging_group_assets,m.ImagingGroup,'group_id'),(m.EventBlockItem.__table__,m.EventBlock,'event_block_id')):
        values.append([list(row) for row in db.session.execute(select(table).join(parent,parent.id==table.c[key]).where(parent.station_id==station.id).order_by(*table.primary_key.columns))])
    return hashlib.sha256(json.dumps(values,default=str,separators=(',',':')).encode()).hexdigest()


def checkpoint(station):
    state=station.automation
    clock=db.session.get(m.ClockState,station.id)
    return dict(rotation=state.active_rotation_id,index=state.next_slot_index,
        visual={},
        clock=dict(id=clock.clock_id,occurrence=clock.occurrence_key,index=clock.next_slot_index) if clock else None,
        playlists={str(row.clock_slot_id):dict(occurrence=row.occurrence_key,state=row.state) for row in m.PlaylistCursor.query.filter_by(station_id=station.id)},
        rotations={str(row.rotation_id):row.next_slot_index for row in m.RotationCursor.query.filter_by(station_id=station.id)})


def restore(station,saved):
    if not saved:return
    state=station.automation
    for key,prior in saved.get('visual',{}).items():
        row=db.session.get(m.ScheduleCursor,(station.id,key))
        if row:row.state=prior
    if state.active_rotation_id==saved['rotation']:state.next_slot_index=saved['index']
    clock=db.session.get(m.ClockState,station.id)
    prior=saved.get('clock')
    if clock:
        if prior and clock.clock_id==prior['id'] and clock.occurrence_key==prior['occurrence']:
            clock.next_slot_index=prior['index']
        else:
            clock.next_slot_index=0
    for row in m.PlaylistCursor.query.filter_by(station_id=station.id):
        prior=saved.get('playlists',{}).get(str(row.clock_slot_id))
        row.state=prior['state'] if prior and row.occurrence_key==prior['occurrence'] else {}
    for row in m.RotationCursor.query.filter_by(station_id=station.id):
        row.next_slot_index=saved.get('rotations',{}).get(str(row.rotation_id),0)


def refresh(station,reader,current_signature):
    from app.services.playout_queue import queued_ids,active_ids,socket_identity,remove_future,request_decision_id
    reader.collect(station.slug)
    rows=m.SelectionDecision.query.filter(m.SelectionDecision.station_id==station.id,
        m.SelectionDecision.admin_user_id.is_(None),m.SelectionDecision.playback_bus=='A',
        ~m.SelectionDecision.selection_method.in_(('timed_event','event_block','schedule_insert')),
        m.SelectionDecision.status.in_(('selected','queued','failed')),
        db.or_(m.SelectionDecision.status!='failed',m.SelectionDecision.reason=='programming_refresh_pending'),
        db.or_(m.SelectionDecision.programming_signature.is_(None),m.SelectionDecision.programming_signature!=current_signature,
               m.SelectionDecision.reason=='programming_refresh_pending')).order_by(m.SelectionDecision.id).all()
    if not rows:return False
    identity=socket_identity(station.slug)
    future=queued_ids(station.slug)
    untracked={row.id:row for row in rows if row.status=='selected' and row.liquidsoap_request_id is None}
    if untracked:
        # A worker can die after push succeeds but before recording the request ID.
        # Recover the URI's decision identity instead of leaving an orphan in the queue.
        for request_id in future|active_ids(station.slug):
            row=untracked.get(request_decision_id(station.slug,request_id))
            if row:
                row.liquidsoap_request_id=request_id;row.socket_identity=identity;row.status='queued'
    # Persist intent before the engine mutation. A restarted worker finishes it.
    candidates=[row for row in rows if (row.socket_identity==identity and row.liquidsoap_request_id in future) or row.reason=='programming_refresh_pending']
    for row in candidates:row.reason='programming_refresh_pending'
    db.session.commit()
    ids=[row.liquidsoap_request_id for row in candidates if row.socket_identity==identity and row.liquidsoap_request_id in future]
    if ids:remove_future(station.slug,ids)
    reader.collect(station.slug)
    live=queued_ids(station.slug)|active_ids(station.slug)
    removed=[row for row in candidates if row.status!='started' and (row.socket_identity!=identity or row.liquidsoap_request_id not in live)]
    # Also cancel decisions selected before a worker crash but never submitted.
    removed += [row for row in rows if row.status=='selected' and row.liquidsoap_request_id is None]
    if not removed:return False
    removed.sort(key=lambda row:row.id)
    first=removed[0]
    later_started=m.SelectionDecision.query.filter(m.SelectionDecision.station_id==station.id,
        m.SelectionDecision.id>first.id,m.SelectionDecision.status=='started',m.SelectionDecision.admin_user_id.is_(None),
        ~m.SelectionDecision.selection_method.in_(('timed_event','event_block','schedule_insert')),m.SelectionDecision.playback_bus=='A').first()
    later_block=m.EventBlockExecution.query.filter(m.EventBlockExecution.station_id==station.id,
        m.EventBlockExecution.source=='CLOCK',m.EventBlockExecution.created_at>=first.selected_at).first()
    if not later_started and not later_block:restore(station,first.cursor_checkpoint)
    for row in removed:row.status='failed';row.reason='programming_changed'
    db.session.commit()
    reader.starved_until.pop(station.slug,None)
    return True
