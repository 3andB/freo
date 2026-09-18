"""Authenticated, revision-checked music preparation and import sessions."""
import io
import json
import stat
import uuid
from datetime import timedelta
from flask import Blueprint, abort, jsonify, request, send_file, url_for
from sqlalchemy.orm import joinedload, selectinload, load_only
from app.extensions import db
from app.models import MusicImportSession, MusicImportItem, MediaIngestJob, MusicArtwork, Track
from app.routes.web import station_or_404
from app.routes.catalog_editor import state
from app.services.admin_auth import admin_required, current_admin, require_csrf, csrf_token
from app.services.admin_media import audit, staged_path
from app.services.catalog_edit import validate_metadata, apply_metadata
from app.services.import_sessions import stage, utcnow, DRAFT_DAYS

music_import = Blueprint('music_import', __name__)
BASE = '/admin/api/stations/<slug>/imports'


def payload():
    try:
        data = json.loads(request.form.get('data', '{}'))
        if not isinstance(data, dict): raise ValueError()
        return data
    except (ValueError, TypeError):
        raise ValueError('Invalid import details')


def session_for(slug, identifier, lock=False):
    station = station_or_404(slug, require_enabled=False)
    query = MusicImportSession.query.filter_by(id=identifier, station_id=station.id, admin_user_id=current_admin().id)
    if lock: query = query.with_for_update()
    session = query.first_or_404()
    if request.method == 'POST' and not station.enabled:
        abort(409, 'Station is disabled')
    return session


def item_state(item, slug, duplicates=None):
    song = item.job.track if item.job and item.job.track and not item.job.track.deleted_at else None
    song_data = state(song, include_waveform=False) if song else None
    if duplicates is None:
        duplicates = duplicate_songs([item], item.session.station_id)
    duplicate = duplicates.get(item.checksum) if item.status != 'finalized' else None
    return dict(id=item.id, name=item.original_filename, path=item.relative_path, size=item.size_bytes,
        duplicate=dict(uuid=duplicate.uuid, title=duplicate.title,
            review_url=url_for('admin_media.track_detail', slug=slug, track_uuid=duplicate.uuid)) if duplicate else None,
        status=item.status, detected=item.detected, choices=item.choices, revision=item.revision,
        error=item.error, job_status=item.job.status if item.job else None,
        job_error=item.job.error_code if item.job else None, song=song_data,
        song_url=url_for('catalog_editor.song', slug=slug, identifier=song.uuid) if song else None,
        review_url=url_for('admin_media.track_detail', slug=slug, track_uuid=song.uuid) if song else None,
        album_url=url_for('admin_media.album_detail', slug=slug, album_id=song.album_id) if song and song.album_id else None,
        preview_url=url_for('.preview', slug=slug, identifier=item.session_id, item_id=item.id) if item.status=='ready' else None,
        cover_url=url_for('.artwork', slug=slug, identifier=item.session_id, item_id=item.id) if (item.detected or {}).get('has_artwork') else None)


def duplicate_songs(items, station_id):
    checksums = {i.checksum for i in items if i.status != 'finalized' and i.checksum}
    if not checksums: return {}
    return {song.checksum_sha256: song for song in Track.query.filter_by(
        station_id=station_id, deleted_at=None, ingest_status='accepted').filter(
        Track.checksum_sha256.in_(checksums)).options(
        load_only(Track.uuid, Track.title, Track.checksum_sha256)).all()}


def session_state(session, slug):
    song = joinedload(MusicImportItem.job).joinedload(MediaIngestJob.track)
    rows = MusicImportItem.query.filter_by(session_id=session.id, dismissed=False).options(
        song.defer(Track.waveform), song.selectinload(Track.tags),
        song.selectinload(Track.categories), song.joinedload(Track.catalog_album),
        song.joinedload(Track.station)).order_by(MusicImportItem.created_at, MusicImportItem.id).all()
    duplicates = duplicate_songs(rows, session.station_id)
    return dict(id=session.id, url=url_for('.session_detail', slug=slug, identifier=session.id),
        library_url=url_for('admin_media.library', slug=slug, import_session=session.id),
        items=[item_state(i, slug, duplicates) for i in rows], groups=session.groups, expires_days=DRAFT_DAYS)


def choices(station_id, data):
    result = validate_metadata(station_id, data)
    if 'keep_disabled' in data:
        if not isinstance(data['keep_disabled'], bool): raise ValueError('Choose whether to keep music disabled')
        result['keep_disabled'] = data['keep_disabled']
    if 'group' in data:
        if not isinstance(data['group'], str) or len(data['group']) > 300: raise ValueError('Invalid album group')
        result['group'] = data['group']
    if 'inherited_group' in data:
        if not isinstance(data['inherited_group'], str) or len(data['inherited_group'])>300: raise ValueError('Invalid album group')
        result['inherited_group'] = data['inherited_group']
    if 'file_fields' in data:
        fields = data['file_fields']
        if not isinstance(fields, list) or any(key not in ('artist_id', 'album_id') for key in fields):
            raise ValueError('Invalid file metadata choices')
        result['file_fields'] = list(set(fields))
    return result


@music_import.errorhandler(ValueError)
def invalid(error):
    db.session.rollback()
    return jsonify(message=str(error)), 409


@music_import.route(BASE, methods=['GET', 'POST'])
@admin_required
def sessions(slug):
    station = station_or_404(slug, require_enabled=False)
    if request.method == 'POST':
        require_csrf()
        if not station.enabled: abort(409)
        session = MusicImportSession(station_id=station.id, admin_user_id=current_admin().id)
        db.session.add(session); db.session.commit()
        return jsonify(session_state(session, slug)), 201
    rows = (MusicImportSession.query.filter_by(station_id=station.id, admin_user_id=current_admin().id)
            .options(selectinload(MusicImportSession.items).load_only(MusicImportItem.id,
                MusicImportItem.original_filename, MusicImportItem.relative_path,
                MusicImportItem.detected, MusicImportItem.dismissed, MusicImportItem.status))
            .filter(MusicImportSession.updated_at >= utcnow() - timedelta(days=DRAFT_DAYS))
            .order_by(MusicImportSession.updated_at.desc()).limit(20).all())
    def label(session):
        visible = [i for i in session.items if not i.dismissed]
        if not visible: return 'Empty import'
        first = visible[0]
        return (first.detected or {}).get('album') or first.relative_path.rpartition('/')[0] or first.original_filename
    response = jsonify(csrf=csrf_token(), sessions=[dict(id=s.id, created_at=s.created_at.isoformat(),
        name=label(s), count=sum(not i.dismissed for i in s.items),
        imported=sum(not i.dismissed and i.status=='finalized' for i in s.items)) for s in rows])
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@music_import.route(BASE + '/<identifier>', methods=['GET', 'POST'])
@admin_required
def session_detail(slug, identifier):
    if request.method == 'POST': require_csrf()
    session = session_for(slug, identifier, lock=request.method=='POST')
    if request.method == 'POST':
        data = payload()
        if data.get('action') == 'save-items':
            selected = data.get('items')
            if not isinstance(selected, list) or not 1 <= len(selected) <= 500:
                raise ValueError('Select songs to save')
            if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in selected):
                raise ValueError('Invalid song selection')
            identifiers = [row['id'] for row in selected]
            rows = {row.id: row for row in MusicImportItem.query.filter(
                MusicImportItem.session_id == session.id, MusicImportItem.id.in_(identifiers),
                MusicImportItem.dismissed.is_(False)).with_for_update().all()}
            if len(rows) != len(selected): raise ValueError('One or more songs are unavailable')
            for selection in selected:
                item = rows[selection['id']]
                if item.revision != selection.get('revision'):
                    raise ValueError('Details changed in another tab. Reload this import before saving.')
                if item.status not in ('pending', 'preparing', 'ready', 'failed'):
                    raise ValueError('This draft has expired or was imported. Reload its details.')
                item.choices = choices(session.station_id, selection.get('choices', {}))
                item.revision += 1
            session.updated_at = utcnow(); db.session.commit()
            return jsonify(session_state(session, slug))
        if data.get('action') == 'group':
            key = data.get('key')
            if not isinstance(key, str) or not key or len(key)>300: raise ValueError('Invalid album group')
            groups = dict(session.groups)
            if data.get('choices') is None: groups.pop(key, None)
            else: groups[key] = choices(session.station_id, data.get('choices', {}))
            if len(groups)>500: raise ValueError('Too many album groups')
            session.groups = groups; session.updated_at = utcnow(); db.session.commit()
            return jsonify(session_state(session, slug))
        if data.get('action') != 'finalize': raise ValueError('Choose an import action')
        selected = data.get('items')
        if not isinstance(selected, list) or not 1 <= len(selected) <= 500: raise ValueError('Select songs to import')
        seen = set()
        for choice in selected:
            if not isinstance(choice, dict): raise ValueError('Invalid song selection')
            item = MusicImportItem.query.filter_by(id=choice.get('id'), session_id=session.id).with_for_update().first()
            if not item or item.dismissed: raise ValueError('Song is unavailable')
            if item.id in seen: continue
            seen.add(item.id)
            if item.status == 'finalized': continue  # Lost-response retry is idempotent.
            if item.revision != choice.get('revision'): raise ValueError('Details changed in another tab. Reload this import before continuing.')
            if item.status != 'ready': raise ValueError('Wait for selected songs to finish preparing')
            metadata = choices(session.station_id, item.choices)
            if item.artwork and not metadata.get('cover_id'):
                art = MusicArtwork(id=str(uuid.uuid4()), station_id=session.station_id, image=item.artwork)
                db.session.add(art); db.session.flush(); metadata['cover_id'] = art.id
            job = MediaIngestJob(id=item.id, station_id=session.station_id, admin_user_id=current_admin().id,
                kind='ingest', status='pending', original_filename=item.original_filename, import_metadata=metadata)
            db.session.add(job); item.job = job; item.status = 'finalized'; item.revision += 1
        session.updated_at = utcnow()
        audit('music_import_committed', user_id=current_admin().id, station_id=session.station_id,
              target_type='import_session', target_id=session.id, summary=f'{len(seen)} songs submitted')
        db.session.commit()
    response = jsonify(session_state(session, slug))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@music_import.post(BASE + '/<identifier>/files')
@admin_required
def upload(slug, identifier):
    require_csrf()
    session = session_for(slug, identifier, lock=True)
    file = request.files.get('file')
    if not file: raise ValueError('Choose an audio file')
    item = stage(session, request.form.get('id', ''), file, request.form.get('path', ''),
                 choices=choices(session.station_id, payload()))
    return jsonify(item_state(item, slug)), 202


@music_import.post(BASE + '/<identifier>/items/<item_id>')
@admin_required
def edit_item(slug, identifier, item_id):
    require_csrf()
    session = session_for(slug, identifier, lock=True)
    item = MusicImportItem.query.filter_by(session_id=session.id, id=item_id).with_for_update().first_or_404()
    data = payload()
    if data.get('revision') != item.revision: raise ValueError('Details changed in another tab. Reload this import before saving.')
    action = data.get('action', 'save')
    if action == 'dismiss':
        if item.status != 'finalized': item.status = 'cancelled'
        item.dismissed = True
    elif action == 'retry':
        if item.status == 'finalized' and item.job and item.job.status in ('error', 'rejected'):
            if not staged_path(item.id).is_file():
                existing = Track.query.filter_by(station_id=session.station_id,
                    checksum_sha256=item.checksum, deleted_at=None, ingest_status='accepted').first()
                if not existing: raise ValueError('Source file expired. Add the file again to retry.')
            item.job.status, item.job.error_code = 'pending', None
        elif item.status == 'failed':
            item.status, item.error = 'pending', ''
        else: raise ValueError('This song cannot be retried yet')
    elif action == 'save':
        metadata = choices(session.station_id, data.get('choices', {}))
        if item.status == 'finalized':
            song = item.job.track if item.job else None
            if not song or song.deleted_at or song.decommissioned_at: raise ValueError('Wait for import to finish before editing song details')
            # Completed rows send the full visible metadata, not old draft defaults.
            if not metadata.get('title'): raise ValueError('Song title is required')
            apply_metadata(song, metadata, session.station_id)
            audit('media_editor_updated', user_id=current_admin().id, station_id=session.station_id,
                  target_id=song.uuid, summary='Song details updated from import workspace')
        elif item.status not in ('pending', 'preparing', 'ready', 'failed'):
            raise ValueError('This draft has expired or was removed')
        item.choices = metadata
    else: raise ValueError('Invalid import action')
    item.revision += 1; session.updated_at = utcnow(); db.session.commit()
    return jsonify(item_state(item, slug))


@music_import.get(BASE + '/<identifier>/items/<item_id>/preview')
@admin_required
def preview(slug, identifier, item_id):
    session = session_for(slug, identifier)
    item = MusicImportItem.query.filter_by(session_id=session.id, id=item_id, status='ready', dismissed=False).first_or_404()
    path = staged_path(item.preview_id or item.id)
    try:
        if not stat.S_ISREG(path.lstat().st_mode): abort(404)
    except OSError: abort(404)
    response = send_file(path, mimetype='audio/mpeg', conditional=True)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@music_import.get(BASE + '/<identifier>/items/<item_id>/artwork')
@admin_required
def artwork(slug, identifier, item_id):
    session = session_for(slug, identifier)
    item = MusicImportItem.query.filter_by(session_id=session.id, id=item_id, dismissed=False).first_or_404()
    if not item.artwork: abort(404)
    response = send_file(io.BytesIO(item.artwork), mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'private, no-store'
    return response
