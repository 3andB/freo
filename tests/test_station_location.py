"""Station location settings and the existing reporter's actual sync requests."""
import json
import time

import pytest
from app.extensions import db
from app.models import Station, CentralStationState
from app.routes.station_settings import settings_token
from app.services.central_api import Reporter, installation, digest, metadata
from app.services.station_location import coordinates, LOCATION_FIELDS
from app.version import VERSION
from tests.test_web import app, admin_client
from tests.test_central_api import central, TOKEN, INSTALLATION_ID
from tests.test_rc6_settings import combined
from tests.test_station_settings_flags import BASE


def location_form(client, **changes):
    payload = combined(client)
    payload.update(city='New York', region='NY', country='US', latitude='40.7128', longitude='-74.0060')
    payload.update(changes)
    return payload


def confirm(payload):
    return dict(payload, location_confirmation=json.dumps([payload.get(key, '') for key in LOCATION_FIELDS]))


def save(client, payload):
    return client.post(BASE, data=payload, headers={'Accept': 'application/json'})


def snapshot(app):
    with app.app_context():
        station = db.session.get(Station, 1)
        return (station.name, station.city, station.region, station.country,
                station.latitude, station.longitude, station.stream.pending_audio, settings_token(station))


@pytest.mark.parametrize('latitude,longitude,expected', [
    ('', '', (None, None)), (None, None, (None, None)), ('0', '0', (0, 0)),
    ('40.7128', '-74.006', (40.71, -74.01)), ('-1.235', '1.235', (-1.24, 1.24)),
    ('90', '180', (90, 180)), ('-90', '-180', (-90, -180)),
])
def test_coordinate_values(latitude, longitude, expected):
    assert coordinates(latitude, longitude) == expected


@pytest.mark.parametrize('latitude,longitude', [
    ('1', ''), ('', '1'), ('not-a-number', '0'), ('0', 'oops'),
    ('NaN', '0'), ('0', 'NaN'), ('Infinity', '0'), ('0', '-Infinity'),
    ('90.001', '0'), ('-90.001', '0'), ('0', '180.001'), ('0', '-180.001'),
    ('1e1000', '0'), ('0', '1e1000'),
])
def test_invalid_settings_leave_all_stored_values_unchanged(app, latitude, longitude):
    client = admin_client(app)
    before = snapshot(app)
    payload = location_form(client, latitude=latitude, longitude=longitude, bitrate='96')
    response = save(client, confirm(payload))
    assert response.status_code == 400
    assert snapshot(app) == before


def test_unchanged_place_save_preserves_pair_without_confirmation(app):
    client = admin_client(app)
    assert save(client, confirm(location_form(client))).status_code == 200
    before = snapshot(app)
    assert before[4:6] == (40.71, -74.01)
    # Use the normalized values reloaded by a new request, without consent.
    payload = location_form(client, latitude='40.71', longitude='-74.01')
    assert save(client, payload).status_code == 200
    # Old callers omitting coordinate inputs also preserve the stored pair.
    payload = location_form(client)
    del payload['latitude'], payload['longitude']
    assert save(client, payload).status_code == 200
    assert snapshot(app) == before
    assert 'value="40.71"' in client.get(BASE).text
    with app.app_context():
        assert db.session.get(Station, 2).latitude is None


@pytest.mark.parametrize('field,value', [('city', 'Albany'), ('region', 'New York'), ('country', 'CA')])
def test_changed_place_requires_confirmation_of_exact_new_values(app, field, value):
    client = admin_client(app)
    assert save(client, confirm(location_form(client))).status_code == 200
    before = snapshot(app)
    original = location_form(client)
    payload = confirm(original)
    payload[field] = value
    # Old confirmation cannot approve the new place, even with valid numbers.
    assert save(client, payload).status_code == 400
    assert snapshot(app) == before
    payload = confirm(payload)
    payload['longitude'] = '-73.75'
    assert save(client, payload).status_code == 400
    assert snapshot(app) == before
    # A different validation failure must not partially save a confirmed place.
    approved = confirm(payload)
    invalid = dict(approved, contact_email='broken', bitrate='96')
    assert save(client, invalid).status_code == 400
    assert snapshot(app) == before
    assert save(client, approved).status_code == 200
    with app.app_context():
        station = db.session.get(Station, 1)
        assert getattr(station, field) == value
        assert station.longitude == -73.75


def test_clear_coordinates_with_changed_place_and_zero_round_trip(app):
    client = admin_client(app)
    assert save(client, confirm(location_form(client, latitude='0', longitude='0'))).status_code == 200
    assert snapshot(app)[4:6] == (0, 0)
    before = snapshot(app)
    payload = location_form(client, city='Different place')
    del payload['latitude'], payload['longitude']
    assert save(client, payload).status_code == 400
    assert snapshot(app) == before
    payload.update(latitude='', longitude='')
    assert save(client, payload).status_code == 200
    assert snapshot(app)[1] == 'Different place'
    assert snapshot(app)[4:6] == (None, None)


def test_coordinate_edit_invalidates_stale_settings_form(app):
    client = admin_client(app)
    assert save(client, confirm(location_form(client))).status_code == 200
    stale = location_form(client, name='Stale edit')
    current = location_form(client, longitude='-74.02')
    assert save(client, current).status_code == 200
    assert save(client, stale).status_code == 400
    assert snapshot(app)[5] == -74.02


@pytest.mark.parametrize('license_error', [None, 404, 503])
def test_complete_sync_two_distinct_stations_schedule_and_identity(central, license_error):
    from app.services.central_api.client import APIError
    reporter, api = central
    api.entitlement.update(plan='free', channel_limit=2, expires_at=None)
    if license_error:
        api.fail['/v1/license'] = APIError('unavailable', status=license_error)
    stations = Station.query.order_by(Station.id).all()
    uuids = [station.freo_station_id for station in stations]
    for station in stations:
        station.city, station.region, station.country = 'New York', 'NY', 'US'
        station.latitude, station.longitude = 40.7128, -74.006
        station.genre, station.directory_categories = 'Rock', ['Independent', 'Community']
        station.directory_opt_in = False
    db.session.commit()
    reporter.tick()
    syncs = [payload for _, path, payload, _ in api.calls if path == '/v1/stations/sync']
    assert len(syncs) == 1
    assert len(set(uuids)) == 2
    for station, entry in zip(stations, syncs[0]['stations']):
        assert entry == dict(station_id=station.freo_station_id, name=station.name,
            description=station.description, genre='Rock', categories=['Independent', 'Community'],
            city='New York', region='NY', country='US', latitude=40.71, longitude=-74.01,
            public_url=f'https://radio.example.org/player/{station.slug}', directory_opt_in=False)
    credentials = reporter.store.read()
    now = time.time()
    due = installation().state['report']['due']
    assert now + 3500 < due < now + 3700
    old_digest = db.session.get(CentralStationState, stations[0].id).synced_digest
    stations[0].longitude = -74.02
    db.session.commit()
    assert digest(metadata(stations[0])) != old_digest
    count = len(api.calls)
    reporter.tick(now=now + 60)
    assert len(api.calls) == count  # No second worker or bypass of the schedule.
    reporter.tick(now=due + 1)
    syncs = [payload for _, path, payload, _ in api.calls if path == '/v1/stations/sync']
    assert len(syncs) == 2 and len(syncs[-1]['stations']) == 1
    assert syncs[-1]['stations'][0]['longitude'] == -74.02
    assert db.session.get(CentralStationState, stations[0].id).synced_digest == digest(metadata(stations[0]))
    Reporter(api.factory).tick(now=due + 2)
    assert reporter.store.read() == credentials
    assert installation().installation_id == INSTALLATION_ID
    assert [s.freo_station_id for s in stations] == uuids
    assert sum(path == '/v1/register' for _, path, _, _ in api.calls) == 1
    for _, path, payload, token in api.calls:
        if path in ('/v1/stations/sync', '/v1/heartbeat'):
            assert token == TOKEN
        if path == '/v1/heartbeat':
            assert payload['installation']['freo_version'] == VERSION
            assert 'latitude' not in json.dumps(payload) and 'longitude' not in json.dumps(payload)
            assert all({'station_id', 'on_air', 'metrics'} == set(s) for s in payload['stations'])


def test_missing_coordinates_and_sync_failure_retry_remain_supported(central):
    from app.services.central_api.client import APIError
    reporter, api = central
    api.fail['/v1/stations/sync'] = APIError('unavailable', status=503, retry_after=120)
    reporter.tick()
    credentials = reporter.store.read()
    due = installation().state['report']['due']
    assert all(station.enabled for station in Station.query)
    assert all(state.synced_digest is None for state in CentralStationState.query)
    count = len(api.calls)
    reporter.tick(now=due - 1)
    assert len(api.calls) == count
    del api.fail['/v1/stations/sync']
    reporter.tick(now=due + 1)
    assert reporter.store.read() == credentials
    assert installation().state['last_heartbeat']['stations_accepted'] == 2
    entries = [p for _, path, p, _ in api.calls if path == '/v1/stations/sync'][-1]['stations']
    assert all(e['latitude'] is None and e['longitude'] is None for e in entries)


def test_serialized_authenticated_sync_uses_stored_coordinates(central, monkeypatch):
    """Exercise the real HTTPS client's serialization without contacting a server."""
    import ssl
    from app.services.central_api.client import Client
    reporter, api = central
    wire = []

    class Transport:
        def __init__(self, host, port, timeout, context):
            assert host == 'api.freo.live' and port == 443 and timeout == 5
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            self.sock = self

        def connect(self):
            pass

        def settimeout(self, timeout):
            assert timeout == 30

        def request(self, method, path, body, headers):
            wire.append((method, path, body, headers))
            token = headers.get('Authorization', '').removeprefix('Bearer ') or None
            payload = json.loads(body) if body else None
            self.response = api.factory('https://api.freo.live', token).request(method, path, payload)

        def getresponse(self):
            return self

        status = 200

        def read(self, maximum):
            return json.dumps(self.response).encode()

        def close(self):
            pass

    monkeypatch.setattr('app.services.central_api.client.http.client.HTTPSConnection', Transport)
    station = db.session.get(Station, 1)
    station.city, station.region, station.country = 'Test city', 'Test region', 'US'
    station.latitude, station.longitude = 0, 0
    db.session.commit()
    expected = [metadata(s) for s in Station.query.order_by(Station.id)]
    reporter.client_factory = Client
    reporter.tick()
    method, path, body, headers = next(call for call in wire if call[1] == '/v1/stations/sync')
    assert method == 'POST' and isinstance(body, bytes)
    assert json.loads(body) == {'stations': expected}
    assert headers['Authorization'] == 'Bearer ' + TOKEN
    assert headers['Content-Type'] == 'application/json'
    assert installation().state['last_heartbeat']['stations_accepted'] == 2
