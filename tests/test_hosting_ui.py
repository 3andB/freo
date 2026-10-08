"""Hosted interface follows assigned capacity; free installations see no hosting UI."""
from tests.test_web import app, admin_client
from freo_ops import hosting


def test_self_hosted_interface_is_unchanged(app, monkeypatch):
    monkeypatch.setattr(hosting, 'read', lambda: {'hosted': False})
    from app.extensions import db
    from app.models import AdminUser
    with app.app_context():
        AdminUser.query.first().installation_admin = True
        db.session.commit()
    client = admin_client(app)
    for path in ('/admin', '/admin/stations', '/admin/software', '/admin/installation'):
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200
        assert 'aria-label="Hosting usage"' not in response.text
        assert 'Media Storage —' not in response.text
    assert client.get('/hosting/status').status_code == 404


def test_hosted_interface_uses_assigned_capacity(app, monkeypatch):
    from app.services import hosting_web
    policy = dict(hosted=True, plan='pro', status='active', limits=dict(hosting.PLANS['pro']))
    monkeypatch.setattr(hosting, 'read', lambda: policy)
    monkeypatch.setattr(hosting_web, 'summary', lambda: dict(policy, stations_used=3, listeners_used=7,
        storage=dict(used_bytes=18_400_000_000, remaining_bytes=31_600_000_000, percent=36.8)))
    from app.extensions import db
    from app.models import AdminUser
    with app.app_context():
        AdminUser.query.first().installation_admin = True
        db.session.commit()
    client = admin_client(app)
    body = client.get('/admin/stations', follow_redirects=True).text
    assert '3 / 10 stations' in body
    assert 'name="name"' in body
    assert '3 of 10 Stations' in body
    assert '18.40 GB / 50 GB' in body
    for path in ('/admin', '/admin/software', '/admin/installation'):
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200
        assert 'Free · three stations per owner' not in response.text
        assert '$99' not in response.text
