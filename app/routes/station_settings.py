"""Station identity, public branding and private contact details."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from flask import Blueprint, abort, flash, redirect, render_template, request, Response, url_for, current_app, jsonify
from app.extensions import db
from app.models import StationLogo
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.programming import clean_text
from app.services.stations import update_station, public_station_for
from app.services.station_domains import preferred_url
from app.services.visual_schedule import policy

station_settings = Blueprint('station_settings', __name__)


@station_settings.post('/admin/stations/<slug>/settings/directories/<directory>')
@admin_required
def directory(slug, directory):
    require_csrf()
    if directory not in ('radio-browser', 'internet-radio'):
        abort(404)
    station = station_or_404(slug, require_enabled=False)
    from app.services.radio_directories import submit_radio_browser, queue_internet_radio
    try:
        if directory == 'radio-browser':
            submit_radio_browser(station, current_admin())
            flash('Station listed in Radio Browser.', 'success')
        elif directory == 'internet-radio':
            value = request.form.get('enabled')
            if value not in ('yes', 'no'):
                raise ValueError('Choose ON or OFF for the public directory listing.')
            changed = queue_internet_radio(station, value == 'yes', current_admin())
            db.session.commit()
            flash('Directory change queued. Refresh this page to check its status.' if changed else 'Directory setting is already up to date.', 'success')
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'error')
    except Exception as error:
        db.session.rollback()
        current_app.logger.error('Directory action failed: station_id=%s error_type=%s', station.id, type(error).__name__)
        flash('Directory action could not be saved. Refresh this page to check its status.', 'error')
    return redirect(url_for('.page', slug=slug) + '#public-directories', code=303)


@station_settings.get('/<slug>')
def directory_stream(slug):
    from app.services.stations import get_station
    try:
        station = get_station(slug)
    except ValueError:
        station = None
    if (not station or not station.enabled or not station.stream.enabled or station.lifecycle_state != 'ready'
            or not (station.internet_radio_enabled or station.internet_radio_pending is True)):
        abort(404)
    response = redirect('/stream/' + station.slug, code=307)
    response.headers['Cache-Control'] = 'no-store'
    return response


def decode_logo(upload, output_limit=None):
    raw = upload.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError('Logo must be at most 10 MB')
    if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff') or
            (raw.startswith(b'RIFF') and raw[8:12] == b'WEBP')):
        raise ValueError('Choose a JPEG, PNG or WebP logo')
    try:
        with tempfile.TemporaryDirectory(prefix='freo-logo-') as folder:
            source = Path(folder) / 'upload'
            source.write_bytes(raw)
            result = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                'stream=width,height','-of','json',str(source)],capture_output=True,check=True,timeout=15)
            stream = json.loads(result.stdout)['streams'][0]
            if not (1 <= stream['width'] <= 3000 and 1 <= stream['height'] <= 3000):
                raise ValueError('Logo dimensions must be at most 3000 × 3000 pixels')
            images = []
            original_scale=['-vf',f"scale=w='min({output_limit},iw)':h='min({output_limit},ih)':force_original_aspect_ratio=decrease"] if output_limit else []
            for name, scale in [('original',original_scale),('thumbnail',['-vf',"scale=w='min(512,iw)':h='min(512,ih)':force_original_aspect_ratio=decrease"])]:
                target = Path(folder) / (name + '.png')
                subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(source),'-frames:v','1',
                    '-map_metadata','-1',*scale,'-threads','1',str(target)],capture_output=True,check=True,timeout=20)
                images.append(target.read_bytes())
            return images
    except (subprocess.SubprocessError, KeyError, IndexError, json.JSONDecodeError) as error:
        raise ValueError('Logo could not be decoded; choose a valid JPEG, PNG or WebP image') from error


def settings_token(station):
    """Fingerprint editable values, excluding worker progress and heartbeat state."""
    row = policy(station)
    fields = ('name', 'description', 'public_slug', 'timezone', 'city', 'region', 'country',
              'genre', 'contact_email', 'phone', 'directory_categories', 'directory_opt_in',
              'publish_contact')
    value = {key: getattr(station, key) for key in fields}
    value.update(directory=station.internet_radio_pending if station.internet_radio_pending is not None else station.internet_radio_enabled, logo=station.logo.version if station.logo else None,
                 audio_revision=station.stream.audio_revision,
                 playlist=row.default_playlist_id if row else None)
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save_combined(station):
    from app.services.station_audio import active_settings, from_form, queue_settings
    from app.services.radio_directories import queue_internet_radio
    from app.services import visual_schedule as vs
    from app.models import ChannelSchedule, ScheduleTransition
    row = ChannelSchedule.query.filter_by(station_id=station.id).with_for_update().first()
    if row:
        db.session.refresh(row)
    if request.form.get('settings_token') != settings_token(station):
        raise ValueError('Settings changed in another window. Your edits are still here. Open this page in a new tab to compare before trying again.')
    # Queue durable work in this transaction; workers see it only after commit.
    if 'bitrate' in request.form:
        values = from_form(request.form)
        if values != (station.stream.pending_audio or active_settings(station.stream)):
            queue_settings(station, values, int(request.form.get('revision', '-1')), current_admin())
    if 'directory_enabled' in request.form:
        enabled = request.form['directory_enabled'] == 'yes'
        if request.form['directory_enabled'] not in ('yes', 'no'):
            raise ValueError('Choose ON or OFF for the public directory listing.')
        effective = station.internet_radio_pending if station.internet_radio_pending is not None else station.internet_radio_enabled
        if enabled != effective:
            queue_internet_radio(station, enabled, current_admin())
    proposed = request.form.get('default_playlist', '')
    proposed = int(proposed) if proposed else None
    if proposed != (row.default_playlist_id if row else None):
        if ScheduleTransition.query.filter_by(station_id=station.id).filter(ScheduleTransition.state.in_(('PENDING', 'PREPARING', 'FADING'))).first():
            raise ValueError('Wait for the playback mode change to finish before saving.')
        if proposed is not None:
            ref = vs.source(station, dict(kind='playlist', id=proposed))
            if not vs.source_tracks(station, ref):
                raise ValueError('Choose a playlist with playable songs.')
        row = row or vs.policy(station, True)
        row.default_playlist_id = proposed
        row.revision += 1


@station_settings.route('/admin/stations/<slug>/settings', methods=['GET','POST'])
@admin_required
def page(slug):
    station = station_or_404(request.args.get('station',slug) if request.method == 'GET' else slug, require_enabled=False)
    if request.method == 'GET' and station.slug != slug:
        return redirect(url_for('.page',slug=station.slug))
    error = None
    if request.method == 'POST':
        require_csrf()
        try:
            if request.form.get('combined') == 'yes':
                from app.services.stations import allocation_lock
                allocation_lock()
                from app.models import Station
                station = Station.query.filter_by(id=station.id).with_for_update().populate_existing().one()
                save_combined(station)
            fields = {key:clean_text(request.form.get(key,''),limit) for key,limit in
                      [('city',120),('region',120),('country',2),('genre',100),('contact_email',254),('phone',40)]}
            if fields['contact_email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', fields['contact_email']):
                raise ValueError('Enter a valid contact email')
            fields['country'] = fields['country'].upper()
            if fields['country'] and not re.fullmatch(r'[A-Z]{2}', fields['country']):
                raise ValueError('Use a two-letter country code, such as AU, US or GB')
            categories = [clean_text(value,100,True) for value in request.form.get('directory_categories','').split(',') if value.strip()]
            if len(categories) > 20:
                raise ValueError('Use at most 20 directory categories')
            upload = request.files.get('logo')
            images = decode_logo(upload) if upload and upload.filename else None
            if images and request.form.get('remove_logo'):
                raise ValueError('Choose either a new logo or Remove logo')
            update_station(station,name=request.form.get('name',''),description=request.form.get('description',''),
                public_slug=request.form.get('public_slug',''),timezone_name=request.form.get('timezone','UTC'),user=current_admin(),commit=False)
            for key,value in fields.items():
                setattr(station,key,value)
            station.directory_categories = list(dict.fromkeys(categories))
            station.directory_opt_in = request.form.get('directory_opt_in') == 'yes'
            station.publish_contact = request.form.get('publish_contact') == 'yes'
            if images:
                station.logo = station.logo or StationLogo(station_id=station.id)
                station.logo.image, station.logo.thumbnail = images
                station.logo.version = hashlib.sha256(images[0]).hexdigest()
            elif request.form.get('remove_logo'):
                station.logo = None
            db.session.commit()
            if request.accept_mimetypes.best == 'application/json':
                return jsonify(message='All changes saved. Queued audio and directory changes are applied in the background.', token=settings_token(station), audio_revision=station.stream.audio_revision, public_url=preferred_url(station), logo_url=url_for('.logo',slug=station.slug,v=station.logo.version) if station.logo else None)
            flash('Station settings saved','success')
            return redirect(url_for('.page',slug=station.slug))
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
            if request.accept_mimetypes.best == 'application/json':
                return jsonify(error=error), 400
    from app.services.station_audio import active_settings
    return render_template('admin/station_settings.html',selected=station,stations=admin_stations(),page='settings',error=error,public_url=preferred_url(station),settings_token=settings_token(station),playback_policy=policy(station),audio_values=station.stream.pending_audio or active_settings(station.stream)), 400 if error else 200


@station_settings.route('/admin/stations/<slug>/settings/audio', methods=['GET', 'POST'])
@admin_required
def audio(slug):
    station = station_or_404(slug, require_enabled=False)
    from app.services.station_audio import active_settings, from_form, queue_settings
    if request.method == 'POST':
        require_csrf()
        try:
            changed = queue_settings(station, from_form(request.form), int(request.form.get('revision', '')), current_admin())
            db.session.commit()
            flash('Audio changes queued. Listeners may briefly reconnect while the station restarts.' if changed else 'Audio settings are already up to date.', 'success')
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else 'Invalid audio settings', 'error')
            return redirect(url_for('.page', slug=slug) + '#audio-settings', code=303)
        return redirect(url_for('.page', slug=slug) + '#audio-settings', code=303)
    stream = station.stream
    response = jsonify(status=stream.audio_status, error=stream.audio_error, revision=stream.audio_revision,
                       active=active_settings(stream), pending=stream.pending_audio)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@station_settings.get('/station-assets/<slug>/logo.png')
def logo(slug):
    try:
        station = public_station_for(slug)
    except ValueError:
        abort(404)
    # Admin previews also work for stations that are stopped or disabled.
    if not station or (not station.enabled and not current_admin()) or not station.logo:
        abort(404)
    full = request.args.get('size') == 'original'
    response = Response(station.logo.image if full else station.logo.thumbnail,mimetype='image/png')
    response.set_etag(station.logo.version + ('-original' if full else '-thumbnail'))
    response.headers['Cache-Control'] = 'public, max-age=300' if station.enabled else 'private, no-store'
    return response.make_conditional(request)
