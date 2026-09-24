"""Logout must survive delivery of an already generated authenticated response."""
from http.cookies import SimpleCookie

import pytest
from tests.test_web import app
from tests.test_admin_setup import login


@pytest.mark.parametrize('path', ['/admin/api/broadcast-status', '/static/theme.js', '/admin/login'])
def test_delayed_response_cannot_restore_logged_out_authentication(app, path):
    client = app.test_client()
    assert login(client, 'test-password-long-enough', 'admin@example.test').status_code == 302
    name = app.config['SESSION_COOKIE_NAME']
    delayed = app.test_client()
    delayed.set_cookie(name, client.get_cookie(name).value)
    # Generate the response using the pre-logout identity, but hold its cookie
    # headers until after logout. No sleeps or successful-rerun assumptions.
    held = delayed.get(path)
    assert held.status_code == 200
    with client.session_transaction() as state:
        csrf = state['logout_csrf']
    assert client.post('/admin/logout', data={'csrf': csrf}).status_code == 302
    assert client.get('/admin').location.endswith('/admin/login')
    for header in held.headers.getlist('Set-Cookie'):
        cookies = SimpleCookie(); cookies.load(header)
        if name in cookies:
            client.set_cookie(name, cookies[name].value)
    response = client.get('/admin')
    assert response.status_code == 302
    assert response.location.endswith('/admin/login')


def test_logout_is_per_login_and_old_cookie_stays_revoked(app):
    from app.extensions import db
    from app.models import AdminLoginSession
    first, second = app.test_client(), app.test_client()
    for client in (first, second):
        login(client, 'test-password-long-enough', 'admin@example.test')
    name = app.config['SESSION_COOKIE_NAME']
    old = first.get_cookie(name).value
    with first.session_transaction() as state:
        csrf = state['logout_csrf']
    assert first.post('/admin/logout', data={'csrf': csrf}).status_code == 302
    first.set_cookie(name, old)
    assert first.get('/admin').status_code == 302
    assert second.get('/admin').status_code == 200
    with app.app_context():
        assert db.session.query(AdminLoginSession).count() == 1
    # A fresh login works, even when the browser presents a revoked cookie.
    assert login(first, 'test-password-long-enough', 'admin@example.test').status_code == 302
    assert first.get('/admin').status_code == 200
    first.set_cookie(name, old)
    assert first.get('/admin').status_code == 302


def test_invalid_logout_csrf_does_not_revoke_login(app):
    client = app.test_client()
    login(client, 'test-password-long-enough', 'admin@example.test')
    assert client.post('/admin/logout', data={'csrf': 'wrong'}).status_code == 400
    assert client.get('/admin').status_code == 200


def test_untracked_preupgrade_cookie_requires_login(app):
    from app.extensions import db
    from app.models import AdminUser
    from app.services.admin_setup import credential_stamp
    with app.app_context():
        user = db.session.query(AdminUser).one()
        old = dict(admin_user_id=user.id, credential_stamp=credential_stamp(user),
                   logout_csrf='old-cookie-with-no-database-record', _permanent=True)
    cookie = app.session_interface.get_signing_serializer(app).dumps(old)
    client = app.test_client()
    client.set_cookie(app.config['SESSION_COOKIE_NAME'], cookie)
    assert client.get('/admin').location.endswith('/admin/login')


def test_active_sessions_renew_but_idle_cookie_still_expires_after_one_hour(app, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from itsdangerous.timed import TimestampSigner
    from app.services import admin_setup
    from app.extensions import db
    from app.models import AdminLoginSession
    clock = [datetime.now(timezone.utc)]
    class Clock:
        @staticmethod
        def now(tz=None): return clock[0]
    monkeypatch.setattr(admin_setup, 'datetime', Clock)
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda _: int(clock[0].timestamp()))
    client = app.test_client()
    login(client, 'test-password-long-enough', 'admin@example.test')
    with app.app_context():
        original = db.session.query(AdminLoginSession).one().expires_at
    for _ in range(2):
        clock[0] += timedelta(minutes=40)
        assert client.get('/admin').status_code == 200
    with app.app_context():
        assert db.session.query(AdminLoginSession).one().expires_at > original
    clock[0] += timedelta(minutes=61)
    assert client.get('/admin').location.endswith('/admin/login')


@pytest.fixture
def threaded_auth(tmp_path, monkeypatch):
    from app import create_app
    from app.extensions import db
    from app.models import AdminUser
    from werkzeug.security import generate_password_hash
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path/'auth.sqlite'))
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    monkeypatch.setenv('SECRET_KEY', 'isolated-logout-race')
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        db.session.add(AdminUser(email='admin@example.test', password_hash=generate_password_hash('test-password-long-enough'), installation_admin=True))
        db.session.commit()
    return application


def test_inflight_response_cannot_recreate_revoked_login_or_replace_new_cookie(threaded_auth):
    from threading import Event
    from concurrent.futures import ThreadPoolExecutor
    from app.services.admin_auth import admin_required
    from app import create_app
    from app.extensions import db
    from app.models import AdminLoginSession
    app = threaded_auth
    entered, release = Event(), Event()
    @app.get('/held-authenticated-response')
    @admin_required
    def held_response():
        entered.set()
        assert release.wait(10)
        return 'Request began before logout'
    client = app.test_client()
    login(client, 'test-password-long-enough', 'admin@example.test')
    name = app.config['SESSION_COOKIE_NAME']
    old = client.get_cookie(name).value
    with client.session_transaction() as state:
        csrf = state['logout_csrf']
    def request_in_flight():
        other = app.test_client(); other.set_cookie(name, old)
        return other.get('/held-authenticated-response')
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(request_in_flight)
        try:
            assert entered.wait(10)
            assert client.post('/admin/logout', data={'csrf': csrf}).status_code == 302
            assert login(client, 'test-password-long-enough', 'admin@example.test').status_code == 302
            fresh = client.get_cookie(name).value
        finally:
            release.set()
        delayed = future.result(timeout=10)
    assert delayed.status_code == 200  # Work authorized before logout may finish.
    assert 'Set-Cookie' not in delayed.headers
    assert 'Cookie' in delayed.vary
    assert client.get_cookie(name).value == fresh
    assert client.get('/admin/software').status_code == 200
    restarted = create_app('testing')
    restored = restarted.test_client()
    restored.set_cookie(name, old)
    assert restored.get('/admin/software').location.endswith('/admin/login')
    restored.set_cookie(name, fresh)
    assert restored.get('/admin/software').status_code == 200
    with restarted.app_context():
        assert db.session.query(AdminLoginSession).count() == 1


def test_cookie_finalization_does_not_commit_unsaved_view_work(app):
    from app.extensions import db
    from app.models import AdminUser
    from app.services.admin_auth import admin_required
    @app.get('/unsaved-profile-draft')
    @admin_required
    def draft():
        user = db.session.query(AdminUser).one()
        user.email = 'must-not-be-saved@example.test'
        db.session.flush()
        return 'Preview only'
    client = app.test_client()
    login(client, 'test-password-long-enough', 'admin@example.test')
    assert client.get('/unsaved-profile-draft').status_code == 200
    with app.app_context():
        assert db.session.query(AdminUser).one().email == 'admin@example.test'


def test_replayed_revoked_cookie_becomes_usable_anonymous_player_session(app):
    client = app.test_client()
    login(client, 'test-password-long-enough', 'admin@example.test')
    name = app.config['SESSION_COOKIE_NAME']
    old = client.get_cookie(name).value
    with client.session_transaction() as state:
        csrf = state['logout_csrf']
    client.post('/admin/logout', data={'csrf': csrf})
    client.set_cookie(name, old)
    response = client.get('/api/stations/test-station/presence')
    assert response.status_code == 200 and response.json.get('csrf')
    assert not response.json.get('ignored')
    with client.session_transaction() as state:
        assert 'admin_user_id' not in state
        assert state['stats_csrf'] == response.json['csrf']
    assert client.post('/api/stations/test-station/presence', json={},
        headers={'X-Presence-CSRF':response.json['csrf']}).status_code == 204
    assert client.get('/admin').location.endswith('/admin/login')
