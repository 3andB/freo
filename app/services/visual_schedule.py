"""One validated composition and recurrence contract for editors and playout.

Documents contain stable, station-validated references; revisions are immutable.
All times inside compositions are seconds, and calendar times are local wall time.
"""
import calendar as month_calendar
import copy
import hashlib
import json
import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import or_
from app.extensions import db
from app.models import (ChannelSchedule, ScheduleComposition, ScheduleCompositionRevision,
                        ScheduleTransition, ScheduleCursor, Playlist, PlaylistItem, Track,
                        Artist, Album, MediaCategory, Clock, SelectionDecision, ImagingAsset, EventBlock, MusicTag, track_categories)
from app.services.availability import tracks_for, artists_for, albums_for, playable
from app.services.schedule import _wall_to_utc, utc_instant

MODES = ('CALENDAR', 'BLOCKS', 'SIMPLE')
KINDS = ('block', 'show', 'category', 'playlist', 'artist', 'album', 'song')


def integer(value, low, high, label='Value'):
    if isinstance(value, bool):
        raise ValueError(f'{label} must be a whole number')
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise ValueError(f'{label} must be a whole number') from None
    if str(result) != str(value) or not low <= result <= high:
        raise ValueError(f'{label} must be between {low} and {high}')
    return result


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f'Enter text of at most {limit} characters')
    return value.strip()


def policy(station, create=False):
    row = db.session.get(ChannelSchedule, station.id)
    if row is None and create:
        row = ChannelSchedule(station_id=station.id)
        db.session.add(row)
        db.session.flush()
    return row


def source(station, ref, *, allow_show=True, allow_block=False, allow_legacy=False):
    if not isinstance(ref, dict):
        raise ValueError('Choose a source')
    kind = ref.get('kind')
    identifier = integer(ref.get('id'), 1, 2147483647, 'Source')
    if kind in ('show', 'block') and (allow_show if kind == 'show' else allow_block):
        row = ScheduleComposition.query.filter_by(id=identifier, station_id=station.id, kind=kind.upper(), archived=False).first()
        if row:
            revision = integer(ref.get('version', row.revision), 1, row.revision, 'Revision')
            version = ScheduleCompositionRevision.query.filter_by(composition_id=row.id, version=revision).first()
            if version:
                return dict(kind=kind, id=row.id, version=version.version, name=row.name, duration=version.duration)
        raise ValueError('This composition revision is unavailable')
    elif kind == 'song':
        row = tracks_for(station.id).filter_by(id=identifier, enabled=True, ingest_status='accepted', decommissioned_at=None).first()
        if row:
            return dict(kind=kind, id=row.id, name=f'{row.title} — {row.artist}', duration=max(1, (row.duration_ms or 180000)//1000))
    elif kind == 'category':
        row = MediaCategory.query.filter_by(id=identifier, station_id=station.id, enabled=True).first()
    elif kind == 'playlist':
        row = Playlist.query.filter_by(id=identifier, station_id=station.id, deleted_at=None).first()
    elif kind == 'artist':
        row = artists_for(station.id).filter_by(id=identifier).first()
    elif kind == 'album':
        row = albums_for(station.id).filter_by(id=identifier).first()
    elif kind == 'legacy' and allow_legacy:
        row = Clock.query.filter_by(id=identifier, station_id=station.id, enabled=True).first()
    else:
        row = None
    if not row:
        raise ValueError('This source is unavailable for this station')
    return dict(kind=kind, id=row.id, name=getattr(row, 'name', None) or getattr(row, 'title', ''), duration=3600,
                order=ref.get('order', 'default') if ref.get('order') in ('default', 'straight', 'shuffle') else 'default')


def search_sources(station, kind, query='', page=1):
    page = integer(page, 1, 100000, 'Page')
    query = text(query, 150)
    pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    if kind in ('show', 'block'):
        q = ScheduleComposition.query.filter_by(station_id=station.id, kind=kind.upper(), archived=False)
        q = q.filter(ScheduleComposition.name.ilike(pattern, escape='\\')).order_by(ScheduleComposition.name, ScheduleComposition.id)
    elif kind == 'song':
        q = tracks_for(station.id).filter_by(enabled=True, ingest_status='accepted', decommissioned_at=None)
        q = q.filter(or_(Track.title.ilike(pattern, escape='\\'), Track.artist.ilike(pattern, escape='\\'), Track.album.ilike(pattern, escape='\\'), Track.tags.any(db.and_(MusicTag.station_id==station.id, MusicTag.name.ilike(pattern, escape='\\'))))).order_by(Track.title, Track.id)
    elif kind == 'artist':
        q = artists_for(station.id).filter(Artist.name.ilike(pattern, escape='\\')).order_by(Artist.name, Artist.id)
    elif kind == 'album':
        q = albums_for(station.id).filter(Album.title.ilike(pattern, escape='\\')).order_by(Album.title, Album.id)
    elif kind == 'playlist':
        q = Playlist.query.filter_by(station_id=station.id, deleted_at=None).filter(Playlist.name.ilike(pattern, escape='\\')).order_by(Playlist.name, Playlist.id)
    elif kind == 'category':
        q = MediaCategory.query.filter_by(station_id=station.id, enabled=True).filter(MediaCategory.name.ilike(pattern, escape='\\')).order_by(MediaCategory.name, MediaCategory.id)
    elif kind == 'sequence':
        q = EventBlock.query.filter_by(station_id=station.id, enabled=True).filter(EventBlock.name.ilike(pattern, escape='\\')).order_by(EventBlock.name, EventBlock.id)
    else:
        raise ValueError('Choose a source type')
    rows = q.offset((page-1)*40).limit(41).all()
    counts={}
    ids=[r.id for r in rows[:40]]
    songs=tracks_for(station.id).filter_by(enabled=True,ingest_status='accepted',decommissioned_at=None)
    if kind in ('artist','album'):
        key=Track.artist_id if kind=='artist' else Track.album_id
        counts=dict(songs.with_entities(key,db.func.count(Track.id)).filter(key.in_(ids)).group_by(key).all())
    elif kind=='playlist':
        counts=dict(songs.join(PlaylistItem,PlaylistItem.track_id==Track.id).with_entities(PlaylistItem.playlist_id,db.func.count(Track.id)).filter(PlaylistItem.playlist_id.in_(ids)).group_by(PlaylistItem.playlist_id).all())
    elif kind=='category':
        counts=dict(songs.join(track_categories,track_categories.c.track_id==Track.id).with_entities(track_categories.c.category_id,db.func.count(Track.id)).filter(track_categories.c.category_id.in_(ids)).group_by(track_categories.c.category_id).all())
    result = []
    for row in rows[:40]:
        if kind in ('imaging', 'sequence'):
            item=dict(kind=kind,id=row.id,name=row.name,identifier=row.uuid if kind=='imaging' else row.slug,duration=(row.duration_ms or 0)//1000)
            if kind=='imaging':item['audition']=f'/admin/stations/{station.slug}/schedule-studio/audio/{row.id}'
            result.append(item)
        else:
            item = dict(kind='song',id=row.id,name=f'{row.title} — {row.artist}',duration=max(1,(row.duration_ms or 180000)//1000)) if kind=='song' else source(station,dict(kind=kind,id=row.id),allow_block=True)
            if kind == 'song':
                item['identifier'] = row.uuid
                item['audition']=f'/admin/stations/{station.slug}/media/{row.uuid}/audition'
                if row.catalog_album and (row.catalog_album.cover_id or row.catalog_album.artwork_key):
                    item['artwork']=f'/admin/stations/{station.slug}/media/albums/{row.album_id}/artwork'
            if kind in ('artist','album','playlist','category'):item['count']=counts.get(row.id,0)
            result.append(item)
    return dict(items=result, more=len(rows)>40, page=page)


def clean_sections(station, sections, duration, kind):
    if not isinstance(sections, list) or len(sections)>500:
        raise ValueError('Use at most 500 sections')
    result, ids = [], set()
    for item in sections:
        if not isinstance(item, dict):
            raise ValueError('Each section must be an object')
        identity = str(item.get('id') or uuid.uuid4())
        if len(identity)>36 or identity in ids:
            raise ValueError('Section identities must be unique')
        ids.add(identity)
        start = integer(item.get('start'), 0, duration-1, 'Start')
        end = integer(item.get('end'), start+1, duration, 'End')
        ref = source(station, item.get('source'), allow_show=kind=='BLOCK')
        artists = item.get('artists', item.get('source',{}).get('artists',[]))
        if artists:
            if ref['kind'] != 'artist' or not isinstance(artists, list) or len(artists)>100:
                raise ValueError('Only artist sections can contain an artist group')
            members=[source(station,dict(kind='artist',id=i)) for i in dict.fromkeys([ref['id']]+artists)]
            ref['artists']=[member['id'] for member in members]
            ref['name']=' + '.join(member['name'] for member in members)
        inserts = []
        if not isinstance(item.get('inserts', []), list):
            raise ValueError('Inserts must be a list')
        for insert in item.get('inserts', []):
            if not isinstance(insert, dict):
                raise ValueError('Each insert must be an object')
            if len(inserts)>=100:
                raise ValueError('Use at most 100 inserts per section')
            target = source(station, insert.get('source'), allow_show=False)
            if target['kind'] != 'song':
                raise ValueError('Play-once inserts must be songs')
            inserts.append(dict(id=str(insert.get('id') or uuid.uuid4())[:36], at=integer(insert.get('at'), start, end-1, 'Insert time'), source=target))
        result.append(dict(id=identity, start=start, end=end, source=ref, inserts=inserts))
    result.sort(key=lambda x:x['start'])
    if any(b['start']<a['end'] for a,b in zip(result,result[1:])):
        raise ValueError('Sections overlap. Move, split, or replace the occupied interval.')
    return result


def save_composition(station, data):
    kind = data.get('kind')
    if kind not in ('SHOW','BLOCK'):
        raise ValueError('Choose Show or Block')
    duration = 86400 if kind=='BLOCK' else integer(data.get('duration'),900,86400,'Show duration')
    sections = clean_sections(station, data.get('sections', []), duration, kind)
    row = None
    if data.get('id'):
        row = ScheduleComposition.query.filter_by(station_id=station.id,id=data['id'],kind=kind).with_for_update().first()
        if not row or row.revision != data.get('revision'):
            raise ValueError('This composition changed. Reload before saving.')
        row.revision += 1
    else:
        row = ScheduleComposition(station_id=station.id,kind=kind,revision=1)
        db.session.add(row)
    row.name = text(data.get('name',''),120,True)
    row.description = text(data.get('description',''),500)
    db.session.flush()
    version = ScheduleCompositionRevision(composition_id=row.id,version=row.revision,duration=duration,sections=sections)
    db.session.add(version)
    return row


def composition_json(row):
    version = ScheduleCompositionRevision.query.filter_by(composition_id=row.id,version=row.revision).one()
    return dict(id=row.id,kind=row.kind,name=row.name,description=row.description,revision=row.revision,duration=version.duration,sections=version.sections)


def clean_rule(rule):
    if not isinstance(rule,dict):
        raise ValueError('Choose recurrence')
    frequency = rule.get('frequency','once')
    if frequency not in ('once','daily','weekly','monthly','dates'):
        raise ValueError('Choose a supported repeat rule')
    anchor = date.fromisoformat(rule.get('anchor',''))
    until = date.fromisoformat(rule['until']) if rule.get('until') else None
    if until and until<anchor:
        raise ValueError('End date is before start date')
    result = dict(frequency=frequency,anchor=anchor.isoformat(),until=until.isoformat() if until else None,
                  interval=integer(rule.get('interval',1),1,365,'Repeat interval'))
    if rule.get('starts_on'):
        starts_on=date.fromisoformat(rule['starts_on'])
        if starts_on<anchor or until and starts_on>until:
            raise ValueError('The series start must be between its anchor and end date')
        result['starts_on']=starts_on.isoformat()
    result['weekdays'] = sorted({integer(i,0,6,'Weekday') for i in rule.get('weekdays',[anchor.weekday()])})
    if frequency=='weekly' and not result['weekdays']:
        raise ValueError('Choose repeat days')
    result['month_day'] = integer(rule.get('month_day',anchor.day),1,31,'Day of month')
    result['nth'] = integer(rule.get('nth',0),-1,5,'Week of month')
    result['weekday'] = integer(rule.get('weekday',anchor.weekday()),0,6,'Weekday')
    for key in ('dates','exceptions'):
        values=rule.get(key,[])
        if not isinstance(values,list) or len(values)>1000:
            raise ValueError('Too many dates')
        result[key]=sorted({date.fromisoformat(v).isoformat() for v in values})
    return result


def matches(rule, day):
    anchor = date.fromisoformat(rule['anchor'])
    if day<anchor or rule.get('starts_on') and day<date.fromisoformat(rule['starts_on']) or rule.get('until') and day>date.fromisoformat(rule['until']) or day.isoformat() in rule.get('exceptions',[]):
        return False
    frequency, interval = rule['frequency'],rule.get('interval',1)
    if frequency=='once': return day==anchor
    if frequency=='dates': return day.isoformat() in rule.get('dates',[])
    if frequency=='daily': return (day-anchor).days%interval==0
    if frequency=='weekly':
        return ((day-timedelta(days=day.weekday()))-(anchor-timedelta(days=anchor.weekday()))).days//7%interval==0 and day.weekday() in rule['weekdays']
    months=(day.year-anchor.year)*12+day.month-anchor.month
    if months%interval: return False
    if rule.get('nth'):
        nth=rule['nth']
        return day.weekday()==rule['weekday'] and (day.day+7>month_calendar.monthrange(day.year,day.month)[1] if nth==-1 else (day.day-1)//7+1==nth)
    return day.day==rule['month_day']


def rule_dates(rule, start, count=14):
    result=[]
    for offset in range(366*5):
        day=start+timedelta(days=offset)
        if matches(rule,day):result.append(day.isoformat())
        if len(result)>=count:break
    return result


def clean_document(station, data, assignments=False):
    if not isinstance(data,list) or len(data)>1000:
        raise ValueError('Use at most 1,000 schedule definitions')
    result=[]; ids=set()
    for item in data:
        if not isinstance(item,dict):raise ValueError('Each schedule definition must be an object')
        identity=str(item.get('id') or uuid.uuid4())
        if len(identity)>36 or identity in ids:raise ValueError('Duplicate schedule identity')
        ids.add(identity)
        rule=clean_rule(item.get('rule',{}))
        value=dict(id=identity,rule=rule)
        if assignments:
            refs=item.get('pattern') or [item.get('source')]
            if len(refs)>100:raise ValueError('Use at most 100 Blocks in a pattern')
            value['pattern']=[source(station,r,allow_block=True) for r in refs]
            if any(r['kind']!='block' for r in value['pattern']):raise ValueError('Assign saved 24-hour Blocks')
        else:
            value.update(start=integer(item.get('start'),0,86399,'Start'),end=integer(item.get('end'),1,172799,'End'))
            if not 0<value['end']-value['start']<=86400:raise ValueError('Intervals must be between one second and 24 hours')
            ref=item.get('source')
            value['source']=source(station,ref,allow_block=True,allow_legacy=isinstance(ref,dict) and ref.get('kind')=='legacy')
        result.append(value)
    from app.services.schedule_conflicts import validate_overlaps
    validate_overlaps(result, matches, assignments)

    return result


def day_entries(document, day, assignments=False):
    result=[]
    for row in document:
        for origin in ([day] if assignments else [day-timedelta(days=1),day]):
            if not matches(row['rule'],origin):continue
            delta=(origin-day).days*86400
            start=row.get('start',0)+delta;end=row.get('end',86400)+delta
            if end<=0 or start>=86400:continue
            value=dict(row,start=max(0,start),end=min(86400,end),origin=origin.isoformat(),offset=-delta)
            if assignments:
                pattern=row['pattern'];value['source']=pattern[(day-date.fromisoformat(row['rule']['anchor'])).days%len(pattern)]
            result.append(value)
    return sorted(result,key=lambda r:(r['start'],r['id']))


def occurrence_key(value):
    return 'visual:'+hashlib.sha256(value.encode()).hexdigest()


def fallback(station):
    row=policy(station)
    return dict(kind='playlist',id=row.default_playlist_id,name=row.default_playlist.name) if row and row.default_playlist_id else None


def wall_boundary(now, local, seconds):
    """Wake at the next wall boundary or UTC offset change, whichever is first."""
    target=local.replace(tzinfo=None)+timedelta(seconds=max(1,seconds))
    candidates=[]
    for fold in (0,1):
        candidate=target.replace(tzinfo=local.tzinfo,fold=fold).astimezone(timezone.utc)
        if candidate>now:candidates.append(candidate)
    end=min(candidates) if candidates else now+timedelta(seconds=1)
    # A DST jump can cross a section before its nominal wall endpoint.
    point=now
    while point<end:
        following=min(end,point+timedelta(hours=1))
        if following.astimezone(local.tzinfo).utcoffset()!=point.astimezone(local.tzinfo).utcoffset():
            low=int(point.timestamp());high=int(following.timestamp())
            while high-low>1:
                middle=(low+high)//2
                if datetime.fromtimestamp(middle,timezone.utc).astimezone(local.tzinfo).utcoffset()==point.astimezone(local.tzinfo).utcoffset():low=middle
                else:high=middle
            return datetime.fromtimestamp(high,timezone.utc)
        point=following
    return end


def resolve_visual(station, at=None, *, mode=None, simple=None, activation=None, calendar=None):
    now=utc_instant(at); local=now.astimezone(ZoneInfo(station.timezone)); row=policy(station)
    if not row or not row.activated and mode is None:return None
    preview_mode=mode
    mode=mode or row.mode;activation=activation or row.activation
    second=local.hour*3600+local.minute*60+local.second
    ref=None;elapsed=0;boundary=86400-second;key=f'{activation}:{mode}';reason=None;occurrence_day=local.date().isoformat()
    if mode=='SIMPLE':
        ref=simple if simple is not None else row.simple if preview_mode else row.live_simple
        start=ScheduleTransition.query.filter_by(id=activation).first()
        origin=(start.completed_at or start.created_at) if start else now
        origin=origin.replace(tzinfo=origin.tzinfo or timezone.utc)
        elapsed=max(0,int((now-origin).total_seconds()));boundary=86400
    else:
        document=(calendar if calendar is not None else row.calendar) if mode=='CALENDAR' else row.assignments
        entries=day_entries(document,local.date(),assignments=mode=='BLOCKS')
        candidates=[r for r in entries if r['start']<=second<r['end']]
        special=[r for r in candidates if r['rule']['frequency'] in ('once','dates')]
        candidates=special or candidates
        if len(candidates)>1:
            reason='Conflicting schedules'
        elif candidates:
            chosen=candidates[0];occurrence_day=chosen['origin'];ref=chosen['source'];elapsed=second+chosen['offset']-next(r.get('start',0) for r in document if r['id']==chosen['id'])
            key+=f":{chosen['id']}:{chosen['origin']}";boundary=chosen['end']-second
        future=[r['start']-second for r in entries if r['start']>second]
        if future:boundary=min(boundary,min(future))
    def effective_ref(value):
        if mode=='SIMPLE' or not value or value['kind'] not in ('show','block'):return value
        updates=[u for u in row.revision_updates if u['id']==value['id'] and u['effective_on']<=occurrence_day]
        return dict(value,version=max(updates,key=lambda u:u['effective_on'])['version']) if updates else value
    ref=effective_ref(ref)
    label=ref.get('name') if ref else None
    if ref and ref['kind'] in ('show','block'):
        comp=ScheduleComposition.query.filter_by(id=ref['id'],station_id=station.id).first()
        version=ScheduleCompositionRevision.query.filter_by(composition_id=ref['id'],version=ref['version']).first() if comp else None
        if version:
            cycle,position=divmod(elapsed,version.duration);key+=f":v{version.id}:c{cycle}"
            section=next((s for s in version.sections if s['start']<=position<s['end']),None)
            boundary=min(boundary,version.duration-position)
            if section:
                key+=':'+section['id'];ref=section['source'];boundary=min(boundary,section['end']-position)
                inserts=sorted([i for i in section.get('inserts',[]) if i['at']<=position],key=lambda i:i['at'])
                for insert in inserts:
                    insert_key=key+':i'+insert['id']
                    if not SelectionDecision.query.filter_by(station_id=station.id,schedule_occurrence=occurrence_key(insert_key)).filter(SelectionDecision.status.in_(('selected','submitting','queued','started'))).first():
                        ref=insert['source'];key=insert_key;break
                upcoming=[i['at']-position for i in section.get('inserts',[]) if i['at']>position]
                if upcoming:boundary=min(boundary,min(upcoming))
            else:
                ref=None;reason='Empty composition interval'
                future=[s['start']-position for s in version.sections if s['start']>position]
                if future:boundary=min(boundary,min(future))
            # Blocks may contain Shows: recurse through a second bounded composition.
            ref=effective_ref(ref)
            if ref and ref['kind']=='show':
                nested=ScheduleCompositionRevision.query.filter_by(composition_id=ref['id'],version=ref['version']).first()
                if nested:
                    cycle,position=divmod(position-section['start'],nested.duration)
                    part=next((s for s in nested.sections if s['start']<=position<s['end']),None)
                    key+=f':v{nested.id}:c{cycle}'
                    boundary=min(boundary,nested.duration-position)
                    ref=part['source'] if part else None
                    if part:
                        key+=':'+part['id'];boundary=min(boundary,part['end']-position)
                        for insert in sorted(part.get('inserts',[]),key=lambda i:i['at']):
                            if insert['at']>position:
                                boundary=min(boundary,insert['at']-position);continue
                            candidate=key+':i'+insert['id']
                            if not SelectionDecision.query.filter_by(station_id=station.id,schedule_occurrence=occurrence_key(candidate)).filter(SelectionDecision.status.in_(('selected','submitting','queued','started'))).first():
                                ref=insert['source'];key=candidate;break
                    else:
                        future=[s['start']-position for s in nested.sections if s['start']>position]
                        if future:boundary=min(boundary,min(future))
                else:ref=None
        else:ref=None;reason='Composition unavailable'
    if not ref:ref=fallback(station);reason=reason or 'Nothing scheduled'
    if ref is None:key+=':empty'
    elif reason:key+=':fallback'
    next_transition=now+timedelta(seconds=max(1,boundary)) if mode=='SIMPLE' else wall_boundary(now,local,boundary)
    return dict(mode=mode,source=ref,label=label or (ref.get('name') if ref else 'No playable content'),key=occurrence_key(key),insert=':i' in key,reason=reason,next_transition=next_transition,local_time=local)


def source_tracks(station, ref, storage=None):
    if not ref:return []
    kind=ref['kind'];identifier=ref['id']
    q=tracks_for(station.id).filter_by(enabled=True,ingest_status='accepted',decommissioned_at=None)
    if kind=='legacy':
        clock=Clock.query.filter_by(id=identifier,station_id=station.id,enabled=True).first()
        if not clock:return []
        found=[]
        for slot in clock.slots:
            if not slot.enabled:continue
            if slot.slot_type=='CATEGORY':found+=source_tracks(station,dict(kind='category',id=slot.category_id),storage)
            elif slot.slot_type=='PLAYLIST':found+=source_tracks(station,dict(kind='playlist',id=slot.playlist_id),storage)
            elif slot.slot_type=='ROTATION' and slot.rotation:
                for part in slot.rotation.slots:
                    if part.enabled:found+=source_tracks(station,dict(kind='category',id=part.category_id),storage)
        return found
    if kind in ('artist','album','category'):q=q.filter_by(audio_kind='MUSIC')
    if kind=='song':q=q.filter(Track.id==identifier)
    elif kind=='artist':q=q.filter(Track.artist_id.in_(ref.get('artists',[identifier])))
    elif kind=='album':q=q.filter(Track.album_id==identifier)
    elif kind=='category':
        category=MediaCategory.query.filter_by(id=identifier,station_id=station.id,enabled=True).first()
        if not category:return []
        q=q.filter(Track.categories.any(MediaCategory.id==identifier))
    elif kind=='playlist':
        playlist=Playlist.query.filter_by(id=identifier,station_id=station.id,deleted_at=None).first()
        if not playlist:return []
        q=q.join(PlaylistItem,PlaylistItem.track_id==Track.id).filter(PlaylistItem.playlist_id==identifier).order_by(PlaylistItem.position)
    else:return []
    if kind!='playlist':q=q.order_by(Track.disc_number.asc().nullslast(),Track.track_number.asc().nullslast(),Track.id)
    tracks=q.all()
    if storage:
        from app.services.automation import _exists
        tracks=[t for t in tracks if _exists(storage,t.station.slug,t.storage_key)]
    return tracks


def select_visual(station, resolved, storage, now):
    ref=resolved['source'];tracks=source_tracks(station,ref,storage)
    if not tracks:
        ref=fallback(station);tracks=source_tracks(station,ref,storage)
        resolved=dict(resolved,key=resolved['key']+':fallback',reason='Source unavailable')
    if not tracks:return None
    key=hashlib.sha256((resolved['key']+json.dumps(ref,sort_keys=True)).encode()).hexdigest()
    cursor=ScheduleCursor.query.filter_by(station_id=station.id,key=key).with_for_update().first()
    if not cursor:
        cursor=ScheduleCursor(station_id=station.id,key=key,state={});db.session.add(cursor)
    saved=dict(cursor.state or {});ids=[t.id for t in tracks]
    ordered=ref.get('order')=='straight' or ref['kind'] in ('song','album') and ref.get('order')!='shuffle'
    if ref['kind']=='playlist' and ref.get('order','default')=='default':ordered=db.session.get(Playlist,ref['id']).mode!='RANDOM'
    if ordered:
        index=(ids.index(saved['last'])+1)%len(ids) if saved.get('last') in ids else 0
        chosen=tracks[index];cursor.state={'last':chosen.id}
    else:
        seen=set(saved.get('played',[]));remaining=[t for t in tracks if t.id not in seen]
        if not remaining:remaining=tracks;seen=set()
        chosen=random.choice(remaining);cursor.state={'played':list(seen|{chosen.id})}
    decision=SelectionDecision(station_id=station.id,track_id=chosen.id,status='selected',selected_at=now,
        selection_method='schedule_insert' if resolved.get('insert') else 'visual_schedule',schedule_occurrence=resolved['key'][:120],reason='default_playlist' if resolved.get('reason') else None,
        candidate_count=len(tracks),relaxation='intentional_loop')
    decision.cursor_checkpoint={'visual':{key:saved}}
    db.session.add(decision)
    return decision


def transition_preview(station, mode, *, simple=None, calendar=None, activation='preview'):
    """Explain the effective source, including why a saved mode cannot play now."""
    resolved = resolve_visual(station, mode=mode, simple=simple, calendar=calendar, activation=activation)
    if resolved is None:
        raise ValueError('Save the mode configuration first')
    ref, reason = resolved['source'], resolved.get('reason')
    code = None
    if reason == 'Nothing scheduled':
        code = 'unassigned' if mode == 'BLOCKS' else 'unscheduled'
        explanation = ('No Block is assigned to today. Save a Block and assign days before using Blocks.'
                       if mode == 'BLOCKS' else 'Nothing is scheduled for this time.')
    elif reason == 'Empty composition interval':
        code, explanation = 'gap', 'The scheduled content has an empty section at this time.'
    elif reason:
        code, explanation = 'unavailable', reason + '.'
    else:
        explanation = ''
    if not source_tracks(station, ref):
        if not reason:
            code, explanation = 'unplayable', 'The selected content has no playable songs at this time.'
        ref = fallback(station)
        reason = reason or 'No playable content in the selected mode'
    playable_now = bool(source_tracks(station, ref))
    using_default = bool(playable_now and reason)
    if playable_now and not ref.get('name'):
        # Older saved selections may contain only their type and identifier.
        ref = source(station, ref, allow_legacy=True)
    if using_default:
        explanation += f' Will play now: {ref["name"]} (default playlist).'
    elif not playable_now:
        explanation += ' No playable default playlist is configured in Station settings.'
    else:
        explanation = f'Will play now: {ref["name"]}.'
    return dict(source=ref, reason=reason, playable=playable_now, code=code,
                message=explanation.strip(), using_default=using_default,
                program=resolved['label'], local_time=resolved['local_time'].isoformat())


def transition_request(station,data):
    identity=str(uuid.UUID(data.get('id','')))
    prior=db.session.get(ScheduleTransition,identity)
    if prior:
        if prior.station_id!=station.id:raise ValueError('Transition unavailable')
        return prior
    row=ChannelSchedule.query.filter_by(station_id=station.id).with_for_update().first()
    if not row:row=policy(station,True)
    if data.get('revision')!=row.revision or data.get('current')!=row.mode:
        raise ValueError('The channel changed. Review the mode change again.')
    if ScheduleTransition.query.filter_by(station_id=station.id).filter(ScheduleTransition.state.in_(('PENDING','PREPARING','FADING'))).first():
        raise ValueError('A mode change is already in progress')
    mode=data.get('mode')
    if mode not in MODES:raise ValueError('Choose Calendar, Blocks, or Simple')
    simple=source(station,data['simple'],allow_block=True) if data.get('simple') else row.simple
    if row.activated and mode==row.mode and (mode!='SIMPLE' or simple==row.live_simple) and not station.automation.hold:
        raise ValueError('This mode and selection are already active')
    preview=transition_preview(station,mode,simple=simple,activation=identity)
    if not preview['playable']:
        raise ValueError(preview['message'])
    command=ScheduleTransition(id=identity,station_id=station.id,mode=mode,previous_mode=row.mode,simple=simple,revision=row.revision)
    db.session.add(command)
    return command
