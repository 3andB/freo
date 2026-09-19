"""Paginated, station-scoped event audio discovery with playlist priority."""
from sqlalchemy import or_, case
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
            for row in playlists.offset(offset).limit(size+1):
                tracks=[i.track for i in row.items if playable(i.track,station.id)]
                result.append(dict(kind='PLAYLIST',identifier=str(row.id),name=row.name,purpose=row.purpose,count=len(tracks),duration=sum(t.duration_ms for t in tracks)//1000,playable=bool(tracks)))
        offset=max(0,offset-total)
    if kind == 'EVENT_BLOCK':
        rows=EventBlock.query.filter_by(station_id=station.id,enabled=True).filter(EventBlock.name.ilike(pattern,escape='\\')).order_by(EventBlock.name,EventBlock.id).offset(offset).limit(size+1).all()
        result=[dict(kind='EVENT_BLOCK',identifier=r.slug,name=r.name,duration=r.duration_ms//1000,playable=True) for r in rows]
    elif kind != 'PLAYLIST' and len(result) <= size:
        rows=tracks_for(station.id).filter_by(ingest_status='accepted',decommissioned_at=None)
        if kind in ('MUSIC','STATION','COMMERCIALS'):rows=rows.filter_by(audio_kind=kind)
        if playlist_id:
            owned=Playlist.query.filter_by(station_id=station.id,id=_integer(playlist_id,1,2147483647,'Playlist'),deleted_at=None).first()
            if not owned:raise ValueError('Playlist unavailable')
            rows=rows.join(PlaylistItem).filter(PlaylistItem.playlist_id==owned.id)
        rows=rows.filter(or_(Track.title.ilike(pattern,escape='\\'),Track.artist.ilike(pattern,escape='\\'),Track.original_filename.ilike(pattern,escape='\\'),Track.cart_code.ilike(pattern,escape='\\'),Track.audio_subtype.ilike(pattern,escape='\\'),Track.tags.any(db.and_(MusicTag.station_id==station.id,MusicTag.name.ilike(pattern,escape='\\')))))
        for row in rows.order_by(case((Track.title==query,0),(Track.cart_code==query,0),else_=1),Track.title,Track.id).offset(offset).limit(size+1-len(result)):
            result.append(dict(kind='TRACK',identifier=row.uuid,name=row.title,artist=row.artist,purpose=row.audio_kind,subtype=row.audio_subtype,cart_code=row.cart_code,duration=row.duration_ms//1000,playable=playable(row,station.id),audition=f'/admin/stations/{station.slug}/media/{row.uuid}/audition'))
    return dict(items=result[:size],more=len(result)>size,page=page)
