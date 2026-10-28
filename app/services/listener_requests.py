"""Durable listener intent. Selection stays in the existing scheduler/worker."""
from datetime import datetime, timedelta, timezone
from app.extensions import db
from app.models import ListenerRequest, RequestRateBucket, SelectionDecision, Station, Track
from app.services.availability import playable, tracks_for
from app.services.selection_policy import artist_key

DEFAULTS = dict(enabled=False, delay_songs=3, track_songs=10, artist_songs=3,
                restrict_programming=True, cooldown_minutes=5, listener_limit=2, station_limit=100)
FIELDS = [('delay_songs', 'Play requested track after (songs)', 0, 1000),
          ('track_songs', 'Songs before repeating the requested track', 0, 1000),
          ('artist_songs', 'Songs before repeating the requested artist', 0, 1000),
          ('cooldown_minutes', 'Listener cooldown (minutes)', 0, 1440),
          ('listener_limit', 'Maximum outstanding per listener', 1, 100),
          ('station_limit', 'Maximum outstanding for this station', 1, 10000)]
OUTSTANDING = ('pending', 'eligible', 'queued')
TERMINAL = ('played', 'rejected', 'expired')
SAFE_FAILURES = ('programming_changed', 'request_not_started', 'playout_restarted', 'listener_request_cancelled')


def utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def settings(station):
    return dict(DEFAULTS, **(station.request_settings or {}))


def save_settings(station, form):
    if 'requests_present' not in form:
        return
    result = {key: form.get('request_' + key) == 'yes' for key in ('enabled', 'restrict_programming')}
    for key, label, low, high in FIELDS:
        raw = form.get('request_' + key, '')
        if not raw.isdecimal() or not low <= int(raw) <= high:
            raise ValueError(f'{label}: enter a whole number from {low} to {high}.')
        result[key] = int(raw)
    station.request_settings = result


def lock(station):
    # Shared order with automation, deck operations and public submission.
    db.session.query(Station).filter_by(id=station.id).with_for_update().populate_existing().one()


def catalog(station):
    return tracks_for(station.id).filter_by(audio_kind='MUSIC', enabled=True,
        ingest_status='accepted', decommissioned_at=None)


def rate_limit(station, key, kind, limit, now):
    minute = int(now.timestamp()) // 60
    row = db.session.get(RequestRateBucket, (station.id, key, kind, minute))
    if row and row.count >= limit:
        return False
    if row is None:
        row = RequestRateBucket(station_id=station.id, key=key, kind=kind, minute=minute, count=0)
        db.session.add(row)
    row.count += 1
    return True


def submit(station, track_uuid, listener, nonce, now=None):
    now = now or datetime.now(timezone.utc)
    lock(station)
    config = settings(station)
    if not config['enabled'] or not station.enabled or station.deleted_at or station.lifecycle_state in ('pending_delete', 'delete_failed'):
        raise ValueError('Requests are currently disabled.')
    prior = ListenerRequest.query.filter_by(station_id=station.id, listener_key=listener, nonce=nonce).first()
    if prior:
        return prior
    track = catalog(station).filter_by(uuid=track_uuid).first()
    if not track:
        raise ValueError('This song is no longer available for requests.')
    from app.services.automation import _exists
    from app.services.media_storage import LocalMediaStorage
    if not _exists(LocalMediaStorage(), track.station.slug, track.storage_key):
        raise ValueError('This song is no longer available for requests.')
    maintain(station, now)
    outstanding = ListenerRequest.query.filter_by(station_id=station.id).filter(ListenerRequest.status.in_(OUTSTANDING))
    duplicate = outstanding.filter_by(listener_key=listener, track_id=track.id).first()
    if duplicate:
        return duplicate
    last = ListenerRequest.query.filter_by(station_id=station.id, listener_key=listener).order_by(ListenerRequest.created_at.desc()).first()
    if last and now < utc(last.created_at) + timedelta(minutes=config['cooldown_minutes']):
        raise ValueError('Please wait for the listener cooldown before requesting another song.')
    if outstanding.count() >= config['station_limit']:
        raise ValueError('The station request queue is full. Please try later.')
    if outstanding.filter_by(listener_key=listener).count() >= config['listener_limit']:
        raise ValueError('You already have the maximum number of outstanding requests.')
    row = ListenerRequest(station_id=station.id, track=track, listener_key=listener, nonce=nonce,
        created_at=now, expires_at=now + timedelta(hours=24), status='pending', reason='Waiting for music selection')
    db.session.add(row)
    db.session.flush()
    return row


def music_history(station, now):
    return SelectionDecision.query.join(Track).filter(SelectionDecision.station_id == station.id,
        SelectionDecision.status == 'started', SelectionDecision.started_at <= now,
        SelectionDecision.playback_bus != 'CART', Track.audio_kind == 'MUSIC')


def eligibility_history(station, now):
    from sqlalchemy.orm import joinedload
    from app.services.selection_policy import recent
    history = music_history(station, now).options(joinedload(SelectionDecision.track)).order_by(
        SelectionDecision.started_at.desc(), SelectionDecision.id.desc()).limit(1001).all()
    pending = SelectionDecision.query.options(joinedload(SelectionDecision.track)).join(Track).filter(
        SelectionDecision.station_id == station.id, SelectionDecision.status.in_(('selected', 'submitting', 'queued')),
        Track.audio_kind == 'MUSIC').all()
    from app.models import LiveQueueSnapshot
    snapshot = db.session.get(LiveQueueSnapshot, station.id)
    audible = set()
    if snapshot and snapshot.observed_at and now - utc(snapshot.observed_at) <= timedelta(seconds=10):
        mixer = snapshot.mixer or {}
        audible = {mixer.get(deck + '_id') for deck in ('a', 'b') if mixer.get(deck + '_playing')}
        if snapshot.current_decision_id:
            audible.add(snapshot.current_decision_id)
    return history, recent(station, station.automation, now) if station.automation else [], pending, audible


def reason(row, station, tracks=None, now=None, ignore_decision=None, history=None):
    """Strict policy: no exhaustion relaxation, and no queued starts counted."""
    now = now or datetime.now(timezone.utc)
    cfg = settings(station)
    if row.status in TERMINAL:
        return row.status
    if not cfg['enabled']:
        return 'Requests are disabled'
    if utc(row.expires_at) <= now:
        return 'Request expired'
    track = row.track
    if not playable(track, station.id) or track.audio_kind != 'MUSIC':
        return 'Song unavailable'
    if cfg['restrict_programming'] and tracks is not None and track.id not in {t.id for t in tracks}:
        return 'Waiting for matching programming'
    recent, separation, pending, audible = history or eligibility_history(station, now)
    count = sum(utc(item.started_at) > utc(row.created_at) for item in recent)
    if count < cfg['delay_songs']:
        return f"Waiting for {cfg['delay_songs'] - count} more song starts"
    for index, item in enumerate(recent):
        if item.track_id == track.id and (index == 0 or item.id in audible or index < cfg['track_songs']):
            return 'Waiting for track separation'
        if artist_key(track.artist) and artist_key(item.track.artist) == artist_key(track.artist) and index < cfg['artist_songs']:
            return 'Waiting for artist separation'
    from app.services.selection_policy import strict_eligible
    state = station.automation
    if state and not strict_eligible([track], separation, now,
            state.track_separation_seconds, state.artist_separation_seconds, ignore_decision=ignore_decision):
        return 'Waiting for automation separation'
    for item in pending:
        if item.id == ignore_decision:
            continue
        if item.track_id == track.id or (cfg['artist_songs'] and artist_key(track.artist) and artist_key(track.artist) == artist_key(item.track.artist)):
            return 'Waiting for a queued song'
    return ''


def choose(station, tracks, storage, now, *, fixed=False):
    if fixed or not settings(station)['enabled'] or (station.automation and station.automation.operator_mode != 'AUTO'):
        return None
    from app.models import ScheduleTransition
    from app.services.event_blocks import active_execution
    if active_execution(station.id) or ScheduleTransition.query.filter_by(station_id=station.id).filter(
            ScheduleTransition.state.in_(('PENDING', 'PREPARING', 'FADING'))).first():
        return None
    # select_next has already locked Station before the existing cursor locks.
    maintain(station, now)
    from sqlalchemy.orm import joinedload
    rows = ListenerRequest.query.options(joinedload(ListenerRequest.track)).filter_by(station_id=station.id).filter(
        ListenerRequest.status.in_(('pending', 'eligible'))).order_by(ListenerRequest.created_at, ListenerRequest.id).all()
    if not rows:
        return None
    history = eligibility_history(station, now)
    for row in rows:
        waiting = reason(row, station, tracks, now, history=history)
        if not waiting:
            from app.services.automation import _exists
            if not _exists(storage, row.track.station.slug, row.track.storage_key):
                waiting = 'Song audio unavailable'
        row.reason = waiting or 'Eligible for this music selection'
        row.status = 'pending' if waiting else 'eligible'
        if not waiting:
            return row
    return None


def bind(row, decision, now):
    if row:
        if row.status not in ('pending', 'eligible') or row.station_id != decision.station_id or row.track_id != decision.track_id:
            raise ValueError('Request changed before it could be selected')
        decision.listener_request_id = row.id
        row.status = 'queued'
        row.reason = 'Waiting for confirmed playback'
        row.evidence = dict(selected_at=now.isoformat(), occurrence=decision.schedule_occurrence,
                            settings=settings(decision.station or db.session.get(Station, row.station_id)))


def confirmed(decision, at):
    if decision.listener_request_id:
        row = ListenerRequest.query.filter_by(id=decision.listener_request_id).with_for_update().populate_existing().first()
        if row and row.station_id == decision.station_id and row.track_id == decision.track_id:
            row.status = 'played'
            row.played_at = at
            row.reason = 'Confirmed playback start'


def maintain(station, now=None):
    now = now or datetime.now(timezone.utc)
    rows = ListenerRequest.query.filter_by(station_id=station.id).filter(ListenerRequest.status.in_(OUTSTANDING)).all()
    for row in rows:
        if utc(row.expires_at) <= now:
            row.status, row.reason = 'expired', 'Not played within 24 hours'
        elif row.status == 'queued':
            attempts = SelectionDecision.query.filter_by(listener_request_id=row.id).all()
            if attempts and all(d.status == 'failed' and d.reason in SAFE_FAILURES for d in attempts):
                row.status, row.reason = 'pending', 'Waiting after cancelled selection'
    cutoff = now - timedelta(minutes=max(settings(station)['cooldown_minutes'], 1))
    for row in ListenerRequest.query.filter_by(station_id=station.id).filter(
            ListenerRequest.status.in_(TERMINAL), ListenerRequest.created_at < cutoff,
            ListenerRequest.listener_key.isnot(None)).all():
        row.listener_key = None
        row.nonce = None



def housekeeping():
    """Bound periodic work; stopped stations still expire and shed anonymous keys."""
    import time
    from flask import current_app
    at = time.monotonic()
    if at < current_app.extensions.get('listener_request_cleanup_at', 0):
        return
    now = datetime.now(timezone.utc)
    station_ids = db.session.query(ListenerRequest.station_id).filter(db.or_(
        ListenerRequest.status.in_(OUTSTANDING), ListenerRequest.listener_key.isnot(None))).distinct()
    for station in Station.query.filter(Station.id.in_(station_ids)).all():
        lock(station)
        maintain(station, now)
        db.session.commit()
    RequestRateBucket.query.filter(RequestRateBucket.minute < int(now.timestamp()) // 60 - 1440).delete(synchronize_session=False)
    db.session.commit()
    current_app.extensions['listener_request_cleanup_at'] = at + 30

def programming_tracks(station, now=None):
    """Read existing programming without moving cursors (DJ validation)."""
    from app.services.schedule import resolve, usable_clock
    from app.services.visual_schedule import source_tracks
    from app.models import ClockState
    from app.services.event_blocks import active_execution
    if active_execution(station.id):
        return [], True
    resolved = resolve(station, now)
    if resolved.visual is not None:
        from app.services.visual_schedule import fallback
        from app.services.media_storage import LocalMediaStorage
        ref = resolved.visual.get('source')
        tracks = source_tracks(station, ref, LocalMediaStorage())
        if not tracks:
            ref = fallback(station)
            tracks = source_tracks(station, ref, LocalMediaStorage())
        return tracks, bool(resolved.visual.get('insert') or (ref and ref['kind'] == 'song'))
    state = station.automation
    if not state:
        return [], False
    clock = resolved.clock or (state.default_clock if usable_clock(state.default_clock, station.id) else None)
    if clock:
        slots = [s for s in clock.slots if s.enabled]
        cursor = ClockState.query.filter_by(station_id=station.id).first()
        slot = slots[(cursor.next_slot_index if cursor and cursor.clock_id == clock.id else 0) % len(slots)] if slots else None
        if not slot or slot.slot_type not in ('PLAYLIST', 'CATEGORY', 'ROTATION'):
            return [], True
        if slot.slot_type != 'ROTATION':
            return source_tracks(station, dict(kind=slot.slot_type.lower(), id=slot.playlist_id if slot.slot_type == 'PLAYLIST' else slot.category_id)), False
        rotation = slot.rotation
    else:
        rotation = state.active_rotation
    if not rotation or not rotation.enabled:
        return [], False
    from app.models import RotationCursor
    slots = [s for s in rotation.slots if s.enabled]
    cursor = state if state.active_rotation_id == rotation.id else RotationCursor.query.filter_by(station_id=station.id, rotation_id=rotation.id).first()
    slot = slots[(cursor.next_slot_index if cursor else 0) % len(slots)] if slots else None
    return (source_tracks(station, dict(kind='category', id=slot.category_id)) if slot else []), False


class RequestIneligible(ValueError):
    pass


def validate_decision(decision, now=None, *, later_queued=()):
    if not decision.listener_request_id:
        return
    station = decision.station
    lock(station)
    row = db.session.get(ListenerRequest, decision.listener_request_id)
    tracks, fixed = programming_tracks(station, now)
    # Automatic selections carry their resolved slot; its cursor already advanced.
    if decision.admin_user_id is None:
        from app.services.programming_refresh import signature
        if decision.programming_signature and decision.programming_signature != signature(station, now):
            raise RequestIneligible('Programming changed before request playback')
        fixed = False
        from app.services.visual_schedule import source_tracks
        if decision.category_id:
            tracks = source_tracks(station, dict(kind='category', id=decision.category_id))
        elif decision.clock_slot_id and decision.clock_slot and decision.clock_slot.playlist_id:
            tracks = source_tracks(station, dict(kind='playlist', id=decision.clock_slot.playlist_id))
    history = None
    if later_queued:
        recent, separation, pending, audible = eligibility_history(station, now or datetime.now(timezone.utc))
        # Rechecking a queued request must respect the engine's actual order.
        # A later automatic repeat cannot retroactively evict its predecessor.
        # Confirmed starts and other live/deck sources still count in full.
        history = (recent, [item for item in separation if item.status=='started' or item.id not in later_queued],
                   [item for item in pending if item.id not in later_queued], audible)
    waiting = reason(row, station, tracks, now, ignore_decision=decision.id, history=history) if row else 'Request unavailable'
    if fixed or waiting:
        raise RequestIneligible(waiting or 'Waiting for flexible music programming')


def reconcile_engine(station, identity, live, complete):
    """Worker-only recovery/cancellation using the existing engine inventory.

    An uncertain submission is never retried just because its DB write failed.
    """
    import time
    from flask import current_app
    from app.services.playout_queue import request_decision_id, mixer_state, deck_control, queued_order
    lock(station)
    rows = SelectionDecision.query.join(ListenerRequest, ListenerRequest.id == SelectionDecision.listener_request_id).filter(
        SelectionDecision.station_id == station.id, SelectionDecision.status != 'started',
        db.or_(ListenerRequest.status.in_(OUTSTANDING), SelectionDecision.status.in_(('selected','submitting','queued')))).all()
    if not rows:
        return
    observed = {request_decision_id(station.slug, rid): rid for rid in live} if complete else {}
    queue_order = queued_order(station.slug) if complete else []
    by_request = {rid: identifier for identifier, rid in observed.items()}
    missing = current_app.extensions.setdefault('listener_request_missing', {})
    now = datetime.now(timezone.utc)
    maintain(station, now)
    for decision in rows:
        row = db.session.get(ListenerRequest, decision.listener_request_id)
        if decision.id in observed:
            decision.liquidsoap_request_id = observed[decision.id]
            decision.socket_identity = identity
            decision.status = 'queued'
            if row and row.status not in TERMINAL:
                row.status, row.reason = 'queued', 'Waiting for confirmed playback'
            missing.pop(decision.id, None)
        elif complete and decision.status in ('failed', 'submitting', 'selected') and decision.reason not in SAFE_FAILURES:
            since = missing.setdefault(decision.id, time.monotonic())
            if time.monotonic() - since >= 10:
                decision.status, decision.reason = 'failed', 'request_not_started'
                missing.pop(decision.id, None)
        invalid = row is None or row.status in TERMINAL or not settings(station)['enabled']
        if not invalid and decision.status in ('selected', 'queued'):
            try:
                position = queue_order.index(decision.liquidsoap_request_id) if decision.liquidsoap_request_id in queue_order else None
                later = {by_request[rid] for rid in queue_order[position+1:] if rid in by_request} if position is not None else set()
                validate_decision(decision, now, later_queued=later)
            except ValueError:
                invalid = True
        if not invalid or decision.status not in ('selected', 'queued'):
            continue
        if decision.admin_user_id is None:
            # Invalidate the automatic tail together so refresh can restore the
            # earliest checkpoint without leaving later cursor steps queued.
            tail = SelectionDecision.query.filter(SelectionDecision.station_id == station.id,
                SelectionDecision.id >= decision.id, SelectionDecision.admin_user_id.is_(None),
                SelectionDecision.playback_bus == 'A', SelectionDecision.status.in_(('selected', 'queued')),
                ~SelectionDecision.selection_method.in_(('timed_event', 'event_block', 'schedule_insert'))).all()
            for future in tail:
                future.programming_signature = None
                future.reason = 'programming_refresh_pending'
        elif complete:
            mixer = mixer_state(station.slug)
            deck = decision.playback_bus.lower()
            if mixer.get(deck + '_id') == decision.id and mixer.get(deck + '_playing'):
                continue
            if decision.id in observed:
                if mixer.get(deck + '_id') not in (None, decision.id):
                    continue
                deck_control(station.slug, decision.playback_bus, 'clear')
            decision.status, decision.reason = 'failed', 'listener_request_cancelled'
    db.session.commit()
