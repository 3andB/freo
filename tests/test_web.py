import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import AdminUser, Station, StreamMount


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///:memory:')
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    application = create_app('testing')
    with application.app_context():
        db.create_all()
        station = Station(name='Test Station', slug='test-station', description='Test stream')
        station.stream = StreamMount()
        db.session.add(station)
        db.session.add(AdminUser(email='admin@example.test', password_hash=generate_password_hash('test-password-long-enough')))
        db.session.commit()
    yield application


def test_public_pages_and_no_mutations(app):
    client = app.test_client()
    assert 'Put your station on the air.' in client.get('/').get_data(as_text=True)
    assert 'Test Station' in client.get('/stations').get_data(as_text=True)
    assert '/stream/test-station' in client.get('/player/test-station').get_data(as_text=True)
    assert client.post('/api/stations').status_code == 405
    assert client.post('/api/stations/test-station/start').status_code == 404
    assert client.get('/player/../etc/passwd').status_code == 404


def test_dashboard_requires_login_and_password_not_leaked(app):
    client = app.test_client()
    assert client.get('/dashboard/test-station').status_code == 302
    login_page = client.get('/admin/login')
    with client.session_transaction() as state:
        token = state['login_csrf']
    bad = client.post('/admin/login', data={'email':'admin@example.test','password':'wrong','csrf':token})
    assert bad.status_code == 401
    assert 'test-password-long-enough' not in bad.get_data(as_text=True)
    with client.session_transaction() as state:
        token = state['login_csrf']
    good = client.post('/admin/login', data={'email':'admin@example.test','password':'test-password-long-enough','csrf':token})
    assert good.status_code == 302
    page = client.get('/dashboard/test-station')
    assert page.status_code == 200
    assert 'READ-ONLY OPERATIONS' in page.get_data(as_text=True)
    assert 'test-password-long-enough' not in page.get_data(as_text=True)
    assert page.headers['Cache-Control'] == 'private, no-store'
    assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']


def test_login_csrf_and_client_lockout(app):
    client = app.test_client()
    assert client.post('/admin/login', data={'email':'admin@example.test','password':'anything'}).status_code == 400
    client.get('/admin/login')
    with client.session_transaction() as state:
        token = state['login_csrf']
    for _ in range(5):
        assert client.post('/admin/login', data={'email':'admin@example.test','password':'wrong','csrf':token}).status_code == 401
        with client.session_transaction() as state:
            token = state['login_csrf']
    assert client.post('/admin/login', data={'email':'admin@example.test','password':'test-password-long-enough','csrf':token}).status_code == 429
