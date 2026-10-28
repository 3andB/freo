"""DJ administration and authenticated access to recorded shows."""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import AdminUser, AdminLoginSession, DJStationAssignment, ShowRecording, LiveSession
from app.routes.web import admin_stations
from app.routes.admin_live import station_for_operator
from app.services.admin_auth import admin_required, current_admin, require_csrf
from app.services.admin_media import audit


dj = Blueprint('dj', __name__)


@dj.route('/admin/djs', methods=['GET', 'POST'])
@admin_required
def accounts():
    if current_admin().role != 'ADMIN':
        abort(403)
    if request.method == 'POST':
        require_csrf()
        try:
            from app.services.stations import allocation_lock
            allocation_lock()
            identifier = request.form.get('user_id', type=int)
            user = db.session.get(AdminUser, identifier) if identifier else None
            if identifier and not user:
                abort(404)
            if user and (user.id == current_admin().id or user.installation_admin):
                raise ValueError('Your account and installation administrators cannot be converted to DJs here.')
            station_ids = {int(value) for value in request.form.getlist('station_id')}
            valid = {s.id for s in admin_stations()}
            if not station_ids <= valid:
                raise ValueError('Invalid station assignment')
            if not user:
                email = request.form.get('email', '').strip().lower()
                name = request.form.get('username', '').strip()
                password = request.form.get('password', '')
                if not email or '@' not in email or len(email) > 254 or not name or len(name) > 64:
                    raise ValueError('Enter an email address and a DJ name of at most 64 characters.')
                if len(password) < 16:
                    raise ValueError('Passwords must contain at least 16 characters.')
                user = AdminUser(email=email, username=name, password_hash=generate_password_hash(password, method='scrypt'))
                db.session.add(user)
                db.session.flush()
            user.role = 'DJ'
            user.active = request.form.get('active') == 'yes'
            if not user.active:
                AdminLoginSession.query.filter_by(admin_user_id=user.id).delete()
            existing = {a.station_id for a in DJStationAssignment.query.filter_by(admin_user_id=user.id)}
            DJStationAssignment.query.filter_by(admin_user_id=user.id).filter(DJStationAssignment.station_id.notin_(station_ids)).delete(synchronize_session=False)
            for station_id in station_ids - existing:
                db.session.add(DJStationAssignment(admin_user_id=user.id, station_id=station_id))
            audit('dj_permissions_changed', user_id=current_admin().id, target_type='admin_user', target_id=str(user.id),
                  summary='DJ assignments updated: ' + ','.join(map(str, sorted(station_ids))))
            db.session.commit()
            flash('DJ access saved. Revoked live access returns to automation on the next worker observation.', 'success')
            return redirect(url_for('.accounts'))
        except (ValueError, IntegrityError) as error:
            db.session.rollback()
            flash(str(error) if isinstance(error, ValueError) else 'Email address or DJ name already exists.', 'error')
    users = AdminUser.query.order_by(AdminUser.email).all()
    assignments = {(a.admin_user_id, a.station_id) for a in DJStationAssignment.query.all()}
    return render_template('admin/djs.html', stations=admin_stations(), selected=None, page='djs', users=users, assignments=assignments)


@dj.get('/admin/stations/<slug>/recordings')
@admin_required
def recordings(slug):
    station = station_for_operator(slug)
    query = ShowRecording.query.filter_by(station_id=station.id)
    if current_admin().role == 'DJ':
        query = query.filter_by(admin_user_id=current_admin().id)
    query = query.filter(ShowRecording.deleted_at.is_(None))
    from sqlalchemy import case, literal
    display_name = case((ShowRecording.name != '', ShowRecording.name),
                        else_=literal('show-') + ShowRecording.id + literal('.mp3'))
    search = request.args.get('q', '').strip()[:160]
    status = request.args.get('status', '')
    if search:
        from sqlalchemy import or_
        query = query.filter(or_(display_name.icontains(search, autoescape=True),
                                 ShowRecording.id.icontains(search, autoescape=True),
                                 LiveSession.dj_name.icontains(search, autoescape=True)))
    if status in ('pending', 'recording', 'finalizing', 'complete', 'partial', 'failed'):
        query = query.filter(ShowRecording.status == status)
    else:
        status = ''
    sort = request.args.get('sort', 'newest')
    ordering = {'newest': LiveSession.created_at.desc(), 'name': display_name.asc(),
                'size': ShowRecording.file_size_bytes.desc().nullslast(), 'duration': ShowRecording.duration_ms.desc().nullslast()}
    if sort not in ordering:
        sort = 'newest'
    page = max(1, request.args.get('page', 1, type=int))
    from sqlalchemy.orm import contains_eager
    rows = query.join(ShowRecording.session).options(contains_eager(ShowRecording.session)).order_by(ordering[sort], ShowRecording.id).paginate(page=page, per_page=30, error_out=False)
    from app.services.recording_manager import editable
    return render_template('admin/recordings.html', stations=admin_stations(), selected=station,
                           page='recordings', recordings=rows, search=search, status=status, sort=sort, editable=editable)


@dj.get('/admin/stations/<slug>/recordings/<identifier>/audio')
@admin_required
def recording_file(slug, identifier):
    station = station_for_operator(slug)
    row = ShowRecording.query.filter_by(id=identifier, station_id=station.id).first_or_404()
    if current_admin().role == 'DJ' and row.admin_user_id != current_admin().id:
        abort(403)
    if row.deleted_at or row.deletion_requested_at or row.status not in ('complete', 'partial') or not row.duration_ms:
        abort(404)
    from app.services.media_storage import LocalMediaStorage
    try:
        path = LocalMediaStorage().recording_file(station.slug, row.storage_key)
        response = send_file(path, mimetype='audio/mpeg', conditional=True,
                             as_attachment=request.args.get('download') == '1',
                             download_name=row.filename, max_age=0)
    except (OSError, ValueError):
        abort(404)
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@dj.post('/admin/stations/<slug>/recordings/<identifier>/<action>')
@admin_required
def recording_action(slug, identifier, action):
    station = station_for_operator(slug)
    require_csrf()
    row = ShowRecording.query.filter_by(id=identifier, station_id=station.id).with_for_update().first_or_404()
    user = current_admin()
    if user.role == 'DJ' and row.admin_user_id != user.id:
        abort(403)
    from app.services.recording_manager import editable, filename
    from app.services.live_sessions import now
    if action not in ('rename', 'delete'):
        abort(404)
    if not editable(row) or request.form.get('revision', type=int) != row.revision:
        abort(409, description='This recording changed or is still in use. Refresh the recordings page.')
    if action == 'rename':
        try:
            row.name = filename(request.form.get('name', ''))
        except ValueError as error:
            abort(400, description=str(error))
        message = 'Recording renamed.'
    else:
        if request.form.get('confirm') != 'yes':
            abort(400, description='Confirm permanent deletion of the MP3.')
        row.deletion_requested_at = now()
        row.deletion_requested_by = user.id
        row.deletion_error = None
        message = 'Deletion queued. The automation worker will remove the local MP3.'
    row.revision += 1
    audit('recording_' + action, user_id=user.id, station_id=station.id,
          target_type='show_recording', target_id=row.id,
          summary=f'Recording renamed to {row.name}' if action == 'rename' else message)
    db.session.commit()
    flash(message, 'success')
    return redirect(url_for('.recordings', slug=slug), code=303)


@dj.post('/admin/stations/<slug>/live/end-show')
@admin_required
def end_show(slug):
    station = station_for_operator(slug)
    require_csrf()
    from app.services.live_sessions import active_session, require_owner
    try:
        require_owner(station, current_admin(), allow_admin_end=True)
    except ValueError:
        abort(403)
    show = active_session(station)
    if show:
        show.end_requested = True
        show.end_reason = 'operator_end'
        audit('live_show_end_requested', user_id=current_admin().id, station_id=station.id,
              target_type='live_session', target_id=show.id, summary='Return show to automation')
        db.session.commit()
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(ok=True, message='Return to automation requested. Waiting for engine confirmation.')
    return redirect(url_for('admin_live.page', slug=slug))
