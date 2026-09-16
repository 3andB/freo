"""Station-scoped listening and music organization workspace."""
from app.services.availability import tracks_for, track_scope
import math
import re
import uuid
from datetime import datetime, timezone, timedelta
from flask import Blueprint, abort, jsonify, request, url_for, redirect
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from app.extensions import db
from app.models import Station, Track, MusicTag, MediaCategory, MusicEdit, song_tags, track_categories
from app.routes.web import station_or_404
from app.services.admin_auth import admin_required, current_admin, require_csrf, can_manage_programming
from app.services.admin_media import audit
from app.services.analysis_queue import request_analysis
from app.services.loudness import gain_for
from app.routes.catalog_editor import cover_url, context_slug
from app.services.airplay import play_counts
from app.models import SongFlag
from app.routes.song_flags import flag_data

from app.services import playlists as playlist_service
from app.models import Playlist, PlaylistItem

sound_room=Blueprint('sound_room',__name__)


def song_data(song, plays=None, station=None, flags=None, ratings=None):
    station = station or song.station
    from app.services.player import vote_stats, EMPTY_STATS
    rating=(ratings if ratings is not None else vote_stats(station.id,[song.id])).get(song.id,EMPTY_STATS)
    return dict(uuid=song.uuid,title=song.title,artist=song.artist,album=song.album,
        votes=rating, feedback_url=url_for('player_experience.inbox',slug=station.slug,track=song.uuid),
        flag=flag_data(flags.get(song.id) if flags is not None else SongFlag.query.filter_by(station_id=station.id,track_id=song.id).first()),
        play_count=play_counts(station.id, 'track', [song.id]).get(song.id, 0) if plays is None else plays,
        duration_ms=song.duration_ms,enabled=song.enabled,notes=song.notes,
        analysis=song.analysis_status,requested=song.analysis_requested,error=song.analysis_error,
        bpm=song.bpm,lufs=song.loudness_lufs,peak=song.true_peak_db,gain=gain_for(song, station),
        playlists=[x.id for x in song.playlists if x.station_id == station.id and x.enabled],
        categories=[x.id for x in song.categories],tags=[x.id for x in song.tags],
        audition=url_for('admin_media.audition',slug=context_slug(song),track_uuid=song.uuid),
        detail=url_for('admin_media.track_detail',slug=context_slug(song),track_uuid=song.uuid),
        artwork=cover_url(song))


@sound_room.get('/admin/stations/<slug>/sound-room')
@admin_required
def page(slug):
    station=station_or_404(request.args.get('station',slug),require_enabled=False)
    return redirect(url_for('playlists.page', slug=station.slug))


@sound_room.get('/admin/api/stations/<slug>/music')
@admin_required
def catalog(slug):
    station=station_or_404(slug,require_enabled=False)
    base=tracks_for(station.id).filter_by(decommissioned_at=None,ingest_status='accepted')
    query=base
    flag_filter=request.args.get('flags','')
    if flag_filter:
        if flag_filter not in ('open','resolved'):abort(400)
        flagged=db.session.query(SongFlag.track_id).filter(SongFlag.station_id==station.id)
        flagged=flagged.filter(SongFlag.resolved_at.is_(None) if flag_filter=='open' else SongFlag.resolved_at.isnot(None))
        query=query.filter(Track.id.in_(flagged))
    term=request.args.get('q','').strip()[:100]
    if term:
        pattern='%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.filter(or_(Track.title.ilike(pattern,escape='\\'),Track.artist.ilike(pattern,escape='\\'),Track.album.ilike(pattern,escape='\\')))
    for key,model,relation in [('category',MediaCategory,Track.categories),('tag',MusicTag,Track.tags)]:
        value=request.args.get(key,'')
        if value:
            if not value.isdecimal():abort(400)
            target=model.query.filter_by(id=int(value),station_id=station.id).first_or_404()
            query=query.filter(relation.any(model.id==target.id))
    if request.args.get('playlist'):
        if not request.args['playlist'].isdecimal():abort(400)
        row=Playlist.query.filter_by(id=int(request.args['playlist']),station_id=station.id,deleted_at=None).first_or_404()
        query=query.filter(Track.id.in_(db.session.query(PlaylistItem.track_id).filter_by(playlist_id=row.id)))
    analysis=request.args.get('analysis','')
    if analysis=='unfinished':query=query.filter(Track.analysis_status!='complete')
    elif analysis in ('pending','processing','complete','failed'):query=query.filter_by(analysis_status=analysis)
    elif analysis:abort(400)
    if request.args.get('uncategorized')=='1':query=query.filter(~Track.categories.any(MediaCategory.station_id==station.id))
    enabled=request.args.get('enabled','')
    if enabled in ('yes','no'):query=query.filter_by(enabled=enabled=='yes')
    elif enabled:abort(400)
    try: page=max(1,min(int(request.args.get('page',1)),100000))
    except ValueError:abort(400)
    total=query.count()
    songs=query.options(selectinload(Track.playlists),selectinload(Track.tags),selectinload(Track.categories),selectinload(Track.station),selectinload(Track.catalog_album)).order_by(Track.artist,Track.title,Track.id).offset((page-1)*50).limit(50).all()
    category_counts=dict(db.session.query(track_categories.c.category_id,func.count()).join(Track,Track.id==track_categories.c.track_id).filter(track_scope(station.id),Track.decommissioned_at.is_(None)).group_by(track_categories.c.category_id).all())
    tag_counts=dict(db.session.query(song_tags.c.tag_id,func.count()).join(Track,Track.id==song_tags.c.track_id).filter(track_scope(station.id),Track.decommissioned_at.is_(None)).group_by(song_tags.c.tag_id).all())
    song_plays = play_counts(station.id, 'track', [x.id for x in songs])
    category_plays = play_counts(station.id, 'category')
    flags={flag.track_id:flag for flag in SongFlag.query.filter(SongFlag.station_id==station.id,SongFlag.track_id.in_([x.id for x in songs])).all()}
    from app.services.player import vote_stats
    ratings=vote_stats(station.id,[x.id for x in songs])
    result=dict(flagged_count=base.filter(Track.id.in_(db.session.query(SongFlag.track_id).filter_by(station_id=station.id,resolved_at=None))).count(),songs=[song_data(x, song_plays.get(x.id, 0), station, flags, ratings) for x in songs],total=total,page=page,pages=max(1,(total+49)//50),target_lufs=station.target_lufs,
        playlists=[playlist_service.summary(row) for row in playlist_service.listing(station.id)],
        categories=[dict(id=x.id,name=x.name,count=category_counts.get(x.id,0),play_count=category_plays.get(x.id,0),enabled=x.enabled,description=x.description) for x in MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name)],
        tags=[dict(id=x.id,name=x.name,color=x.color,description=x.description,count=tag_counts.get(x.id,0)) for x in MusicTag.query.filter_by(station_id=station.id).order_by(MusicTag.name)],
        unfinished=base.filter(Track.analysis_status!='complete').count())
    response=jsonify(result);response.headers['Cache-Control']='private, no-store';return response


@sound_room.get('/admin/api/stations/<slug>/music/<identifier>')
@admin_required
def song(slug,identifier):
    station=station_or_404(slug,require_enabled=False)
    track=tracks_for(station.id).filter_by(uuid=identifier,decommissioned_at=None,ingest_status='accepted').first_or_404()
    return jsonify(song_data(track, station=station))


def selected_songs(station,data):
    ids=data.get('songs',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=500 or any(not isinstance(x,str) for x in ids):raise ValueError('Select between 1 and 500 songs')
    songs=Track.query.filter(track_scope(station.id),Track.uuid.in_(ids),Track.decommissioned_at.is_(None),Track.ingest_status=='accepted').all()
    if len(songs)!=len(set(ids)):raise ValueError('One or more songs are unavailable for this station')
    return songs


def target_for(station,kind,identifier):
    model={'category':MediaCategory,'tag':MusicTag}.get(kind)
    if model is None:raise ValueError('Choose a category or tag')
    target=model.query.filter_by(station_id=station.id,id=identifier).first()
    if not target:raise ValueError('Destination is unavailable for this station')
    return target


@sound_room.post('/admin/api/stations/<slug>/music/actions/<action>')
@admin_required
def mutate(slug,action):
    station=station_or_404(slug,require_enabled=False)
    # Reuse the established form-CSRF boundary; JSON data is one form field.
    require_csrf()
    if action in ('create-tag', 'edit-tag', 'delete-tag') and not can_manage_programming(current_admin(), station):
        abort(403)
    import json
    try:
        data=json.loads(request.form.get('data','{}'))
        if not isinstance(data,dict):raise ValueError('Invalid request')
        db.session.query(Station.id).filter_by(id=station.id).with_for_update().first()
        undo=None
        if action in ('create-playlist','edit-playlist','delete-playlist','playlist-source','playlist-remove','playlist-reorder'):
            if not can_manage_programming(current_admin(),station):abort(403)
            row=Playlist(station_id=station.id) if action=='create-playlist' else playlist_service.get_playlist(station.id,data.get('id'))
            if action in ('edit-playlist','playlist-reorder') and data.get('revision')!=row.revision:
                raise ValueError('This playlist changed elsewhere. Reload it before saving')
            if action in ('create-playlist','edit-playlist'):
                name=data.get('name','');description=data.get('description','');mode=data.get('mode','STRAIGHT')
                if not isinstance(name,str) or not name.strip() or len(name)>120:raise ValueError('Use a name between 1 and 120 characters')
                if not isinstance(description,str) or len(description)>500:raise ValueError('Description must be under 500 characters')
                if mode not in ('STRAIGHT','RANDOM'):raise ValueError('Choose Straight or Random')
                row.name=name.strip();row.description=description.strip();row.mode=mode
                if action=='edit-playlist':row.revision+=1
                db.session.add(row);db.session.flush();message='Playlist saved'
            elif action=='delete-playlist':
                if data.get('confirm')!=row.id:raise ValueError('Confirm playlist deletion')
                playlist_service.delete_playlist(row);message='Playlist deleted. Songs remain in Music.'
            elif action=='playlist-reorder':
                ids=data.get('songs')
                if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):raise ValueError('Supply the complete song order')
                by_uuid={item.track.uuid:item.track_id for item in row.items}
                if len(ids)!=len(by_uuid) or set(ids)!=set(by_uuid):raise ValueError('The playlist contents changed. Reload before reordering')
                playlist_service.replace_order(row,[by_uuid[x] for x in ids]);message='Playlist order saved'
            else:
                if action=='playlist-source':
                    songs=playlist_service.source_songs(station.id,data.get('kind'),data.get('source'))
                else:
                    ids=data.get('songs',[])
                    if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):raise ValueError('Select songs to remove')
                    songs=[item.track for item in row.items if item.track.uuid in ids]
                undo,count=playlist_service.membership(row,songs,'add' if action=='playlist-source' else 'remove',current_admin().id)
                message=f'{count} song(s) updated · {row.name}'
        elif action=='assign' and data.get('kind')=='playlist':
            if not can_manage_programming(current_admin(),station):abort(403)
            row=playlist_service.get_playlist(station.id,data.get('target'))
            songs=selected_songs(station,data)
            # Preserve the order selected in Music.
            by_uuid={song.uuid:song for song in songs};songs=list(dict.fromkeys(by_uuid[x] for x in data['songs']))
            undo,count=playlist_service.membership(row,songs,data.get('operation'),current_admin().id)
            message=f'{count} song(s) updated · {row.name}'
        elif action=='assign':
            songs=selected_songs(station,data);kind=data.get('kind');target=target_for(station,kind,data.get('target'))
            if data.get('operation') not in ('add','remove'):raise ValueError('Choose add or remove')
            adding=data['operation']=='add';changes=[]
            for song in songs:
                collection=song.categories if kind=='category' else song.tags
                before=target in collection
                if before==adding:continue
                if adding:collection.append(target)
                else:collection.remove(target)
                changes.append(dict(uuid=song.uuid,before=before,after=adding))
            if changes:
                edit=MusicEdit(id=str(uuid.uuid4()),station_id=station.id,admin_user_id=current_admin().id,kind=kind,target_id=target.id,changes=changes)
                db.session.add(edit);undo=edit.id
            message=f'{len(changes)} song(s) updated · {target.name}'
        elif action=='undo':
            edit=MusicEdit.query.filter_by(id=data.get('id'),station_id=station.id,admin_user_id=current_admin().id).with_for_update().first()
            if not edit or edit.undone:raise ValueError('This change has already been undone or is unavailable')
            if datetime.now(timezone.utc)-edit.created_at.replace(tzinfo=timezone.utc)>timedelta(hours=1):raise ValueError('Undo expired; adjust the selection directly')
            if edit.kind=='playlist':
                playlist_service.undo_edit(edit);message='Playlist changes undone'
            else:
                target=target_for(station,edit.kind,edit.target_id)
                songs=selected_songs(station,{'songs':[x['uuid'] for x in edit.changes]});by_id={x.uuid:x for x in songs}
                for change in edit.changes:
                    collection=by_id[change['uuid']].categories if edit.kind=='category' else by_id[change['uuid']].tags
                    if (target in collection)!=change['after']:raise ValueError('These assignments changed again; review them before editing')
                    if change['before']:collection.append(target)
                    else:collection.remove(target)
                edit.undone=True;message='Assignment changes undone'
        elif action in ('create-tag','edit-tag','create-category'):
            name=str(data.get('name','')).strip()
            if not name or len(name)>80:raise ValueError('Use a name between 1 and 80 characters')
            key=re.sub(r'[^a-z0-9]+','-',name.casefold()).strip('-')[:64]
            if not key:raise ValueError('Include letters or numbers in the name')
            description=data.get('description','')
            if not isinstance(description,str) or len(description)>500:raise ValueError('Description must be under 500 characters')
            if action=='create-category':
                row=MediaCategory(station_id=station.id,name=name,slug=key,description=description.strip());db.session.add(row)
            else:
                color=data.get('color','#b9e79b')
                if not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',color):raise ValueError('Choose a valid tag color')
                row=target_for(station,'tag',data.get('id')) if action=='edit-tag' else MusicTag(station_id=station.id)
                row.name=name;row.slug=key;row.color=color;row.description=description.strip();db.session.add(row)
            message='Category created' if action=='create-category' else 'Tag saved'
        elif action=='delete-tag':
            tag=target_for(station,'tag',data.get('id'))
            if data.get('confirm')!=tag.id:raise ValueError('Confirm deletion of this tag')
            message=f'Tag {tag.name} deleted'
            db.session.execute(song_tags.delete().where(song_tags.c.tag_id==tag.id))
            db.session.delete(tag)
        elif action=='edit-category':
            category=target_for(station,'category',data.get('id'))
            name=str(data.get('name','')).strip();description=str(data.get('description',''))
            if not name or len(name)>120 or len(description)>500:raise ValueError('Use a name under 120 characters and description under 500')
            if not isinstance(data.get('enabled'),bool):raise ValueError('Choose enabled or disabled')
            category.name=name;category.description=description;category.enabled=data['enabled'];message='Category saved'
        elif action=='delete':
            songs=selected_songs(station,data)
            if len(songs)!=1 or data.get('confirm')!=songs[0].uuid:raise ValueError('Confirm deletion of one song')
            from app.services.music_delete import queue_delete
            job=queue_delete(songs[0],current_admin());db.session.commit()
            return jsonify(message='Permanent deletion queued. Open deletion status to confirm completion.',job_url=url_for('admin_media.job_status',slug=slug,job_id=job.id))
        elif action=='notes':
            songs=selected_songs(station,data)
            if len(songs)!=1:raise ValueError('Select one song to edit notes')
            notes=data.get('notes','')
            if not isinstance(notes,str) or len(notes)>4000:raise ValueError('Notes must be under 4,000 characters')
            if songs[0].notes!=data.get('previous',songs[0].notes):raise ValueError('Notes changed elsewhere. Reload the song before saving.')
            songs[0].notes=notes;message='Notes saved'
        elif action=='process':
            songs=selected_songs(station,data)
            count=sum(request_analysis(song) for song in songs);message=f'{count} song(s) queued for priority processing'
        elif action=='loudness':
            target=float(data.get('target'))
            if not math.isfinite(target) or not -30<=target<=-12:raise ValueError('Choose a target between −30 and −12 LUFS')
            station.target_lufs=target;message=f'Station target saved: {target:g} LUFS. Applies to newly queued songs.'
        else:abort(404)
        audit('music_'+action.replace('-','_'),user_id=current_admin().id,station_id=station.id,target_type='music',target_id=undo,summary=message)
        db.session.commit();return jsonify(message=message,undo=undo,tag_id=row.id if action in ('create-tag','edit-tag') else None,playlist_id=row.id if action=='create-playlist' else None)
    except (ValueError,TypeError,IntegrityError) as error:
        db.session.rollback()
        return jsonify(message='That name already exists. Choose an existing destination or another name.' if isinstance(error,IntegrityError) else str(error)),409
