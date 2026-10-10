"""Station-authorized public discovery and DJ profile editing."""
import hashlib
from flask import Blueprint, abort, flash, redirect, render_template, request, Response, url_for
from app.extensions import db
from app.models import AdminUser, Artist, Track, DJStationAssignment, DJStationProfile
from app.routes.web import station_or_404, admin_stations
from app.services.admin_auth import admin_required, require_csrf, current_admin
from app.services.admin_media import audit
from app.services import polish

platform_polish = Blueprint('platform_polish', __name__)


@platform_polish.app_context_processor
def helpers():
    return dict(discovery_kinds=polish.LINK_KINDS, visual_modes=polish.VISUAL_MODES,
                ad_sizes=polish.sizes, public_discovery_links=polish.public_links)


@platform_polish.post('/admin/stations/<slug>/discovery/<kind>/<int:identifier>')
@admin_required
def discovery(slug, kind, identifier):
    require_csrf()
    station = station_or_404(slug, require_enabled=False)
    model = {'track': Track, 'artist': Artist}.get(kind)
    if not model:
        abort(404)
    row = model.query.filter_by(id=identifier, station_id=station.id).first_or_404()
    if kind == 'track' and (row.deleted_at or row.audio_kind != 'MUSIC'):
        abort(404)
    try:
        row.discovery_links = polish.form_links(request.form)
        audit('discovery_links_updated', user_id=current_admin().id, station_id=station.id,
              target_type=kind, target_id=str(row.id), summary='Public discovery links updated')
        db.session.commit()
        flash('Discovery links saved.', 'success')
    except ValueError as error:
        db.session.rollback()
        return render_template('admin/discovery_edit.html', selected=station, stations=admin_stations(),
            page='media', item=row, kind=kind, error=str(error)), 400
    return redirect(url_for('admin_media.track_detail', slug=slug, track_uuid=row.uuid) if kind == 'track'
                    else url_for('admin_media.artist_detail', slug=slug, artist_id=row.id), code=303)


@platform_polish.route('/admin/stations/<slug>/dj-profiles', methods=['GET', 'POST'])
@admin_required
def profiles(slug):
    station = station_or_404(slug, require_enabled=False)
    error = None
    if request.method == 'POST':
        require_csrf()
        user_id = request.form.get('user_id', type=int)
        assignment = DJStationAssignment.query.filter_by(admin_user_id=user_id, station_id=station.id).with_for_update().first()
        if not assignment:
            abort(404)
        try:
            from app.services.player import clean_text
            from app.routes.station_settings import decode_logo
            row = db.session.get(DJStationProfile, (user_id, station.id))
            if request.form.get('revision', type=int) != (row.revision if row else 0):
                raise ValueError('Profile changed. Reload before saving.')
            row = row or DJStationProfile(user_id=user_id, station_id=station.id, revision=0)
            row.bio = clean_text(request.form.get('bio', ''), 1000, multiline=True)
            row.links = polish.form_links(request.form)
            upload = request.files.get('image')
            if upload and upload.filename:
                if request.form.get('remove_image'):
                    raise ValueError('Choose upload or remove image')
                row.image = decode_logo(upload, output_limit=512)[0]
                row.image_version = hashlib.sha256(row.image).hexdigest()
            elif request.form.get('remove_image'):
                row.image = row.image_version = None
            row.revision += 1
            db.session.add(row)
            audit('dj_profile_updated', user_id=current_admin().id, station_id=station.id,
                  target_type='admin_user', target_id=str(user_id), summary='Station public DJ profile updated')
            db.session.commit()
            flash('DJ profile saved.', 'success')
            return redirect(url_for('.profiles', slug=slug), code=303)
        except ValueError as exc:
            db.session.rollback()
            error = str(exc)
    users = AdminUser.query.join(DJStationAssignment, DJStationAssignment.admin_user_id == AdminUser.id).filter(
        DJStationAssignment.station_id == station.id).order_by(AdminUser.username).all()
    rows = {row.user_id: row for row in DJStationProfile.query.filter_by(station_id=station.id)}
    return render_template('admin/dj_profiles.html', selected=station, stations=admin_stations(),
                           page='djs', users=users, profiles=rows, error=error), 400 if error else 200


@platform_polish.get('/station-assets/<slug>/dj/<int:user_id>.png')
def dj_image(slug, user_id):
    from app.routes.player_experience import public_station
    station = public_station(slug)
    if not polish.dj_profile(station, user_id):
        abort(404)
    row = db.session.get(DJStationProfile, (user_id, station.id))
    if not row.image:
        abort(404)
    response = Response(row.image, mimetype='image/png')
    response.set_etag(row.image_version)
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response.make_conditional(request)
