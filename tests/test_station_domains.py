from datetime import datetime, timezone
from types import SimpleNamespace

import dns.exception
import dns.resolver
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Station, StationDomain, AuditEvent
from app.services import station_domains as domains
from tests.test_web import app as base_app, admin_client


@pytest.fixture
def app(base_app):
    base_app.config.update(FREO_DOMAIN_TARGET_HOST='', FREO_DOMAIN_TARGET_IPS='',
                           FREO_INSTALLATION_HOSTS='', PUBLIC_BASE_URL='', FREO_DOMAIN='')
    return base_app

BASE = '/admin/stations/test-station/domains/'
CSRF = {'csrf': 'test-admin-csrf-token'}


def add(app, hostname='rock.example.test', slug='test-station', verified=False):
    with app.app_context():
        row = domains.add_domain(Station.query.filter_by(slug=slug).one(), hostname)
        if verified:
            row.enabled = True
            row.verified_at = datetime.now(timezone.utc)
        db.session.commit()
        return row.id


@pytest.mark.parametrize('raw,expected', [('ROCK.Example.COM:443', 'rock.example.com'), ('rock.example.com.', 'rock.example.com'), ('xn--bcher-kva.example', 'xn--bcher-kva.example')])
def test_normalization(raw, expected):
    assert domains.normalize_hostname(raw, domain=True) == expected


@pytest.mark.parametrize('raw', ['', 'https://rock.com', 'a.com/path', 'user@a.com', 'a.com,evil.com', ' a.com', 'a.com\n', 'a..com', '-a.com', 'a-.com', '*.com', 'a_b.com', 'a.com:0', 'a.com:65536', 'a.com:no', 'a.com:80:90', '127.0.0.1', '[::1]', 'localhost', 'é.com', 'a'*64+'.com'])
def test_malformed(raw):
    with pytest.raises(ValueError):
        domains.normalize_hostname(raw, domain=True)


def test_routing_and_existing_urls(app):
    add(app, verified=True)
    add(app, 'other.example.test', slug='second-station', verified=True)
    add(app, 'alt.example.test', verified=True)
    add(app, 'pending.example.test')
    client = app.test_client()
    for host, name in [('rock.example.test', 'Test Station'), ('other.example.test', 'Second Station'), ('alt.example.test', 'Test Station'), ('ROCK.EXAMPLE.TEST:443', 'Test Station')]:
        response = client.get('/', headers={'Host': host})
        assert response.status_code == 200 and name in response.text and 'player-shell' in response.text
    for host in ['unknown.example.test', 'pending.example.test']:
        for path in ['/', '/stations', '/player/test-station', '/station-assets/test-station/logo.png', '/listen/test-station']:
            assert client.get(path, headers={'Host': host}).status_code == 404
    assert client.get('/', headers={'Host': 'bad,host'}).status_code == 400
    assert client.get('/', headers={'Host': 'unknown.example.test', 'X-Forwarded-Host': 'rock.example.test'}).status_code == 404
    assert client.get('/', headers={'Host': 'rock.example.test', 'X-Forwarded-Host': 'other.example.test'}).text.find('data-station="test-station"') >= 0
    assert client.get('/player/second-station', headers={'Host': 'rock.example.test'}).status_code == 404
    assert client.get('/listen/second-station', headers={'Host': 'rock.example.test'}).status_code == 404
    assert client.get('/station-assets/second-station/logo.png', headers={'Host': 'rock.example.test'}).status_code == 404
    assert client.get('/player/test-station', headers={'Host': 'rock.example.test'}).status_code == 200
    assert client.get('/stations', headers={'Host': 'rock.example.test'}).text.find('data-station="test-station"') >= 0
    assert client.get('/').status_code == 200
    assert client.get('/player/test-station').status_code == 200
    assert client.get('/listen/test-station').status_code == 307
    # API semantics are independent of domain resolution, as before.
    assert client.get('/api/stations/second-station', headers={'Host': 'rock.example.test'}).status_code == 200
    with app.app_context():
        station = Station.query.filter_by(slug='test-station').one()
        station.public_slug = 'new-name'
        db.session.commit()
    assert client.get('/player/new-name').status_code == 200
    assert client.get('/player/test-station').status_code == 200
    assert client.get('/player/new-name', headers={'Host': 'rock.example.test'}).status_code == 200


@pytest.mark.parametrize('field,value', [('enabled', False), ('deleted_at', datetime.now(timezone.utc)), ('lifecycle_state', 'pending_delete'), ('lifecycle_state', 'delete_failed')])
def test_unavailable_station(app, field, value):
    add(app, verified=True)
    with app.app_context():
        setattr(Station.query.filter_by(slug='test-station').one(), field, value)
        db.session.commit()
    assert app.test_client().get('/', headers={'Host': 'rock.example.test'}).status_code == 404


def test_authorization_duplicates_primary_and_removal(app):
    client = admin_client(app)
    assert app.test_client().post(BASE+'add', data=dict(CSRF, hostname='rock.example.test')).status_code == 302
    assert client.post(BASE+'add', data={'hostname': 'rock.example.test'}).status_code == 400
    assert client.post(BASE+'add', data=dict(CSRF, hostname='ROCK.example.test:443')).status_code == 303
    assert 'already claimed' in client.post(BASE+'add', data=dict(CSRF, hostname='rock.example.test.'), follow_redirects=True).text
    with app.app_context():
        first = StationDomain.query.one().id
    second = add(app, 'alt.example.test', verified=True)
    foreign = add(app, 'foreign.example.test', slug='second-station', verified=True)
    for action in ['primary', 'verify', 'remove']:
        assert client.post(BASE+action, data=dict(CSRF, domain_id=foreign)).status_code == 404
    assert 'Verify this domain' in client.post(BASE+'primary', data=dict(CSRF, domain_id=first), follow_redirects=True).text
    client.post(BASE+'primary', data=dict(CSRF, domain_id=second))
    third = add(app, 'third.example.test', verified=True)
    client.post(BASE+'primary', data=dict(CSRF, domain_id=third))
    with app.app_context():
        assert StationDomain.query.filter_by(is_primary=True).one().id == third
        assert domains.preferred_url(Station.query.filter_by(slug='test-station').one()) == 'https://third.example.test/'
        assert AuditEvent.query.filter_by(action='station_domain_primary').count() == 2
    assert 'https://third.example.test/' in client.get('/admin/stations/test-station/settings').text
    client.post(BASE+'remove', data=dict(CSRF, domain_id=third))
    assert client.get('/', headers={'Host': 'third.example.test'}).status_code == 404
    with app.app_context():
        assert not StationDomain.query.filter_by(is_primary=True).count()
        with app.test_request_context():
            assert domains.preferred_url(Station.query.filter_by(slug='test-station').one()).endswith('/player/test-station')
    # Inactive administrators cannot mutate; active admins are global in Freo today.
    with app.app_context():
        from app.models import AdminUser
        AdminUser.query.one().active = False
        db.session.commit()
    assert client.post(BASE+'remove', data=dict(CSRF, domain_id=second)).status_code == 302


def test_database_guards(app):
    first = add(app, verified=True)
    second = add(app, 'alt.example.test', verified=True)
    with app.app_context():
        db.session.get(StationDomain, first).is_primary = True
        db.session.commit()
        db.session.get(StationDomain, second).is_primary = True
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        db.session.get(StationDomain, second).hostname = 'ROCK.EXAMPLE.TEST'
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        row = db.session.get(StationDomain, second)
        row.verified_at = None
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_installation_hosts_reserved(app):
    app.config['FREO_INSTALLATION_HOSTS'] = 'freo.example.test,192.0.2.1,[2001:db8::1]'
    with app.app_context():
        with pytest.raises(ValueError, match='installation hostname'):
            domains.add_domain(Station.query.first(), 'FREO.example.test:443')
    for host in ['freo.example.test', '192.0.2.1', '[2001:db8::1]:8000']:
        assert app.test_client().get('/', headers={'Host': host}).status_code == 200


def test_verification(app, monkeypatch):
    identity = add(app)
    app.config['FREO_DOMAIN_TARGET_IPS'] = '192.0.2.10,2001:db8::10'
    client = admin_client(app)
    with app.app_context():
        token = db.session.get(StationDomain, identity).verification_token
    answers = {'A': [SimpleNamespace(address='192.0.2.10')], 'AAAA': [SimpleNamespace(address='2001:db8::10')], 'TXT': [SimpleNamespace(strings=[b'freo-verification=', token.encode()])]}
    monkeypatch.setattr(domains, 'dns_records', lambda host, kind: answers[kind])
    assert 'verified and enabled' in client.post(BASE+'verify', data=dict(CSRF, domain_id=identity), follow_redirects=True).text
    with app.app_context():
        row = db.session.get(StationDomain, identity)
        assert row.enabled and row.verified_at
    assert client.get('/', headers={'Host': 'rock.example.test'}).status_code == 200
    for kind, values, message in [('A', [SimpleNamespace(address='192.0.2.99')], 'All A/AAAA'), ('TXT', [SimpleNamespace(strings=[b'wrong-station-token'])], 'TXT record')]:
        saved = answers[kind]; answers[kind] = values
        other = add(app, kind.lower()+'.example.test')
        assert message in client.post(BASE+'verify', data=dict(CSRF, domain_id=other), follow_redirects=True).text
        with app.app_context():
            assert not db.session.get(StationDomain, other).enabled
        answers[kind] = saved
    app.config['FREO_DOMAIN_TARGET_IPS'] = ''
    assert 'configure domain verification targets' in client.post(BASE+'verify', data=dict(CSRF, domain_id=identity), follow_redirects=True).text


def test_dns_timeout_and_absolute_queries(monkeypatch):
    def resolver(name, kind, **kwargs):
        assert name == 'rock.example.test.' and kwargs == {'lifetime': 3, 'search': False}
        raise dns.exception.Timeout()
    monkeypatch.setattr(dns.resolver, 'resolve', resolver)
    with pytest.raises(ValueError, match='timed out'):
        domains.dns_records('rock.example.test', 'A')


def test_dns_target_hostname_empty_answers_and_lookup_failure(app, monkeypatch):
    identity = add(app)
    app.config.update(FREO_DOMAIN_TARGET_HOST='server.example.test', FREO_DOMAIN_TARGET_IPS='')
    with app.app_context():
        token = db.session.get(StationDomain, identity).verification_token
    calls = []
    def records(host, kind):
        calls.append((host, kind))
        if kind == 'TXT':
            return [SimpleNamespace(strings=[('freo-verification='+token).encode()])]
        return [SimpleNamespace(address='192.0.2.1')] if kind == 'A' else []
    monkeypatch.setattr(domains, 'dns_records', records)
    client = admin_client(app)
    assert 'verified and enabled' in client.post(BASE+'verify', data=dict(CSRF, domain_id=identity), follow_redirects=True).text
    assert ('server.example.test', 'A') in calls
    assert ('_freo-verification.rock.example.test', 'TXT') in calls
    second = add(app, 'missing.example.test')
    def failure(host, kind):
        raise ValueError('DNS lookup failed or timed out')
    monkeypatch.setattr(domains, 'dns_records', failure)
    assert 'timed out' in client.post(BASE+'verify', data=dict(CSRF, domain_id=second), follow_redirects=True).text
    with app.app_context():
        assert not db.session.get(StationDomain, second).enabled
    app.config.update(FREO_DOMAIN_TARGET_HOST='', FREO_DOMAIN_TARGET_IPS='192.0.2.1')
    monkeypatch.setattr(domains, 'dns_records', lambda host, kind: [])
    assert 'All A/AAAA' in client.post(BASE+'verify', data=dict(CSRF, domain_id=second), follow_redirects=True).text


def test_disabled_domain_and_schema_primary_requires_enabled(app):
    identity = add(app, verified=True)
    with app.app_context():
        row = db.session.get(StationDomain, identity)
        row.enabled = False
        db.session.commit()
        row.is_primary = True
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
    assert app.test_client().get('/', headers={'Host': 'rock.example.test'}).status_code == 404


@pytest.mark.parametrize('identity', ['', 'abc', '-1', '9'*100])
def test_invalid_domain_identifier(app, identity):
    assert admin_client(app).post(BASE+'remove', data=dict(CSRF, domain_id=identity)).status_code == 404
