"""Public API authority, safe read models and browser credential lifecycle."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import re
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.extensions import db
from app import models as m
from app.services import public_api as service
from tests.test_web import app, admin_client
from tests.test_phase3_dj import dj_client

ROOT = '/api/v1/stations'
STATION = ROOT + '/test-station'
ADMIN = '/admin/api-credentials'
CSRF = 'test-admin-csrf-token'
UUID = '00000000-0000-4000-8000-000000000001'
SUFFIXES = ['', '/now-playing', '/schedule', '/listeners', '/library/tracks', '/library/tracks/' + UUID]


def issue(app, slugs=('test-station',)):
    with app.app_context():
        ids = [s.id for s in m.Station.query.filter(m.Station.slug.in_(slugs))]
        row, token = service.create_credential(m.AdminUser.query.first(), 'Test integration', ids)
        db.session.commit()
        return row.id, token


def headers(token):
    return {'Authorization': 'Bearer ' + token}


def test_create_once_revoke_and_audit(app):
    client = admin_client(app)
    assert client.get(ADMIN).status_code == 200
    assert client.post(ADMIN, data={'name': 'test', 'stations': '1'}).status_code == 400
    response = client.post(ADMIN, data={'csrf': CSRF, 'name': '<Integration>', 'stations': '1'})
    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    assert '&lt;Integration&gt;' in response.text
    token = re.search(r'freo_v1_[0-9a-f]{32}\.[A-Za-z0-9_-]{43}', response.text)[0]
    with client.session_transaction() as cookie:
        assert token not in repr(dict(cookie))
    with app.app_context():
        row = m.ApiCredential.query.one()
        identifier = row.id
        assert row.token_digest == hashlib.sha256(token.encode()).hexdigest()
        assert row.scope == 'read' and len(row.grants) == 1
        assert token not in repr(db.session.execute(sa.select(m.ApiCredential.__table__)).all())
        assert token not in repr([(e.summary, e.target_id) for e in m.AuditEvent.query.all()])
    assert token not in client.get(ADMIN).text
    assert app.test_client().get(ROOT, headers=headers(token)).status_code == 200
    revoke = f'{ADMIN}/{identifier}/revoke'
    assert client.get(revoke).status_code == 405
    assert client.post(revoke).status_code == 400
    assert client.post(revoke, data={'csrf': CSRF}).status_code == 302
    assert client.post(revoke, data={'csrf': CSRF}).status_code == 302
    assert token not in client.get(ADMIN).text
    assert app.test_client().get(ROOT, headers=headers(token)).status_code == 401
    with app.app_context():
        assert m.AuditEvent.query.filter_by(action='api_credential_created').count() == 1
        assert m.AuditEvent.query.filter_by(action='api_credential_revoked').count() == 1


@pytest.mark.parametrize('form', [dict(stations=[]), dict(stations=['999']), dict(stations=['bad']),
    dict(scope='write'), dict(scope='read write'), dict(name=''), dict(name='x' * 121)])
def test_creation_validation(app, form):
    client = admin_client(app)
    data = dict(csrf=CSRF, name='Integration', stations=['1'], scope='read')
    data.update(form)
    assert client.post(ADMIN, data=data).status_code == 400
    with app.app_context():
        assert m.ApiCredential.query.count() == 0


def test_credential_management_permissions(app, dj_client):
    identifier, token = issue(app)
    for client, code in [(app.test_client(), 302), (dj_client, 403)]:
        assert client.get(ADMIN).status_code == code
        assert client.post(ADMIN, data={'csrf': 'dj-csrf', 'name': 'bad', 'stations': '1'}).status_code == code
        assert client.post(f'{ADMIN}/{identifier}/revoke', data={'csrf': 'dj-csrf'}).status_code == code
    assert app.test_client().post(ADMIN, headers=headers(token)).status_code == 302


@pytest.mark.parametrize('change', ['inactive', 'dj', 'setup', 'missing'])
def test_creator_authority_is_checked_each_request(app, change):
    identifier, token = issue(app)
    with app.app_context():
        user = m.AdminUser.query.first()
        if change == 'inactive': user.active = False
        elif change == 'dj': user.role = 'DJ'
        elif change == 'setup': user.setup_required = True
        else: db.session.get(m.ApiCredential, identifier).created_by = None
        db.session.commit()
    assert app.test_client().get(ROOT, headers=headers(token)).status_code == 401


def test_bearer_only_authentication_and_json_errors(app):
    _, token = issue(app)
    client = admin_client(app)
    for supplied in ('', 'Basic ' + token, 'Bearer bad', 'Bearer ' + token + 'x',
                     'Bearer ' + token[:-1] + ('A' if token[-1] != 'A' else 'B')):
        response = client.get(ROOT, headers={'Authorization': supplied})
        assert response.status_code == 401
        assert response.json['error']['code'] == 'unauthorized'
        assert response.headers['WWW-Authenticate'].startswith('Bearer')
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'Location' not in response.headers
    assert client.get(ROOT + '?token=' + token).status_code == 401
    assert client.post(ROOT, json={'token': token}).status_code == 401
    assert client.get(ROOT, headers={'Authorization': 'bearer ' + token}).status_code == 200
    options = client.options(ROOT, headers=headers(token))
    assert options.status_code == 200 and options.json == {'data': None}
    assert 'GET' in options.headers['Allow']
    head = client.head(ROOT, headers=headers(token))
    assert head.status_code == 200 and head.is_json and head.data == b''
    for path, method, code in [('/api/v1/missing', 'get', 404), ('/api/v1', 'get', 404),
                               (ROOT, 'post', 405), (STATION, 'delete', 405)]:
        response = getattr(client, method)(path, headers=headers(token))
        assert response.status_code == code and response.is_json
        assert set(response.json) == {'error'}
        assert response.headers['Cache-Control'] == 'no-store'
        if code == 405: assert 'GET' in response.headers['Allow']
    assert client.get('/api/v10/missing').status_code == 404
    assert not client.get('/api/v10/missing').is_json


@pytest.mark.parametrize('suffix', SUFFIXES)
def test_every_station_endpoint_enforces_grants(app, suffix):
    _, token = issue(app)
    client = app.test_client()
    assert client.get(STATION + suffix, headers=headers(token)).status_code == 200
    assert client.get(ROOT + '/second-station' + suffix, headers=headers(token)).status_code == 403
    assert client.get(ROOT + '/unknown' + suffix, headers=headers(token)).status_code == 404
    with app.app_context():
        station = m.Station.query.filter_by(slug='test-station').one()
        station.lifecycle_state = 'pending_delete'
        db.session.commit()
    assert client.get(STATION + suffix, headers=headers(token)).status_code == 404


def test_station_list_selection_pagination_and_future_stations(app):
    _, token = issue(app, ('test-station', 'second-station'))
    client = app.test_client()
    with app.app_context():
        db.session.add(m.Station(name='Future', slug='future'))
        db.session.commit()
    response = client.get(ROOT + '?per_page=1', headers=headers(token)).json
    assert response['meta'] == dict(page=1, per_page=1, total=2)
    assert response['data'][0]['slug'] == 'second-station'
    page2 = client.get(ROOT + '?per_page=1&page=2', headers=headers(token)).json
    assert page2['data'][0]['slug'] == 'test-station'
    assert client.get(ROOT + '?page=3&per_page=1', headers=headers(token)).json['data'] == []
    assert client.get(ROOT + '/future', headers=headers(token)).status_code == 403
    assert set(page2['data'][0]) == {'id', 'slug', 'name', 'description', 'timezone'}
    with app.app_context():
        m.Station.query.filter_by(slug='test-station').one().deleted_at = datetime.now(timezone.utc)
        db.session.commit()
    assert client.get(ROOT, headers=headers(token)).json['meta']['total'] == 1


@pytest.mark.parametrize('suffix', ['?page=0', '?per_page=101', '?page=x', '?page=-1', '?per_page=0',
    '?page=1&page=2', '?page=999999999999999999999999999999', '?page=１', '?unknown=1'])
def test_pagination_validation(app, suffix):
    _, token = issue(app)
    assert app.test_client().get(ROOT + suffix, headers=headers(token)).status_code == 400


def test_library_safe_fields_search_and_shared_access(app):
    _, token = issue(app, ('test-station', 'second-station'))
    client = app.test_client()
    path = STATION + '/library/tracks'
    response = client.get(path, headers=headers(token)).json
    track = response['data'][0]
    assert set(track) == {'uuid', 'freo_track_id', 'title', 'artist', 'album', 'genre', 'release_year', 'isrc', 'duration_ms'}
    assert track['uuid'] == UUID
    assert client.get(path + '/' + UUID, headers=headers(token)).json['data'] == track
    assert client.get(path + '?q=TEST', headers=headers(token)).json['meta']['total'] == 1
    assert client.get(path + '?q=%25', headers=headers(token)).json['data'] == []
    assert client.get(path + '?q=' + 'x' * 101, headers=headers(token)).status_code == 400
    other = ROOT + '/second-station/library/tracks/' + UUID
    assert client.get(other, headers=headers(token)).status_code == 404
    with app.app_context():
        m.Track.query.one().available_to_all = True
        db.session.commit()
    assert client.get(other, headers=headers(token)).json['data'] == track
    with app.app_context():
        m.Track.query.one().available_to_all = False
        artist = m.Artist(station_id=1, name='Shared artist', normalized_name='shared artist', available_to_all=True)
        m.Track.query.one().catalog_artist = artist
        db.session.commit()
    assert client.get(other, headers=headers(token)).status_code == 200
    with app.app_context():
        m.Track.query.one().catalog_artist.available_to_all = False
        db.session.commit()
    assert client.get(other, headers=headers(token)).status_code == 404


@pytest.mark.parametrize('field,value', [('enabled', False), ('ingest_status', 'rejected'),
    ('deleted_at', datetime.now(timezone.utc)), ('decommissioned_at', datetime.now(timezone.utc)),
    ('audio_kind', 'STATION'), ('audio_kind', 'COMMERCIALS')])
def test_library_unavailable_tracks_are_not_exposed(app, field, value):
    _, token = issue(app)
    with app.app_context():
        setattr(m.Track.query.one(), field, value)
        db.session.commit()
    client = app.test_client()
    assert client.get(STATION + '/library/tracks', headers=headers(token)).json['data'] == []
    assert client.get(STATION + '/library/tracks/' + UUID, headers=headers(token)).status_code == 404


@pytest.mark.parametrize('mode', ['AUTO', 'DJ_BOOTH'])
def test_now_playing_fresh_and_stale_observations(app, mode):
    _, token = issue(app)
    client = app.test_client()
    assert client.get(STATION + '/now-playing', headers=headers(token)).json['data']['current'] == []
    with app.app_context():
        decision = m.SelectionDecision.query.one()
        now = datetime.now(timezone.utc)
        snapshot = m.LiveQueueSnapshot(station_id=decision.station_id, current_decision_id=decision.id,
            queued_decision_ids=[], unknown_count=0, observed_at=now, broadcast_observed_at=now,
            broadcast_online=True, listeners=12,
            mixer=dict(mode=mode, a_id=decision.id, a_playing=True, b_playing=False))
        db.session.add(snapshot)
        db.session.commit()
    response = client.get(STATION + '/now-playing', headers=headers(token)).json['data']
    assert response['fresh'] and response['stream_online'] and response['mode'] == mode
    assert response['observed_at'].endswith('+00:00')
    assert set(response) == {'current', 'program', 'mode', 'fresh', 'observed_at', 'stream_online', 'timezone'}
    assert set(response['current'][0]) == {'track', 'freo_track_id', 'title', 'artist', 'started_at'}
    assert response['current'][0]['track'] == UUID
    if mode == 'DJ_BOOTH': assert response['program'] == 'Live DJ'
    with app.app_context():
        snapshot = m.LiveQueueSnapshot.query.one()
        snapshot.observed_at = snapshot.broadcast_observed_at = now - timedelta(minutes=5)
        db.session.commit()
    response = client.get(STATION + '/now-playing', headers=headers(token)).json['data']
    assert response['current'] == [] and not response['fresh'] and response['stream_online'] is None


def test_listener_aggregates_no_network_or_private_data(app, monkeypatch):
    _, token = issue(app)
    monkeypatch.setattr('app.services.broadcast_status.observation', lambda *a: pytest.fail('No network polling'))
    client = app.test_client()
    data = client.get(STATION + '/listeners', headers=headers(token)).json['data']
    assert data['current'] is None and not data['fresh'] and data['summary']['coverage'] == 0
    with app.app_context():
        now = int(datetime.now(timezone.utc).timestamp())
        db.session.add(m.StatsState(scope=1, data=dict(at=now, listeners=9, online=True, private_secret='HIDDEN')))
        db.session.add(m.StatsState(scope=2, data=dict(at=now, listeners=999, online=True)))
        db.session.add(m.StatsBucket(scope=1, resolution='minute', at=now // 60 * 60 - 60,
            observed_seconds=60, listener_seconds=540, online_seconds=60, peak=9))
        db.session.add(m.StatsBucket(scope=2, resolution='minute', at=now // 60 * 60 - 60,
            observed_seconds=60, listener_seconds=59940, online_seconds=60, peak=999))
        db.session.commit()
    response = client.get(STATION + '/listeners', headers=headers(token))
    assert response.json['data']['current'] == 9
    assert response.json['data']['summary']['average'] == 9
    assert response.json['data']['summary']['peak'] == 9
    assert response.json['data']['summary']['listener_hours'] == .15
    assert 'HIDDEN' not in response.text and '999' not in response.text
    for period in ('7d', '30d'):
        assert client.get(STATION + '/listeners?range=' + period, headers=headers(token)).status_code == 200
    assert client.get(STATION + '/listeners?range=365d', headers=headers(token)).status_code == 400
    with app.app_context():
        db.session.get(m.StatsState, 1).data = dict(at=now - 46, listeners=9, online=True)
        db.session.commit()
    assert client.get(STATION + '/listeners', headers=headers(token)).json['data']['current'] is None


def test_schedule_defaults_validation_and_no_publication(app):
    _, token = issue(app)
    client = app.test_client()
    response = client.get(STATION + '/schedule?per_page=1', headers=headers(token)).json
    assert response['meta']['days'] == 7 and response['meta']['timezone'] == 'UTC'
    assert set(response['data'][0]) == {'start', 'end', 'title', 'source'}
    assert response['data'][0]['title'] == 'Power'
    assert datetime.fromisoformat(response['data'][0]['end']) > datetime.now(timezone.utc)
    for days in ('0', '8', 'bad'):
        assert client.get(STATION + '/schedule?days=' + days, headers=headers(token)).status_code == 400
    with app.app_context():
        assert m.PublicScheduleRevision.query.count() == 0
        assert m.SelectionDecision.query.count() == 1


def test_unexpected_error_is_sanitized_and_legacy_errors_unchanged(app, monkeypatch):
    _, token = issue(app)
    def broken(*args): raise RuntimeError('private path /private/secret')
    monkeypatch.setattr('app.services.player.now_playing', broken)
    response = app.test_client().get(STATION + '/now-playing', headers=headers(token))
    assert response.status_code == 500 and response.json['error']['code'] == 'internal_error'
    assert '/private/secret' not in response.text
    assert app.test_client().post('/api/stations').status_code == 405
    assert app.test_client().get('/api/stations').status_code == 200


def test_rate_limits_headers_reset_and_network_hashes(app, monkeypatch):
    _, token = issue(app)
    monkeypatch.setattr(service.time, 'time', lambda: 6000)
    client = app.test_client()
    with app.app_context():
        for _ in range(119): assert service.rate_limit('credential', token[8:40], 120)[0]
    assert client.get(ROOT, headers=headers(token)).status_code == 200
    response = client.get(ROOT, headers=headers(token))
    assert response.status_code == 429 and response.headers['Retry-After'] == '60'
    monkeypatch.setattr(service.time, 'time', lambda: 6060)
    assert client.get(ROOT, headers=headers(token)).status_code == 200
    with app.app_context(), app.test_request_context('/', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
        key = service.network_key()
        for _ in range(299): service.rate_limit('network', key, 300)
        assert len(key) == 64 and '127.0.0.1' not in key
    response = client.get(ROOT)
    assert response.status_code == 429
    with app.app_context():
        assert service.rate_limit('network', 'old', 1, now=0)[0]
        service.rate_limit('network', 'new', 1, now=60 * 1442)
        assert not m.ApiRateBucket.query.filter_by(key='old').count()


def test_proxy_headers_are_only_trusted_from_configured_peers(app):
    with app.test_request_context('/', headers={'X-Real-IP': '1.2.3.4'}, environ_base={'REMOTE_ADDR': '5.6.7.8'}):
        untrusted = service.network_key(100)
    with app.test_request_context('/', environ_base={'REMOTE_ADDR': '5.6.7.8'}):
        assert untrusted == service.network_key(100)
    app.config['DMCA_TRUSTED_PROXY_IPS'] = ('5.6.7.8',)
    with app.test_request_context('/', headers={'X-Real-IP': '1.2.3.4'}, environ_base={'REMOTE_ADDR': '5.6.7.8'}):
        trusted = service.network_key(100)
    with app.test_request_context('/', environ_base={'REMOTE_ADDR': '1.2.3.4'}):
        assert trusted == service.network_key(100)
        assert trusted != service.network_key(86400)


def test_phase6_sqlite_migration_roundtrip_preserves_existing_rows(app):
    spec = importlib.util.spec_from_file_location('phase6', 'migrations/versions/f606a1b2c3d4_public_api.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with app.app_context():
        with db.engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.downgrade()
            migration.upgrade()
        assert m.Station.query.count() == 2 and m.SelectionDecision.query.count() == 1
    _, token = issue(app)
    assert app.test_client().get(ROOT, headers=headers(token)).status_code == 200


@pytest.mark.parametrize('mode', ['SIMPLE', 'CALENDAR', 'BLOCKS'])
@pytest.mark.parametrize('day,hours', [('2026-03-08', 23), ('2026-11-01', 25)])
def test_schedule_modes_and_dst_use_existing_resolver(app, monkeypatch, mode, day, hours):
    from app.services import visual_schedule as vs
    from tests.test_visual_schedule import setup
    from app.routes import public_api as routes
    at = datetime.fromisoformat(day + 'T00:30:00').replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None): return at.astimezone(tz)
    monkeypatch.setattr(routes, 'datetime', FixedClock)
    _, token = issue(app)
    with app.app_context():
        station, policy, reference = setup()
        station.timezone = 'America/New_York'
        reference = vs.source(station, reference)
        policy.mode = mode
        policy.simple = policy.live_simple = reference
        rule = vs.clean_rule(dict(frequency='once', anchor=day))
        entry = dict(id='special', start=0, end=86400, rule=rule, source=reference)
        policy.calendar = [entry]
        policy.assignments = [dict(entry, pattern=[reference])]
        db.session.commit()
    response = app.test_client().get(STATION + '/schedule?days=1', headers=headers(token))
    assert response.status_code == 200
    entries = response.json['data']
    assert 'Verified Test Track' in entries[0]['title']
    assert entries[0]['source'] == mode.lower()
    begin = datetime.fromisoformat(entries[0]['start'])
    end = datetime.fromisoformat(entries[-1]['end'])
    assert (end - begin).total_seconds() == hours * 3600
    with app.app_context():
        assert m.PublicScheduleRevision.query.count() == 0
        assert m.ScheduleTransition.query.count() == 0


def test_settings_failure_keeps_api_error_contract(app, monkeypatch):
    from app.services.installation_settings import SettingsUnavailable
    _, token = issue(app)
    def broken(*args): raise SettingsUnavailable('private configuration')
    monkeypatch.setattr('app.services.player.now_playing', broken)
    response = app.test_client().get(STATION + '/now-playing', headers=headers(token))
    assert response.status_code == 503
    assert response.json == {'error': {'code': 'unavailable', 'message': 'The service is temporarily unavailable.'}}
