"""First-use credentials, durable setup, cookie policy and stale-session rejection."""
import pytest
from tests.test_web import app, admin_client
from app.extensions import db
from app.models import AdminUser, AdminBootstrap, InstallationSettings
from app.services.admin_setup import bootstrap, DEFAULT_PASSWORD
from werkzeug.security import check_password_hash


def fresh(app):
    with app.app_context():
        db.drop_all(); db.create_all()
        assert bootstrap()
        return AdminUser.query.one().id


def login(client, password=DEFAULT_PASSWORD, identity='admin'):
    response = client.get('/admin/login')
    with client.session_transaction() as state: token=state['login_csrf']
    return client.post('/admin/login', data={'email':identity,'password':password,'csrf':token})


def test_bootstrap_is_once_only_and_does_not_replace_existing_accounts(app):
    with app.app_context():
        old=AdminUser.query.one().password_hash
        assert not bootstrap()
        assert AdminUser.query.one().password_hash == old
        assert AdminUser.query.one().username is None
        assert db.session.get(AdminBootstrap,1)
        AdminUser.query.delete(); db.session.commit()
        assert not bootstrap() and AdminUser.query.count() == 0


def test_setup_gate_validation_completion_and_stale_session_rejection(app):
    fresh(app)
    from app.services.admin_auth import admin_required
    app.add_url_rule('/protected-outside-admin', 'protected_fixture', admin_required(lambda: 'must not run'))
    owner=app.test_client(); stale=app.test_client()
    assert login(owner).location.endswith('/admin/setup')
    assert login(stale).location.endswith('/admin/setup')
    assert owner.get('/admin').location.endswith('/admin/setup')
    assert owner.get('/protected-outside-admin').location.endswith('/admin/setup')
    assert owner.post('/admin/software/license').location.endswith('/admin/setup')
    assert owner.post('/admin/setup').status_code == 400
    with owner.session_transaction() as state: csrf=state['admin_csrf']
    data={'csrf':csrf,'email':'owner@example.test','password':'short','confirmation':'short'}
    assert owner.post('/admin/setup',data=data).status_code == 400
    password='a new private fixture passphrase'
    data.update(password=password,confirmation=password)
    assert owner.post('/admin/setup',data=data).location.endswith('/admin')
    assert owner.get('/admin/software').status_code == 200
    assert stale.get('/admin').location.endswith('/admin/login')
    assert stale.post('/admin/setup',data=data).location.endswith('/admin/login')
    assert login(app.test_client()).status_code == 401
    assert login(app.test_client(),password).location.endswith('/admin')
    assert login(app.test_client(),password,'owner@example.test').location.endswith('/admin')
    with app.app_context():
        user=AdminUser.query.one()
        assert not user.setup_required and user.installation_admin
        assert user.username == 'admin' and check_password_hash(user.password_hash,password)
        before=user.password_hash
        assert not bootstrap()
        assert user.password_hash == before


@pytest.mark.parametrize('scheme,secure',[('http',False),('https',True)])
def test_cookie_scheme_uses_saved_origin_not_client_headers(app,scheme,secure):
    app.config['SESSION_COOKIE_SECURE']=True  # Same default as production.
    with app.app_context():
        from app.services.installation_settings import import_environment
        app.config['PUBLIC_BASE_URL']=scheme+'://radio.example.test'
        import_environment()
    response=app.test_client().get('/admin/login',headers={'X-Forwarded-Proto':'http' if secure else 'https'})
    cookie=response.headers['Set-Cookie']
    assert ('; Secure;' in cookie) is secure
    assert '; HttpOnly;' in cookie and 'SameSite=Lax' in cookie
