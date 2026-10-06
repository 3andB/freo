"""Performance reports over confirmed decisions and existing audience rollups."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import func, case
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import SelectionDecision, AudienceSample, Track, ImagingAsset
from app.services.statistics import window, aggregate, sessions


def capture(decision):
    track = decision.track or decision.imaging_asset
    if decision.performance_snapshot is None and track:
        from app.services.track_audio import decision_duration_ms
        decision.performance_snapshot = dict(
            track_uuid=track.uuid, title=getattr(track,'title',getattr(track,'name','')), artist=getattr(track,'artist',''),
            album=getattr(track, 'album', ''), isrc=getattr(track, 'isrc', None),
            kind=getattr(track, 'audio_kind', 'STATION'), duration_ms=decision_duration_ms(decision))


def query(station, period):
    return SelectionDecision.query.filter(
        SelectionDecision.station_id == station.id, SelectionDecision.status == 'started',
        SelectionDecision.started_at >= datetime.fromtimestamp(period['start'], timezone.utc),
        SelectionDecision.started_at < datetime.fromtimestamp(period['end'], timezone.utc))


def performances(station, period, limit=None, offset=0, audience=True):
    rows = query(station, period).options(joinedload(SelectionDecision.track), joinedload(SelectionDecision.imaging_asset)).order_by(SelectionDecision.started_at.desc(), SelectionDecision.id.desc())
    if limit is not None:
        rows = rows.offset(offset).limit(limit)
    zone = ZoneInfo(station.timezone)
    for row in rows.yield_per(250):
        data = dict(row.performance_snapshot or {})
        origin = 'confirmed snapshot' if data else 'current library metadata'
        if not data:
            track = row.track or row.imaging_asset
            data = dict(track_uuid=track.uuid if track else '',
                title=getattr(track,'title',getattr(track,'name','Unavailable metadata')), artist=getattr(track,'artist',''),
                album=getattr(track, 'album', ''), isrc=getattr(track, 'isrc', None),
                kind=getattr(track, 'audio_kind', ''),
                duration_ms=(row.audio_snapshot or {}).get('duration_ms', getattr(track, 'duration_ms', None)))
        instant = row.started_at.replace(tzinfo=timezone.utc)
        at = int(instant.timestamp())
        observation = AudienceSample.query.filter(AudienceSample.scope == station.id,
            AudienceSample.at.between(at - 45, at + 45), AudienceSample.listeners.isnot(None)).order_by(
                func.abs(AudienceSample.at-at), AudienceSample.at).first() if audience else None
        yield dict(data, decision_id=row.id, played_at=instant.isoformat(),
            local_time=instant.astimezone(zone).isoformat(), metadata_source=origin,
            listeners=observation.listeners if observation else None,
            audience_at=datetime.fromtimestamp(observation.at, timezone.utc).isoformat() if observation else '',
            source_duration_seconds=data['duration_ms']/1000 if data.get('duration_ms') is not None else None)


def summary(station, args):
    period = window(dict(args, timezone=station.timezone), station.timezone)
    audience = aggregate(station.id, period['start'], period['end'])
    listening = sessions.report(station.id, period['start'], period['end'], int(datetime.now(timezone.utc).timestamp()))['sessions']
    return dict(period=period, total_performances=query(station, period).count(),
                audience=audience, sessions=listening, unique_listeners=None)


def tracks(station, period):
    snapshot = SelectionDecision.performance_snapshot
    def field(name, fallback):
        # A missing ISRC at confirmation stays missing even if the catalog is edited later.
        return func.coalesce(case((snapshot['title'].as_string().isnot(None),snapshot[name].as_string()),else_=fallback),'').label(name)
    fields = [field('track_uuid',func.coalesce(Track.uuid,ImagingAsset.uuid)), field('artist',Track.artist),
        field('title',func.coalesce(Track.title,ImagingAsset.name,'Unavailable metadata')),
        field('album',Track.album),field('isrc',Track.isrc)]
    rows = query(station,period).outerjoin(Track, SelectionDecision.track_id==Track.id).outerjoin(
        ImagingAsset,SelectionDecision.imaging_asset_id==ImagingAsset.id).with_entities(
            *fields,func.count(SelectionDecision.id).label('plays')).group_by(*fields).order_by(
                func.count(SelectionDecision.id).desc(),fields[2])
    return (dict(row._mapping) for row in rows.yield_per(250))
