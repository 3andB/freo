"""One-time local administrator setup; never runs during application startup."""
import hashlib
import secrets
from flask import g, request, session, redirect, url_for, current_app
from flask.sessions import SecureCookieSessionInterface
from sqlalchemy import text
from werkzeug.security import generate_password_hash
from app.extensions import db
from app.models import AdminUser, AdminBootstrap, AuditEvent

DEFAULT_PASSWORD = 'IAmOnTheAir'


def credential_stamp(user):
    return hashlib.sha256(user.password_hash.encode()).hexdigest()


def sign_in(user):
    session.clear()
    session['admin_user_id'] = user.id
    session['credential_stamp'] = credential_stamp(user)
    session['admin_csrf'] = secrets.token_urlsafe(32)
    session['logout_csrf'] = secrets.token_urlsafe(32)
    session.permanent = True


def bootstrap():
    if db.engine.dialect.name == 'postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(717304023)'))
    if db.session.get(AdminBootstrap, 1):
        return False
    db.session.add(AdminBootstrap(id=1))
    created = AdminUser.query.count() == 0
    if created:
        db.session.add(AdminUser(email='admin@localhost.invalid', username='admin',
            password_hash=generate_password_hash(DEFAULT_PASSWORD), installation_admin=True, setup_required=True))
        db.session.add(AuditEvent(action='admin.bootstrap', target_type='installation', target_id='1',
            summary='Created first-use local administrator; password replacement required'))
    db.session.commit()
    return created


class InstallationSessionInterface(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        # Only saved server configuration chooses HTTP mode, never client headers.
        return getattr(g, 'freo_cookie_secure', super().get_cookie_secure(app))


def configure_cookie_policy():
    if not hasattr(g, 'freo_cookie_secure'):
        from app.services.installation_settings import get_setting
        from urllib.parse import urlsplit
        g.freo_cookie_secure = current_app.config['SESSION_COOKIE_SECURE']
        scheme = urlsplit(get_setting('PUBLIC_BASE_URL')).scheme
        if scheme:
            g.freo_cookie_secure = scheme != 'http'


def cookie_policy(response):
    # Public pages and static responses can refresh a permanent admin session too.
    if session or session.modified:
        configure_cookie_policy()
    return response


def guard_setup():
    if not request.path.startswith('/admin'):
        return None
    configure_cookie_policy()
    from app.services.admin_auth import current_admin
    user = current_admin()
    if user and user.setup_required and request.endpoint not in ('web.first_setup', 'web.logout', 'web.login'):
        return redirect(url_for('web.first_setup'))
