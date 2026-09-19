"""Paginated, station-scoped event audio discovery with playlist priority."""
from sqlalchemy import or_, case, func
from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models import Playlist, PlaylistItem, Track, MusicTag, EventBlock
from app.services.availability import tracks_for, playable
from app.services.timed_events import _integer, _clean


def search(station, query='', kind='ALL', page=1, playlist_id=None):
    page = _integer(page,1,100000,'Page')
    query = _clean(query,150)
    if kind not in ('ALL','PLAYLIST','MUSIC','STATION','COMMERCIALS','EVENT_BLOCK'): raise ValueError('Choose an audio filter')
    pattern = '%'+query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    offset, size = (page-1)*30, 30
    result=[]
    if not playlist_id and kind in ('ALL','PLAYLIST','STATION','COMMERCIALS'):
        playlists = Playlist.query.filter_by(station_id=station.id,deleted_at=None)
        if kind in ('STATION','COMMERCIALS'):playlists=playlists.filter_by(purpose=kind)
        playlists=playlists.filter(or_(Playlist.name.ilike(pattern,escape='\\'),Playlist.purpose.ilike(pattern,escape='\\'))).order_by(case((Playlist.system_key=='STATION',0),(Playlist.system_key=='COMMERCIALS',1),else_=2),Playlist.name,Playlist.id)
        total=playlists.count()
        if offset < total:
            page_rows = playlists.offset(offset).limit(size+1).all()
            counts = {row[0]:row[1:] for row in tracks_for(station.id).filter_by(enabled=True,ingest_status='accepted',decommissioned_at=None).join(PlaylistItem).filter(PlaylistItem.playlist_id.in_([p.id for p in page_rows])).with_entities(PlaylistItem.playlist_id,func.count(Track.id),func.sum(Track.duration_ms),func.max(Track.duration_ms)).group_by(PlaylistItem.playlist_id)}
            for row in page_rows:
                count, duration, longest = counts.get(row.id,(0,0,0))
                result.append(dict(kind='PLAYLIST',identifier=str(row.id),name=row.name,purpose=row.purpose,system=bool(row.system_key),count=count,duration=duration//1000,one_duration=longest//1000,playable=bool(count),unavailable_reason='' if count else 'No enabled audio'))
        offset=max(0,offset-total)
    if kind == 'EVENT_BLOCK':
        from app.models import EventBlockItem
        from app.services.event_blocks import validate_block
        rows=EventBlock.query.options(selectinload(EventBlock.items).joinedload(EventBlockItem.track)).filter_by(station_id=station.id,enabled=True).filter(EventBlock.name.ilike(pattern,escape='\\')).order_by(EventBlock.name,EventBlock.id).offset(offset).limit(size+1).all()
        for row in rows:
            errors=validate_block(row,check_files=False)
            result.append(dict(kind='EVENT_BLOCK',identifier=row.slug,name=row.name,duration=row.duration_ms//1000,playable=not errors,unavailable_reason=errors[0] if errors else ''))
    elif kind != 'PLAYLIST' and len(result) <= size:
        rows=tracks_for(station.id).filter_by(ingest_status='accepted',decommissioned_at=None)
        if kind in ('MUSIC','STATION','COMMERCIALS'):rows=rows.filter_by(audio_kind=kind)
        if playlist_id:
            owned=Playlist.query.filter_by(station_id=station.id,id=_integer(playlist_id,1,2147483647,'Playlist'),deleted_at=None).first()
            if not owned:raise ValueError('Playlist unavailable')
            rows=rows.join(PlaylistItem).filter(PlaylistItem.playlist_id==owned.id)
        rows=rows.filter(or_(Track.title.ilike(pattern,escape='\\'),Track.artist.ilike(pattern,escape='\\'),Track.album.ilike(pattern,escape='\\'),Track.original_filename.ilike(pattern,escape='\\'),Track.cart_code.ilike(pattern,escape='\\'),Track.audio_subtype.ilike(pattern,escape='\\'),Track.tags.any(db.and_(MusicTag.station_id==station.id,MusicTag.name.ilike(pattern,escape='\\')))))
        for row in rows.order_by(case((Track.title==query,0),(Track.cart_code==query,0),else_=1),Track.title,Track.id).offset(offset).limit(size+1-len(result)):
            result.append(dict(kind='TRACK',identifier=row.uuid,name=row.title,artist=row.artist,album=row.album,purpose=row.audio_kind,subtype=row.audio_subtype,cart_code=row.cart_code,duration=row.duration_ms//1000,playable=playable(row,station.id),unavailable_reason='' if playable(row,station.id) else 'Disabled for broadcast',audition=f'/admin/stations/{station.slug}/media/{row.uuid}/audition'))
    return dict(items=result[:size],more=len(result)>size,page=page)
