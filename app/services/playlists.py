"""Explicit playlist membership and durable, non-repeating playback cycles."""
from datetime import datetime, timezone, timedelta
import uuid
from sqlalchemy.orm import selectinload
from sqlalchemy import case, func
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


def summaries(station_id):
    """Library navigation needs counts, not every playlist's audio objects."""
    rows = db.session.query(Playlist, func.count(PlaylistItem.track_id),
        func.coalesce(func.sum(Track.duration_ms), 0)).outerjoin(PlaylistItem,
        PlaylistItem.playlist_id == Playlist.id).outerjoin(Track, Track.id == PlaylistItem.track_id).filter(
        Playlist.station_id == station_id, Playlist.deleted_at.is_(None)).group_by(Playlist.id).order_by(
        case(*[(Playlist.system_key == key, index) for index, key in enumerate(
            ('PLAYLIST_1', 'PLAYLIST_2', 'STATION', 'COMMERCIALS'))], else_=4), Playlist.id)
    result = []
    for row, count, duration in rows:
        if row.smart_enabled:
            from app.services.smart_playlists import members
            tracks = members(row)
            count, duration = len(tracks), sum(t.duration_ms or 0 for t in tracks)
        result.append(dict(id=row.id, name=row.name, description=row.description, mode=row.mode,
            purpose=row.purpose, system_key=row.system_key, revision=row.revision, count=count,
            duration_ms=duration, smart_enabled=row.smart_enabled))
    return result


def get_playlist(station_id, identifier):
    if isinstance(identifier, bool) or not isinstance(identifier, (int, str)) or not str(identifier).isdecimal():
        raise ValueError('Choose a playlist')
    row = Playlist.query.filter_by(station_id=station_id, id=int(identifier), deleted_at=None).first()
    if row is None:
        raise ValueError('Playlist is unavailable for this station')
    return row


def summary(row):
    from app.services.smart_playlists import members
    tracks = members(row) if row.smart_enabled else [i.track for i in row.items]
    return dict(id=row.id, name=row.name, description=row.description, mode=row.mode,
                purpose=row.purpose, system_key=row.system_key, revision=row.revision, count=len(tracks),
                duration_ms=sum(track.duration_ms or 0 for track in tracks),
                leader_track_id=row.leader_track_id, smart_enabled=row.smart_enabled,
                smart_rules=row.smart_rules, selection_weights=row.selection_weights)


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
    if row.smart_enabled:
        raise ValueError('Edit the smart playlist filters to change its contents')
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


def playable_tracks(row, station_id, storage=None):
    from app.services.automation import _exists
    if not row or row.station_id != station_id or not row.enabled:
        return []
    from app.services.smart_playlists import members
    return [track for track in members(row) if playable(track, station_id)
            and (storage is None or _exists(storage, track.station.slug, track.storage_key))]


def advance(row, tracks, saved, *, exclude=(), history=(), now=None, automation=None, result=None):
    """Pure cursor step: preserve cycles while applying the shared music policy."""
    from app.services.selection_policy import eligible
    from app.services.smart_playlists import weighted_choice
    ids = [track.id for track in tracks]
    state = dict(saved or {})
    if state.get('mode') != row.mode:
        state = {}
    eligible_ids = set(ids)
    played = [i for i in state.get('played', []) if i in eligible_ids]
    if row.mode == 'RANDOM':
        seen = set(played)
        remaining = [i for i in ids if i not in seen]
        if not remaining:
            remaining, played = list(ids), []
            last = state.get('last') or (state.get('played') or [None])[-1]
            if len(remaining) > 1:
                remaining = [i for i in remaining if i != last]
    else:
        last = state.get('last')
        index = (ids.index(last) + 1) % len(ids) if last in ids else 0
        remaining = ids[index:] + ids[:index]
    by_id = {t.id: t for t in tracks}
    pool = [by_id[i] for i in remaining if i not in exclude]
    relaxation = 'none'
    if automation and now:
        pool, relaxation, _ = eligible(pool, history, now, automation.track_separation_seconds, automation.artist_separation_seconds)
    if not pool:
        raise ValueError('Playlist has no remaining playable audio')
    track = weighted_choice(pool, getattr(row, 'selection_weights', None)) if row.mode == 'RANDOM' else pool[0]
    if result is not None:
        result.update(relaxation=relaxation, candidate_count=len(pool))
    state = dict(mode=row.mode, last=track.id)
    if row.mode == 'RANDOM':
        state['played'] = played + [track.id]
    return track, state


class LeaderPending(Exception):
    """Wait for the existing leader request to start before queuing members."""


def leader_track(row, storage=None):
    from app.services.automation import _exists
    if not row:
        return None
    track = row.leader_track
    return track if (track and row.enabled and track.audio_kind in ('MUSIC', 'STATION')
        and playable(track, row.station_id) and (storage is None or _exists(storage, track.station.slug, track.storage_key))) else None


def leader_decisions(row, station_id, occurrence):
    import hashlib
    key = hashlib.sha256(f'{station_id}:{row.id}:{occurrence}'.encode()).hexdigest()
    return key, SelectionDecision.query.filter_by(station_id=station_id, leader_key=key).all()


def leader_due(row, station_id, storage, occurrence):
    if not leader_track(row, storage):
        return False
    _, previous = leader_decisions(row, station_id, occurrence)
    return not any(d.status == 'started' or d.reason == 'playlist_leader_unavailable' for d in previous)


def select_leader(row, station, storage, now, occurrence, context=None):
    """Decisions own pending/confirmed state; cursor rewinds cannot erase airplay."""
    if not row or row.station_id != station.id or not row.enabled or not row.leader_track_id:
        return None
    key, previous = leader_decisions(row, station.id, occurrence)
    if any(d.status == 'started' or d.reason == 'playlist_leader_unavailable' for d in previous):
        return None
    if any(d.status in ('selected', 'submitting', 'queued') for d in previous):
        raise LeaderPending()
    track = leader_track(row, storage)
    if track is None:
        if not any(d.reason == 'playlist_leader_unavailable' for d in previous):
            db.session.add(SelectionDecision(station_id=station.id, leader_key=key, status='failed',
                selected_at=now, selection_method='playlist_leader', reason='playlist_leader_unavailable', **(context or {})))
        return None
    decision = SelectionDecision(station_id=station.id, leader_key=key, track_id=track.id,
        selected_at=now, status='selected', selection_method='playlist_leader',
        candidate_count=1, relaxation='none', **(context or {}))
    db.session.add(decision)
    return decision


def configure(row, data):
    from app.services.smart_playlists import validate_rules, validate_weights
    if 'leader_track_id' in data:
        identifier = data['leader_track_id']
        track = db.session.get(Track, identifier) if type(identifier) is int and 1 <= identifier <= 2147483647 else None
        if identifier is not None and (not track or not playable(track, row.station_id) or track.audio_kind not in ('MUSIC', 'STATION')):
            raise ValueError('Choose an available music track or STATION audio leader')
        row.leader_track = track
    if 'smart_enabled' in data:
        if type(data['smart_enabled']) is not bool:
            raise ValueError('Choose whether this playlist is dynamic')
        if data['smart_enabled'] and row.system_key in ('STATION', 'COMMERCIALS'):
            raise ValueError('System audio collections cannot be dynamic')
        row.smart_enabled = data['smart_enabled']
    if 'smart_rules' in data:
        row.smart_rules = validate_rules(data['smart_rules'], row.station_id)
    if 'selection_weights' in data:
        row.selection_weights = validate_weights(data['selection_weights'], row.station_id)


def select_playlist(station, slot, storage, now, context):
    row = slot.playlist
    leader = select_leader(row, station, storage, now, context['schedule_occurrence'], context)
    if leader:
        return leader
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
        if row.mode != 'RANDOM':
            cursor.state = {}
    result = dict(candidate_count=len(tracks), relaxation='none')
    if row.legacy_imaging_group_id:
        from datetime import timedelta
        history = SelectionDecision.query.filter_by(station_id=station.id,status='started').filter(SelectionDecision.track_id.in_([t.id for t in tracks])).order_by(SelectionDecision.started_at.desc()).all()
        last = {}
        for decision in history: last.setdefault(decision.track_id,decision.started_at.replace(tzinfo=decision.started_at.tzinfo or timezone.utc))
        eligible = [t for t in tracks if t.id not in last or now-last[t.id] >= timedelta(seconds=row.minimum_separation_seconds)] or tracks
        track = min(eligible,key=lambda t:(last.get(t.id,datetime.min.replace(tzinfo=timezone.utc)),t.id))
    else:
        from app.services.selection_policy import recent
        track, cursor.state = advance(row, tracks, cursor.state, history=recent(station, station.automation, now),
            now=now, automation=station.automation, result=result)
    decision = SelectionDecision(station_id=station.id, selected_at=now, track_id=track.id,
        status='selected', selection_method='playlist', **result, **context)
    db.session.add(decision)
    return decision
