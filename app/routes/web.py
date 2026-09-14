"""Public pages and a login-gated, read-only operations overview."""
import hmac
import secrets
import time
from functools import wraps

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import AdminUser, Station
from app.services.stations import get_station

web_blueprint = Blueprint('web', __name__)


def login_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        user = db.session.get(AdminUser, session.get('admin_user_id')) if session.get('admin_user_id') else None
        if user is None or not user.active:
            session.clear()
            return redirect(url_for('web.login'))
        return view(*args, **kwargs)
    return guarded


def station_or_404(slug):
    try:
        station = get_station(slug)
    except ValueError:
        station = None
    if station is None or not station.enabled:
        abort(404)
    return station


@web_blueprint.get('/')
def homepage():
    try:
        stations = Station.query.filter_by(enabled=True).order_by(Station.slug).all()
    except SQLAlchemyError:
        stations = []
    return render_template('home.html', stations=stations)


@web_blueprint.get('/stations')
def stations():
    rows = Station.query.filter_by(enabled=True).order_by(Station.slug).all()
    return render_template('stations.html', stations=rows)


@web_blueprint.get('/player/<slug>')
def player(slug):
    return render_template('player.html', station=station_or_404(slug))


@web_blueprint.get('/dashboard/<slug>')
@login_required
def dashboard(slug):
    return render_template('dashboard.html', station=station_or_404(slug))


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
    user = AdminUser.query.filter_by(email=email, active=True).first()
    # The dummy hash reduces timing differences for unknown accounts.
    valid = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if not user or not valid:
        attempts = session.get('login_failures', 0) + 1
        session['login_failures'] = attempts
        if attempts >= 5:
            session['login_lock_until'] = time.time() + 900
        token = secrets.token_urlsafe(32)
        session['login_csrf'] = token
        return render_template('login.html', csrf=token, error='Email or password was not accepted.'), 401
    session.clear()
    session['admin_user_id'] = user.id
    session.permanent = True
    return redirect(url_for('web.stations'))


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
    if response.mimetype == 'text/html':
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; media-src 'self'; connect-src 'self'; "
            "base-uri 'self'; frame-ancestors 'none'")
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.path.startswith('/admin/') or request.path.startswith('/dashboard/'):
            response.headers['Cache-Control'] = 'private, no-store'
    return response


_DUMMY_HASH = generate_password_hash('unusable-random-placeholder', method='scrypt')
