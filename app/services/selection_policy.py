"""Shared music separation; callers retain their own ordering and cursors."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
from app.models import SelectionDecision, Track


def artist_key(value):
    return ' '.join((value or '').casefold().split())


def recent(station, state, now):
    since = now - timedelta(seconds=max(getattr(state, 'track_separation_seconds', 0), getattr(state, 'artist_separation_seconds', 0), 3600))
    return SelectionDecision.query.options(joinedload(SelectionDecision.track)).filter(
        SelectionDecision.station_id == station.id,
        SelectionDecision.track.has(Track.audio_kind == 'MUSIC'),
        or_(and_(SelectionDecision.status == 'started', SelectionDecision.started_at >= since),
            and_(SelectionDecision.status.in_(('selected', 'submitting', 'queued')),
                 SelectionDecision.selected_at >= since))).all()


def eligible(tracks, history, now, track_seconds, artist_seconds):
    last_track, last_artist = {}, {}
    for item in history:
        if getattr(item, 'track', None) is None or item.track.audio_kind != 'MUSIC':
            continue
        if item.status not in ('started', 'selected', 'submitting', 'queued'):
            continue
        occurred = item.started_at if item.status == 'started' else item.selected_at
        if occurred is None:
            continue
        occurred = occurred.replace(tzinfo=occurred.tzinfo or timezone.utc)
        if occurred > now:
            continue
        last_track[item.track_id] = max(last_track.get(item.track_id, occurred), occurred)
        key = artist_key(item.track.artist)
        if key:
            last_artist[key] = max(last_artist.get(key, occurred), occurred)
    for relaxation, aw, tw in (('none', artist_seconds, track_seconds), ('artist', 0, track_seconds), ('track', 0, 0)):
        pool = [t for t in tracks if t.audio_kind != 'MUSIC' or (
            (not tw or t.id not in last_track or now-last_track[t.id] >= timedelta(seconds=tw)) and
            (not aw or artist_key(t.artist) not in last_artist or now-last_artist[artist_key(t.artist)] >= timedelta(seconds=aw)))]
        if pool:
            return pool, relaxation, last_track
    return [], 'none', last_track


def choose(tracks, history, now, track_seconds, artist_seconds):
    pool, relaxation, last = eligible(tracks, history, now, track_seconds, artist_seconds)
    return (min(pool, key=lambda t: (last.get(t.id, datetime.min.replace(tzinfo=timezone.utc)), t.id)) if pool else None,
            relaxation, len(pool))


def strict_eligible(tracks, history, now, track_seconds, artist_seconds, *, ignore_decision=None):
    """Request policy shares normalization/history but never relaxes separation."""
    history = [item for item in history if item.id != ignore_decision]
    pool, relaxation, _ = eligible(tracks, history, now, track_seconds, artist_seconds)
    return pool if relaxation == 'none' else []
