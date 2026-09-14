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
