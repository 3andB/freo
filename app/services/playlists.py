"""Explicit playlist membership and durable, non-repeating playback cycles."""
from datetime import datetime, timezone, timedelta
import random
import uuid
from sqlalchemy.orm import selectinload
from sqlalchemy import case
from app.extensions import db
from app.models import (Playlist, PlaylistItem, PlaylistCursor, MusicEdit, Track,
                        MediaCategory, Artist, Album, ClockSlot, ScheduleProgram,
                        ScheduleAssignment, AutomationState, SelectionDecision)
from app.services.availability import tracks_for, available, playable, artists_for, albums_for


def seed_playlists(station_id):
    for number in (1, 2):
        if not Playlist.query.filter_by(station_id=station_id,system_key=f'PLAYLIST_{number}').first():
            db.session.add(Playlist(station_id=station_id, name=f'Playlist {number}',system_key=f'PLAYLIST_{number}'))
    from app.services.audio_classification import defaults
    defaults(station_id)


def listing(station_id):
    return Playlist.query.options(selectinload(Playlist.items).joinedload(PlaylistItem.track)).filter_by(station_id=station_id, deleted_at=None).order_by(case(*[(Playlist.system_key==key, index) for index,key in enumerate(('PLAYLIST_1','PLAYLIST_2','STATION','COMMERCIALS'))],else_=4),Playlist.id).all()


def get_playlist(station_id, identifier):
    if isinstance(identifier, bool) or not isinstance(identifier, (int, str)) or not str(identifier).isdecimal():
        raise ValueError('Choose a playlist')
    row = Playlist.query.filter_by(station_id=station_id, id=int(identifier), deleted_at=None).first()
    if row is None:
        raise ValueError('Playlist is unavailable for this station')
    return row


def summary(row):
    return dict(id=row.id, name=row.name, description=row.description, mode=row.mode,
                purpose=row.purpose, system_key=row.system_key, revision=row.revision, count=len(row.items),
                duration_ms=sum(item.track.duration_ms or 0 for item in row.items))


def ordered_ids(row):
    return [item.track_id for item in sorted(row.items, key=lambda item: item.position)]


def replace_order(row, ids):
    """Move existing positions out of the way before applying the new order."""
    items = {item.track_id: item for item in row.items}
    base = max((item.position for item in row.items), default=0) + len(ids) + 1
    for index, item in enumerate(row.items):
        item.position = base + index
    db.session.flush()
    wanted = set(ids)
    for identifier, item in items.items():
        if identifier not in wanted:
            row.items.remove(item)
    db.session.flush()
    for index, identifier in enumerate(ids, 1):
        if identifier in items:
            items[identifier].position = index
        else:
            row.items.append(PlaylistItem(track_id=identifier, position=index))
    row.revision += 1
    db.session.flush()


def membership(row, songs, operation, user_id):
    if operation not in ('add', 'remove'):
        raise ValueError('Choose add or remove')
    if row.system_key in ('STATION','COMMERCIALS'):
        if operation == 'remove':
            raise ValueError('Reclassify this audio in its editor to remove it from the system collection')
        from app.services.audio_classification import classify
        before = len(row.items)
        for song in songs:
            classify(song, row.purpose, song.audio_subtype if row.purpose == 'STATION' else '', song.cart_code, station_id=row.station_id)
        return None, len(row.items) - before
    before = ordered_ids(row)
    selected = list(dict.fromkeys(song.id for song in songs))
    existing, chosen = set(before), set(selected)
    after = (before + [i for i in selected if i not in existing]) if operation == 'add' else [i for i in before if i not in chosen]
    if after == before:
        return None, 0
    replace_order(row, after)
    edit = MusicEdit(id=str(uuid.uuid4()), station_id=row.station_id, admin_user_id=user_id,
                     kind='playlist', target_id=row.id,
                     changes=[dict(before=before, after=after, revision=row.revision)])
    db.session.add(edit)
    return edit.id, abs(len(after) - len(before))


def undo_edit(edit):
    if edit.undone or datetime.now(timezone.utc) - edit.created_at.replace(tzinfo=timezone.utc) > timedelta(hours=1):
        raise ValueError('Undo is unavailable or expired')
    row = get_playlist(edit.station_id, edit.target_id)
    change = edit.changes[0]
    if row.revision != change['revision'] or ordered_ids(row) != change['after']:
        raise ValueError('This playlist changed again. Review it before editing')
    restored = set(change['before']) - set(change['after'])
    if any(not available(db.session.get(Track, identifier), row.station_id) for identifier in restored):
        raise ValueError('A removed song is no longer available')
    replace_order(row, change['before'])
    edit.undone = True


def source_songs(station_id, kind, identifier):
    if isinstance(identifier, bool) or not isinstance(identifier, (int, str)) or not str(identifier).isdecimal():
        raise ValueError('Choose a collection')
    identifier = int(identifier)
    query = tracks_for(station_id).filter_by(decommissioned_at=None, ingest_status='accepted')
    if kind == 'category':
        source = MediaCategory.query.filter_by(station_id=station_id, id=identifier).first()
        if not source:
            raise ValueError('Category is unavailable')
        query = query.filter(Track.categories.any(MediaCategory.id == source.id))
    elif kind == 'artist':
        source = artists_for(station_id).filter(Artist.id == identifier).first()
        if not source:
            raise ValueError('Artist is unavailable')
        query = query.filter(Track.artist_id == source.id)
    elif kind == 'album':
        source = albums_for(station_id).filter(Album.id == identifier).first()
        if not source:
            raise ValueError('Album is unavailable')
        query = query.filter(Track.album_id == source.id)
    else:
        raise ValueError('Choose a category, artist, or album')
    order = [Track.disc_number.asc().nullslast(), Track.track_number.asc().nullslast(), Track.title, Track.id]
    if kind != 'album':
        order = [Track.artist, Track.album] + order
    return query.order_by(*order).all()


def delete_playlist(row):
    from app.models import TimedEvent
    if row.system_key in ('STATION','COMMERCIALS'):
        raise ValueError('STATION and COMMERCIALS are permanent audio collections')
    if TimedEvent.query.filter_by(playlist_id=row.id).first():
        raise ValueError('Remove this playlist from its events before deleting it')
    slots = ClockSlot.query.filter_by(playlist_id=row.id).all()
    clock_ids = [slot.clock_id for slot in slots]
    if clock_ids and (ScheduleProgram.query.filter(ScheduleProgram.clock_id.in_(clock_ids), ScheduleProgram.enabled.is_(True)).first()
            or ScheduleAssignment.query.filter(ScheduleAssignment.clock_id.in_(clock_ids), ScheduleAssignment.enabled.is_(True)).first()
            or AutomationState.query.filter(AutomationState.default_clock_id.in_(clock_ids)).first()):
        raise ValueError('Remove this playlist from the schedule before deleting it')
    # Retain identities for past selections; library audio is untouched.
    row.deleted_at = datetime.now(timezone.utc)
    for slot in slots:
        slot.clock.enabled = False


def playable_tracks(row, station_id, storage):
    from app.services.automation import _exists
    if not row or row.station_id != station_id or not row.enabled:
        return []
    return [item.track for item in sorted(row.items, key=lambda item: item.position)
            if playable(item.track, station_id) and _exists(storage, item.track.station.slug, item.track.storage_key)]


def advance(row, tracks, saved):
    """Pure cursor step shared by broadcast selection and read-only rehearsal."""
    ids = [track.id for track in tracks]
    eligible = set(ids)
    state = dict(saved or {})
    if state.get('mode') != row.mode:
        state = {}
    if row.mode == 'RANDOM':
        played = [i for i in state.get('played', []) if i in eligible]
        seen = set(played)
        remaining = [i for i in ids if i not in seen]
        if not remaining:
            remaining = list(ids)
            played = []
        identifier = random.choice(remaining)
        state = dict(mode=row.mode, played=played + [identifier])
    else:
        last = state.get('last')
        index = (ids.index(last) + 1) % len(ids) if last in ids else 0
        identifier = ids[index]
        state = dict(mode=row.mode, last=identifier)
    return next(track for track in tracks if track.id == identifier), state


def select_playlist(station, slot, storage, now, context):
    row = slot.playlist
    tracks = playable_tracks(row, station.id, storage)
    if not tracks:
        db.session.add(SelectionDecision(station_id=station.id, selected_at=now, status='failed',
            selection_method='playlist', reason='empty_or_unavailable_playlist', **context))
        return None
    cursor = PlaylistCursor.query.filter_by(station_id=station.id, clock_slot_id=slot.id).with_for_update().first()
    if cursor is None:
        cursor = PlaylistCursor(station_id=station.id, clock_slot_id=slot.id, occurrence_key=context['schedule_occurrence'], state={})
        db.session.add(cursor)
    if cursor.occurrence_key != context['schedule_occurrence']:
        cursor.occurrence_key = context['schedule_occurrence']
        cursor.state = {}
    if row.legacy_imaging_group_id:
        from datetime import timedelta
        history = SelectionDecision.query.filter_by(station_id=station.id,status='started').filter(SelectionDecision.track_id.in_([t.id for t in tracks])).order_by(SelectionDecision.started_at.desc()).all()
        last = {}
        for decision in history: last.setdefault(decision.track_id,decision.started_at.replace(tzinfo=decision.started_at.tzinfo or timezone.utc))
        eligible = [t for t in tracks if t.id not in last or now-last[t.id] >= timedelta(seconds=row.minimum_separation_seconds)] or tracks
        track = min(eligible,key=lambda t:(last.get(t.id,datetime.min.replace(tzinfo=timezone.utc)),t.id))
    else:
        track, cursor.state = advance(row, tracks, cursor.state)
    decision = SelectionDecision(station_id=station.id, selected_at=now, track_id=track.id,
        status='selected', selection_method='playlist', candidate_count=len(tracks), relaxation='none', **context)
    db.session.add(decision)
    return decision
