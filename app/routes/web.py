"""Public pages and a login-gated, read-only operations overview."""
from app.services.installation_settings import get_setting
import hmac
import secrets
import time

from flask import Blueprint, flash, abort, redirect, render_template, request, session, url_for, jsonify, current_app
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import AdminUser, Station
from app.services.admin_auth import admin_required, csrf_token, media_mutation_required, current_admin
from app.services.stations import get_station
from app.services.admin_view import context as admin_context, section_data, iso, format_station_time, latest_rows, worker_health
from app.routes.stations import observed_status
from app.services.clocks import current as current_programming
from app.models import Clock, ClockState

web_blueprint = Blueprint('web', __name__)


@web_blueprint.app_context_processor
def admin_template_helpers():
    from app.services.timezones import choices
    return {'format_station_time': format_station_time, 'csrf_token': csrf_token, 'timezone_choices': choices}


login_required = admin_required


def station_or_404(slug, require_enabled=True):
    if request.method == 'POST':
        from app.services.stations import allocation_lock
        allocation_lock()
    try:
        station = get_station(slug)
    except ValueError:
        station = None
    if station is None or station.lifecycle_state in ('pending_delete', 'delete_failed') or (require_enabled and not station.enabled):
        abort(404)
    return station


@web_blueprint.get('/')
def homepage():
    from app.services.website import presentation
    try:
        return render_template('home.html', **presentation())
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Website database unavailable')
        return render_template('website_unavailable.html'), 503


@web_blueprint.get('/stations')
def stations():
    return redirect(url_for('web.homepage') + '#channels', code=302)


@web_blueprint.get('/player/<slug>')
def player(slug):
    from app.services.stations import public_station_for
    try:
        station = public_station_for(slug)
    except ValueError:
        station = None
    if not station or not station.enabled:
        abort(404)
    return render_template('player.html', station=station)


@web_blueprint.get('/dashboard/<slug>')
@login_required
def dashboard(slug):
    return redirect(url_for('web.admin_station', slug=slug), code=302)


def admin_stations():
    return Station.query.filter_by(deleted_at=None).order_by(Station.name, Station.id).all()


def selected_station(stations):
    slug = request.args.get('station', '')
    if slug:
        try:
            station = get_station(slug)
        except ValueError:
            station = None
        if station is None:
            abort(404)
        return station
    stations = [s for s in stations if s.lifecycle_state not in ('pending_delete', 'delete_failed')]
    return next((station for station in stations if station.desired_state == 'running' and station.enabled), stations[0] if stations else None)


@web_blueprint.get('/admin')
@login_required
def admin_home():
    stations = admin_stations()
    from app.services.operations import snapshot
    from app.services.stations import deletion_impact
    from app.services.software_license import unlimited
    return render_template('admin/overview.html', stations=stations, selected=None,
                           ops=snapshot(stations), page='overview',
                           impacts={station.slug: deletion_impact(station) for station in stations},
                           station_limit=0 if unlimited() else get_setting('FREO_MAX_STATIONS'))


@web_blueprint.get('/admin/stations')
@login_required
def admin_station_list():
    return redirect(url_for('web.admin_home', _anchor='stations'))


@web_blueprint.get('/admin/switch-station')
@login_required
def switch_station():
    station = station_or_404(request.args.get('station', ''), require_enabled=False)
    return redirect(url_for('schedule_studio.page', slug=station.slug, view='control'))


@web_blueprint.get('/admin/api/operations')
@login_required
def operations_snapshot():
    from app.services.operations import snapshot
    response = jsonify(snapshot(admin_stations()))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@web_blueprint.get('/admin/api/broadcast-status')
@login_required
def broadcast_snapshot():
    from app.services.broadcast_status import cached_status
    response = jsonify(stations=cached_status(admin_stations()))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@web_blueprint.get('/admin/stations/<slug>')
@login_required
def admin_station(slug):
    station = station_or_404(slug, require_enabled=False)
    data = admin_context(station)
    return render_template('admin/station_overview.html', stations=admin_stations(), selected=station,
                           data=data, page='station-detail', detail=True)


_SECTIONS = {'media', 'categories', 'rotations', 'clocks', 'schedule', 'history', 'system', 'calendar', 'events', 'blocks', 'traffic'}


@web_blueprint.get('/admin/<section>')
@login_required
def admin_section(section):
    if section not in _SECTIONS:
        abort(404)
    stations = admin_stations()
    station = selected_station(stations)
    scheduling = {'calendar':'admin_calendar.page', 'events':'admin_events.list_page',
                  'blocks':'admin_blocks.list_page', 'traffic':'admin_traffic.page'}
    if section in scheduling and station:
        return redirect(url_for(scheduling[section], slug=station.slug))
    if section in {'categories', 'rotations', 'clocks', 'schedule'} and station:
        return redirect(url_for('admin_programming.list_page', slug=station.slug, section=section))
    if section == 'media' and station:
        return redirect(url_for('admin_media.library', slug=station.slug))
    data = admin_context(station, with_status=section == 'system') if station else None
    extra = section_data(station, section) if station else {}
    return render_template('admin/section.html', stations=stations, selected=station,
                           data=data, extra=extra, page=section, section=section)


@web_blueprint.get('/admin/api/stations/<slug>/snapshot')
@login_required
def admin_snapshot(slug):
    station = station_or_404(slug, require_enabled=False)
    programming = current_programming(station.slug)
    clock_state = db.session.get(ClockState, station.id)
    clock = Clock.query.filter_by(station_id=station.id, slug=programming['clock']).first() if programming['clock'] else None
    slots = [slot for slot in clock.slots if slot.enabled] if clock else []
    next_slot = (slots[clock_state.next_slot_index % len(slots)] if slots and clock_state and
                 clock_state.occurrence_key == programming['occurrence'] else None)
    state = station.automation
    worker = worker_health(station)
    return jsonify(station=station.slug, observed=observed_status(station),
                   automation_enabled=bool(state and state.enabled),
                   queue_depth=state.observed_queue_depth if state else None,
                   worker=worker['station'], worker_last_seen=iso(worker['last_seen']),
                   clock=clock.name if clock else None,
                   next_slot=(f'{next_slot.position} · {next_slot.slot_type.title()} → '
                              f'{next_slot.rotation.name if next_slot.rotation else next_slot.category.name if next_slot.category else next_slot.imaging_asset.name if next_slot.imaging_asset else next_slot.imaging_group.name if next_slot.imaging_group else "Unavailable"}'
                              if next_slot else None),
                   local_time=programming['local_time'],
                   timezone=station.timezone, next_transition=programming['next_transition'],
                   next_slot_index=clock_state.next_slot_index if clock_state and clock_state.occurrence_key == programming['occurrence'] else None)


@web_blueprint.get('/admin/api/stations/<slug>/now')
@login_required
def admin_now(slug):
    station = station_or_404(slug, require_enabled=False)
    rows = latest_rows(station, 1)
    row = rows[0] if rows else None
    return jsonify(now_playing=({'title': row.track.title if row.track else row.imaging_asset.name if row.imaging_asset else None,
                                 'artist': row.track.artist if row.track else None,
                                 'kind': 'imaging' if row.imaging_asset else 'music',
                                 'imaging_type': row.imaging_asset.asset_type if row.imaging_asset else None,
                                 'started_at': iso(row.started_at),
                                 'category': row.category.name if row.category else None}
                                if row else None))


@web_blueprint.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        token = secrets.token_urlsafe(32)
        session['login_csrf'] = token
        return render_template('login.html', csrf=token, error=None)
    if not session.get('login_csrf') or not hmac.compare_digest(request.form.get('csrf', ''), session['login_csrf']):
        abort(400)
    if session.get('login_lock_until', 0) > time.time():
        token = secrets.token_urlsafe(32)
        session['login_csrf'] = token
        return render_template('login.html', csrf=token, error='Try again later.'), 429
    email = request.form.get('email', '').strip().lower()[:254]
    password = request.form.get('password', '')
    user = AdminUser.query.filter(AdminUser.active.is_(True), db.or_(AdminUser.email == email, AdminUser.username == email)).first()
    # The dummy hash reduces timing differences for unknown accounts.
    valid = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if not user or not valid:
        attempts = session.get('login_failures', 0) + 1
        session['login_failures'] = attempts
        if attempts >= 5:
            session['login_lock_until'] = time.time() + 900
        token = secrets.token_urlsafe(32)
        session['login_csrf'] = token
        return render_template('login.html', csrf=token, error='Username/email or password was not accepted.'), 401
    from app.services.admin_setup import sign_in
    sign_in(user)
    return redirect(url_for('web.first_setup' if user.setup_required else 'web.admin_home'))


@web_blueprint.route('/admin/setup', methods=['GET', 'POST'])
@admin_required
def first_setup():
    user = current_admin()
    if not user.setup_required:
        return redirect(url_for('web.admin_home'))
    error = None
    if request.method == 'POST':
        from app.services.admin_auth import require_csrf
        from app.services.admin_setup import sign_in
        from app.models import AuditEvent
        from sqlalchemy import update
        from sqlalchemy.exc import IntegrityError
        require_csrf()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not email or '@' not in email or len(email) > 254 or email == 'admin@localhost.invalid':
            error = 'Enter your administrator email address. This does not register you with Freo Live.'
        elif len(password) < 16:
            error = 'Choose a password of at least 16 characters.'
        elif password != request.form.get('confirmation', ''):
            error = 'The passwords do not match.'
        else:
            try:
                result = db.session.execute(update(AdminUser).where(AdminUser.id == user.id,
                    AdminUser.setup_required.is_(True), AdminUser.password_hash == user.password_hash).values(
                        email=email, password_hash=generate_password_hash(password), setup_required=False))
                if result.rowcount != 1:
                    db.session.rollback()
                    abort(409, 'Setup was already completed. Sign in with your chosen password.')
                db.session.add(AuditEvent(admin_user_id=user.id, action='admin.setup.complete',
                    target_type='installation', target_id='1', summary='Completed first-use administrator setup'))
                db.session.commit()
                db.session.refresh(user)
            except IntegrityError:
                db.session.rollback()
                error = 'That email already belongs to an administrator.'
            else:
                sign_in(user)
                return redirect(url_for('web.admin_home'))
    return render_template('admin_setup.html', error=error), (400 if error else 200)


@web_blueprint.post('/admin/logout')
@login_required
def logout():
    if not hmac.compare_digest(request.form.get('csrf', ''), session.get('logout_csrf', '')):
        abort(400)
    session.clear()
    return redirect(url_for('web.homepage'))


@web_blueprint.before_app_request
def provide_logout_token():
    if session.get('admin_user_id') and not session.get('logout_csrf'):
        session['logout_csrf'] = secrets.token_urlsafe(32)


@web_blueprint.after_app_request
def page_security_headers(response):
    if request.path.startswith('/admin') or request.path.startswith('/dashboard/'):
        response.headers['Cache-Control'] = 'private, no-store'
    if response.mimetype == 'text/html':
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; media-src 'self' blob:; connect-src 'self'; "
            "base-uri 'self'; frame-ancestors 'none'")
        if request.endpoint == 'website.preview':
            response.headers['Content-Security-Policy'] = response.headers['Content-Security-Policy'].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    return response


_DUMMY_HASH = generate_password_hash('unusable-random-placeholder', method='scrypt')


@web_blueprint.get('/listen/<slug>')
def listen_alias(slug):
    from app.services.stations import public_station_for
    try:
        station = public_station_for(slug)
    except ValueError:
        station = None
    if not station or not station.enabled:
        abort(404)
    return redirect('/stream/' + station.slug, code=307)


@web_blueprint.post('/admin/stations/<slug>/edit')
@admin_required
def edit_station(slug):
    from app.services.admin_auth import current_admin, require_csrf
    from app.services.stations import update_station
    from sqlalchemy.exc import IntegrityError
    require_csrf()
    station = station_or_404(slug, require_enabled=False)
    try:
        update_station(station, name=request.form.get('name'), description=request.form.get('description'),
            public_slug=request.form.get('public_slug'), timezone_name=request.form.get('timezone'), user=current_admin())
        flash('Station details saved. Previous listener URLs still work.', 'success')
    except (ValueError, IntegrityError) as error:
        db.session.rollback()
        flash(str(error) if isinstance(error, ValueError) else 'That station URL was just taken. Choose another.', 'error')
    return redirect(url_for('web.admin_station_list'))


@web_blueprint.post('/admin/stations/create')
@media_mutation_required
def create_station_page():
    from app.services.stations import create_station
    from app.services.schedule import validate_timezone
    from app.services.admin_media import audit
    try:
        zone = validate_timezone(request.form.get('timezone', 'UTC'))
        station = create_station(request.form.get('name'), request.form.get('slug'),
                                 request.form.get('description', ''), pending=True, timezone_name=zone)
        audit('station_create_requested', user_id=current_admin().id, station_id=station.id,
              target_type='station', target_id=station.slug, summary='Station provisioning requested')
        db.session.commit()
        flash('Station added. Provisioning is queued; refresh to see its status.', 'success')
    except (ValueError, SQLAlchemyError) as error:
        db.session.rollback()
        flash(str(error) if isinstance(error, ValueError) else 'Station could not be added. Refresh and try again.', 'error')
    return redirect(url_for('web.admin_station_list'), code=303)


@web_blueprint.post('/admin/stations/<slug>/delete')
@media_mutation_required
def delete_station_page(slug):
    from app.services.stations import request_delete
    station = get_station(slug)
    if station is None:
        abort(404)
    if request.form.get('confirm') != station.slug:
        flash('Enter the station slug to confirm deletion.', 'error')
    else:
        request_delete(station, current_admin().id)
        flash('Deletion queued. Shared songs, private media, and history will be retained.', 'success')
    return redirect(url_for('web.admin_station_list'), code=303)


@web_blueprint.post('/admin/stations/<slug>/retry')
@media_mutation_required
def retry_station_page(slug):
    from app.services.station_lifecycle import retry
    station = get_station(slug)
    if station is None:
        abort(404)
    try:
        retry(station)
        flash('Provisioning retry queued.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('web.admin_station_list'), code=303)
