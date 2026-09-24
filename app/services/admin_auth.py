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
    if not user or not user.active:
        return None
    from .admin_setup import credential_stamp, login_session_valid
    stamp = session.get('credential_stamp')
    if stamp is not None and (not isinstance(stamp, str) or not hmac.compare_digest(stamp, credential_stamp(user))):
        return None
    if user.setup_required and stamp is None:
        return None
    if not login_session_valid(user):
        return None
    return user


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
        user = current_admin()
        if user is None:
            # Signed-out tabs still poll protected endpoints. Do not erase an
            # anonymous login form's CSRF token or failed-attempt counters.
            if 'admin_user_id' in session:
                session.clear()
            return redirect(url_for('web.login'))
        if user.setup_required and request.endpoint not in ('web.first_setup', 'web.logout', 'web.login'):
            return redirect(url_for('web.first_setup'))
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

def can_manage_traffic(user, station):
    """Separate traffic boundary for a future traffic-manager role."""
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
