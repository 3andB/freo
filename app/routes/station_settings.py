"""Station identity, public branding and private contact details."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from flask import Blueprint, abort, flash, redirect, render_template, request, Response, url_for, current_app
from app.extensions import db
from app.models import StationLogo
from app.routes.web import admin_stations, station_or_404
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.programming import clean_text
from app.services.stations import update_station, public_station_for

station_settings = Blueprint('station_settings', __name__)


def decode_logo(upload):
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
            for name, scale in [('original',[]),('thumbnail',['-vf',"scale=w='min(512,iw)':h='min(512,ih)':force_original_aspect_ratio=decrease"])]:
                target = Path(folder) / (name + '.png')
                subprocess.run(['ffmpeg','-v','error','-threads','1','-i',str(source),'-frames:v','1',
                    '-map_metadata','-1',*scale,'-threads','1',str(target)],capture_output=True,check=True,timeout=20)
                images.append(target.read_bytes())
            return images
    except (subprocess.SubprocessError, KeyError, IndexError, json.JSONDecodeError) as error:
        raise ValueError('Logo could not be decoded; choose a valid JPEG, PNG or WebP image') from error


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
            fields = {key:clean_text(request.form.get(key,''),limit) for key,limit in
                      [('city',120),('region',120),('contact_email',254),('phone',40)]}
            if fields['contact_email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', fields['contact_email']):
                raise ValueError('Enter a valid contact email')
            upload = request.files.get('logo')
            images = decode_logo(upload) if upload and upload.filename else None
            if images and request.form.get('remove_logo'):
                raise ValueError('Choose either a new logo or Remove logo')
            update_station(station,name=request.form.get('name',''),description=request.form.get('description',''),
                public_slug=request.form.get('public_slug',''),timezone_name=request.form.get('timezone','UTC'),user=current_admin(),commit=False)
            for key,value in fields.items():
                setattr(station,key,value)
            station.publish_contact = request.form.get('publish_contact') == 'yes'
            if images:
                station.logo = station.logo or StationLogo(station_id=station.id)
                station.logo.image, station.logo.thumbnail = images
                station.logo.version = hashlib.sha256(images[0]).hexdigest()
            elif request.form.get('remove_logo'):
                station.logo = None
            db.session.commit()
            flash('Station settings saved','success')
            return redirect(url_for('.page',slug=station.slug))
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
    return render_template('admin/station_settings.html',selected=station,stations=admin_stations(),page='settings',error=error,public_url=(current_app.config.get('PUBLIC_BASE_URL') or request.url_root).rstrip('/') + url_for('web.player',slug=station.public_slug or station.slug)), 400 if error else 200


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
