"""Central authenticated global-admin boundary for browser media operations."""
import hmac
import secrets
from functools import wraps

from flask import abort, redirect, request, session, url_for

from app.extensions import db
from app.models import AdminUser


def current_admin():
    identity = session.get('admin_user_id')
    user = db.session.get(AdminUser, identity) if isinstance(identity, int) else None
    return user if user and user.active else None


def csrf_token():
    if not session.get('admin_csrf'):
        session['admin_csrf'] = secrets.token_urlsafe(32)
    return session['admin_csrf']


def require_csrf():
    expected = session.get('admin_csrf')
    supplied = request.form.get('csrf', '')
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        abort(400)


def admin_required(view):
    @wraps(view)
    def guarded(*args, **kwargs):
        if current_admin() is None:
            session.clear()
            return redirect(url_for('web.login'))
        return view(*args, **kwargs)
    return guarded


def media_mutation_required(view):
    @admin_required
    @wraps(view)
    def guarded(*args, **kwargs):
        require_csrf()
        return view(*args, **kwargs)
    return guarded


def can_manage_programming(user, station):
    """Phase 8 global-admin permission boundary; station roles can extend here."""
    return bool(user and user.active and station is not None)


def can_control_playout(user, station):
    """Distinct permission boundary for real-time operator actions."""
    return bool(user and user.active and station is not None)


def can_manage_events(user, station):
    """Timed events are programming mutations, kept as an explicit boundary."""
    return can_manage_programming(user, station)


def programming_mutation_required(view):
    @admin_required
    @wraps(view)
    def guarded(*args, **kwargs):
        require_csrf()
        from app.services.stations import get_station
        try:
            station = get_station(kwargs.get('slug'))
        except ValueError:
            station = None
        if station is None:
            abort(404)
        if not can_manage_programming(current_admin(), station):
            abort(403)
        return view(*args, **kwargs)
    return guarded
