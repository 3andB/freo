import os

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app
from app.extensions import db


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("SECRET_KEY", "test-only")
    return create_app("testing")


@pytest.mark.parametrize('path', ['/', '/admin/login'])
@pytest.mark.parametrize('existing_session', [False, True])
def test_factory_and_health(app, path, existing_session):
    client = app.test_client()
    if existing_session:
        with client.session_transaction() as state:
            state['admin_user_id'] = 1
    response = client.get(path)
    assert response.status_code == 503  # A missing schema is not an empty installation.
    assert response.json == {'status': 'unavailable'}
    client.delete_cookie(app.config['SESSION_COOKIE_NAME'])
    assert client.get("/health").json == {"status": "ok"}


def test_ready_success(app):
    assert app.test_client().get("/ready").json == {"status": "ok"}


def test_ready_database_failure(app, monkeypatch):
    def fail(_query):
        raise OperationalError("SELECT 1", {}, Exception("offline"))
    monkeypatch.setattr(db.session, "execute", fail)
    response = app.test_client().get("/ready")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable"}
    assert "offline" not in response.get_data(as_text=True)


def test_production_requires_secrets(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FREO_ENV_FILE", os.devnull)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")
