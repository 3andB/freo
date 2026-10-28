"""Station-scoped catalog, artwork, and live media editor endpoints."""
from freo_ops.hosting_storage import run_media, reserve

from app.services.availability import artists_for, albums_for
from app.services.availability import tracks_for
import io
import json
import subprocess
import tempfile
import uuid
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, url_for
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Artist, Album, MusicTag, MediaCategory, MusicArtwork, Track
from app.routes.web import station_or_404
from app.services.admin_auth import admin_required, media_mutation_required, current_admin
from app.services.admin_media import audit
from app.services.catalog_edit import owned, apply_metadata
from app.services.music_catalog import artist_for, album_for

catalog_editor = Blueprint('catalog_editor', __name__)


def context_slug(song):
    return (request.view_args or {}).get('slug') or song.station.slug


def cover_url(song):
    identifier = song.catalog_album.cover_id if song.catalog_album and song.catalog_album.cover_id else song.cover_id
    if identifier: return url_for('catalog_editor.artwork', slug=context_slug(song), identifier=identifier)
    if song.catalog_album and song.catalog_album.artwork_key:
        return url_for('admin_media.album_artwork', slug=context_slug(song), album_id=song.album_id)
    if song.artwork_key:
        return url_for('catalog_editor.song_artwork',slug=context_slug(song),identifier=song.uuid)
    return None


def availability_data(song, station=None):
    inherited = bool(song.audio_kind == 'MUSIC' and ((song.catalog_artist and song.catalog_artist.available_to_all) or
                     (song.catalog_album and song.catalog_album.available_to_all)))
    return dict(direct=song.available_to_all and song.audio_kind == 'MUSIC', inherited=inherited,
                owner=song.station.name, editable=(song.station_id == station.id if station else song.station.slug == context_slug(song)) and song.audio_kind == 'MUSIC', effective=(song.audio_kind == 'MUSIC' and song.available_to_all) or inherited,
                url=url_for('admin_media.sharing', slug=context_slug(song), kind='song', identifier=song.id))


def state(song, *, include_waveform=True, station=None):
    from app.services.track_audio import state as audio_state
    station = station or station_or_404(context_slug(song), require_enabled=False)
    eligible = song.enabled and not song.decommissioned_at and any(c.enabled for c in song.categories)
    return dict(discovery_links=song.discovery_links,source_editable=song.station_id==station.id,audio=audio_state(song, station), availability=availability_data(song, station), uuid=song.uuid, audio_kind=song.audio_kind, audio_subtype=song.audio_subtype, cart_code=song.cart_code, isrc=song.isrc, title=song.title, artist=song.artist, album=song.album, track_number=song.track_number, disc_number=song.disc_number, release_year=song.release_year, artist_id=song.artist_id, album_id=song.album_id, album_artist_id=song.catalog_album.artist_id if song.catalog_album else None, album_artist=song.album_artist,
                enabled=song.enabled, analysis=song.analysis_status, error=song.analysis_error,
                processing_requested=song.analysis_requested, **({'waveform':song.waveform} if include_waveform else {}), cover=cover_url(song),
                tags=[t.id for t in song.tags if t.station_id == station.id], categories=[c.id for c in song.categories if c.station_id == station.id],
                playlists=[p.id for p in song.playlists if p.station_id == song.station_id and not p.deleted_at and p.system_key not in ('STATION', 'COMMERCIALS')],
                broadcast=('Decommissioned' if song.decommissioned_at else
                           'Enabled for broadcast' if eligible else 'Enabled — choose an active category for rotation' if song.enabled else
                           'Processing before broadcast' if song.auto_enable_pending else 'Disabled'),
                audition=url_for('admin_media.audition',slug=context_slug(song),track_uuid=song.uuid))


@catalog_editor.get('/admin/api/stations/<slug>/catalog')
@admin_required
def catalog(slug):
    station = station_or_404(slug, require_enabled=False)
    from app.services.playlists import summaries
    return jsonify(artists=[dict(id=a.id,name=a.name,available_to_all=a.available_to_all) for a in artists_for(station.id).order_by(Artist.name)],
                   albums=[dict(id=a.id,name=a.title,artist_id=a.artist_id,cover_id=a.cover_id,available_to_all=a.available_to_all or a.artist.available_to_all) for a in albums_for(station.id).order_by(Album.title)],
                   playlists=[dict(id=p['id'],name=p['name']) for p in summaries(station.id) if p['system_key'] not in ('STATION','COMMERCIALS')],
                   tags=[dict(id=t.id,name=t.name) for t in MusicTag.query.filter_by(station_id=station.id).order_by(MusicTag.name)],
                   categories=[dict(id=c.id,name=c.name,enabled=c.enabled) for c in MediaCategory.query.filter_by(station_id=station.id).order_by(MediaCategory.name)])


@catalog_editor.post('/admin/api/stations/<slug>/catalog/<kind>')
@media_mutation_required
def create(slug, kind):
    station = station_or_404(slug, require_enabled=False)
    try:
        name = request.form.get('name','').strip()
        if not name or len(name)>200: raise ValueError('Enter a name up to 200 characters')
        if kind=='artists': row=artist_for(station.id,name)
        elif kind=='albums':
            artist=owned(Artist,station.id,request.form.get('artist_id'))
            row=album_for(station.id,artist,name,year=None)
        else: return jsonify(message='Unknown catalog type'),404
        audit('catalog_created',user_id=current_admin().id,station_id=station.id,target_type=kind,target_id=str(row.id),summary=name)
        db.session.commit();return jsonify(id=row.id,name=row.name if kind=='artists' else row.title, **({'artist_id':row.artist_id,'cover_id':row.cover_id} if kind=='albums' else {}))
    except (ValueError,IntegrityError) as error:
        db.session.rollback();return jsonify(message=str(error) if isinstance(error,ValueError) else 'That entry already exists. Select it from the list.'),409


@catalog_editor.route('/admin/api/stations/<slug>/song/<identifier>',methods=['GET','POST'])
@admin_required
def song(slug,identifier):
    station=station_or_404(slug,require_enabled=False)
    track=tracks_for(station.id).filter_by(uuid=identifier,deleted_at=None).first_or_404()
    if request.method=='POST':
        if track.station_id != station.id:
            return jsonify(message='Edit shared source details in the owning station.'), 403
        from app.services.admin_auth import require_csrf
        require_csrf()
        if track.decommissioned_at: return jsonify(message='This song is decommissioned'),409
        try:
            data=json.loads(request.form.get('data','{}'))
            if not isinstance(data,dict): raise ValueError('Invalid song details')
            if 'enabled' in data:
                if not isinstance(data['enabled'],bool): raise ValueError('Choose enabled or disabled')
                if data['enabled'] and (track.ingest_status!='accepted' or track.analysis_status!='complete'):
                    raise ValueError('Complete audio processing before enabling broadcast')
                from app.services.media import set_enabled_db
                set_enabled_db(track,data['enabled'])
            else:
                if not str(data.get('title','')).strip(): raise ValueError('Song title is required')
                apply_metadata(track,data,station.id)
            audit('media_editor_updated',user_id=current_admin().id,station_id=station.id,target_id=track.uuid,summary='Song details or broadcast state updated')
            db.session.commit()
        except (ValueError,TypeError,IntegrityError) as error:
            db.session.rollback();return jsonify(message=str(error) if not isinstance(error,IntegrityError) else 'Catalog changed. Please try again.'),409
    response=jsonify(state(track));response.headers['Cache-Control']='private, no-store';return response


@catalog_editor.post('/admin/api/stations/<slug>/song/<identifier>/audio')
@media_mutation_required
def save_audio(slug, identifier):
    from sqlalchemy import update
    from app.services.track_audio import validate
    station = station_or_404(slug, require_enabled=False)
    track = tracks_for(station.id).filter_by(uuid=identifier, deleted_at=None).first_or_404()
    if track.station_id != station.id:
        from flask import abort
        abort(403)
    if track.decommissioned_at:
        return jsonify(message='This song is decommissioned'), 409
    try:
        data = json.loads(request.form.get('data', '{}'))
        if not isinstance(data, dict) or type(data.get('revision')) is not int or not 0 <= data['revision'] < 2147483647:
            raise ValueError('An audio revision is required')
        values = validate(data, track.duration_ms)
        changed = db.session.execute(update(Track).where(
            Track.id == track.id, Track.audio_edit_revision == data['revision'],
            Track.deleted_at.is_(None), Track.decommissioned_at.is_(None)
        ).values(**values, audio_edit_enabled=True, audio_edit_revision=data['revision'] + 1))
        if not changed.rowcount:
            db.session.rollback()
            return jsonify(message='Audio settings changed. Reload the saved settings before saving again.'), 409
        audit('track_audio_updated', user_id=current_admin().id, station_id=station.id,
              target_id=track.uuid, summary='Cue points, fades and gain trim saved')
        db.session.commit()
        db.session.refresh(track)
        return jsonify(state(track))
    except ValueError as error:
        db.session.rollback()
        return jsonify(message=str(error)), 400


@catalog_editor.post('/admin/api/stations/<slug>/artwork')
@media_mutation_required
def upload_artwork(slug):
    station=station_or_404(slug,require_enabled=False)
    try:
        file=request.files.get('file')
        if not file: raise ValueError('Choose a JPEG or PNG image')
        payload=file.read(20*1024*1024+1)
        if len(payload)>20*1024*1024: raise ValueError('Artwork must be under 20 MB')
        if not (payload.startswith(b'\x89PNG\r\n\x1a\n') or payload.startswith(b'\xff\xd8')):
            raise ValueError('Choose a JPEG or PNG image')
        with reserve(80*1024*1024), tempfile.TemporaryDirectory(prefix='freo-art-') as directory:
            source=Path(directory)/'source';source.write_bytes(payload)
            info=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(source)],capture_output=True,timeout=10,check=True)
            size=json.loads(info.stdout)['streams'][0]
            if not 1<=size['width']<=10000 or not 1<=size['height']<=10000: raise ValueError('Artwork must be no larger than 10000 pixels on either side')
            output=Path(directory)/'cover.jpg'
            run_media(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(source),'-frames:v','1','-vf',"crop=min(iw\\,ih):min(iw\\,ih),scale=min(3000\\,iw):-1",'-q:v','2',str(output)],max_output_bytes=32*1024*1024,capture_output=True,timeout=20,check=True)
            art=MusicArtwork(id=str(uuid.uuid4()),station_id=station.id,image=output.read_bytes());db.session.add(art)
        if request.form.get('album_id'):
            album = owned(Album, station.id, request.form['album_id'])
            from app.services.polish import require_owner
            require_owner(album, station.id)
            album.cover_id = art.id
        if request.form.get('song_id'):
            track=tracks_for(station.id).filter_by(uuid=request.form['song_id'],deleted_at=None,decommissioned_at=None).first()
            if not track: raise ValueError('Song unavailable')
            from app.services.polish import require_owner
            require_owner(track, station.id)
            if track.catalog_album: require_owner(track.catalog_album, station.id)
            if track.catalog_album: track.catalog_album.cover_id=art.id
            else: track.cover_id=art.id
        audit('music_artwork_uploaded',user_id=current_admin().id,station_id=station.id,target_type='artwork',target_id=art.id,summary='Cover artwork saved')
        db.session.commit();return jsonify(id=art.id,url=url_for('.artwork',slug=slug,identifier=art.id))
    except (ValueError,KeyError,IndexError,OSError,subprocess.SubprocessError):
        db.session.rollback();return jsonify(message='Could not save artwork. Use a JPEG or PNG under 20 MB and 10000 pixels.'),400


@catalog_editor.get('/admin/stations/<slug>/artwork/<identifier>')
@admin_required
def artwork(slug,identifier):
    station=station_or_404(slug,require_enabled=False)
    from sqlalchemy import or_
    allowed_covers = tracks_for(station.id).with_entities(Track.cover_id)
    album_covers = albums_for(station.id).with_entities(Album.cover_id)
    art=MusicArtwork.query.filter(MusicArtwork.id==identifier, or_(
        MusicArtwork.station_id==station.id, MusicArtwork.id.in_(allowed_covers),
        MusicArtwork.id.in_(album_covers))).first_or_404()
    return send_file(io.BytesIO(art.image),mimetype='image/jpeg',max_age=3600)


@catalog_editor.get('/admin/stations/<slug>/song-artwork/<identifier>')
@admin_required
def song_artwork(slug,identifier):
    from flask import abort
    from app.services.media_storage import LocalMediaStorage
    station=station_or_404(slug,require_enabled=False)
    track=tracks_for(station.id).filter_by(uuid=identifier,deleted_at=None).first_or_404()
    if not track.artwork_key: abort(404)
    try: path=LocalMediaStorage().artwork_file(track.station.slug,track.artwork_key)
    except (OSError,ValueError): abort(404)
    return send_file(path,mimetype='image/jpeg',conditional=True,max_age=3600)
