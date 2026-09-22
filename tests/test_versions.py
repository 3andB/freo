"""Version reporting and public discovery never control broadcasting or licensing."""
import copy
import http.client
import json
import platform
import ssl
import time
from pathlib import Path

import pytest

from app.extensions import db
from app.models import CentralInstallation, Station
from app.services.central_api import Reporter, installation
from app.services.central_api.client import APIError, Client
from app.services.central_api.metrics import machine_snapshot
from app.services.central_api.releases import semver_key
from app.version import VERSION
from tests.test_central_api import TOKEN, central
from tests.test_web import app, admin_client


def test_authoritative_version_ignores_legacy_overrides(app, monkeypatch):
    monkeypatch.setenv('FREO_VERSION', '9.9.9')
    app.config['FREO_VERSION'] = 'development'
    def no_release_file(*args, **kwargs):
        pytest.fail('Machine snapshot must not read a release file')
    monkeypatch.setattr(Path, 'read_text', no_release_file)
    with app.app_context():
        snapshot = machine_snapshot()
    assert snapshot['freo_version'] == VERSION == '0.3.0-rc.3'
    assert snapshot['os'] == platform.system()
    assert snapshot['architecture'] == platform.machine()
    assert snapshot['install_type'] == 'self-hosted'
    assert {'cpu_count', 'ram_bytes', 'disk_total_bytes', 'disk_free_bytes'} <= snapshot.keys()


def test_version_heartbeat_preserves_identity_payload_and_cadence(central):
    reporter, api = central
    reporter.tick()
    credentials = reporter.store.read()
    method, _, payload, token = next(call for call in api.calls if call[1] == '/v1/heartbeat')
    assert method == 'POST' and token == TOKEN
    assert set(payload) == {'installation', 'stations'}
    assert set(payload['installation']) == set(machine_snapshot())
    assert payload['installation']['os'] == platform.system()
    assert payload['installation']['architecture'] == platform.machine()
    assert payload['installation']['freo_version'] == VERSION
    assert len(payload['stations']) == Station.query.count()
    assert all(set(station) == {'station_id', 'on_air', 'metrics'} for station in payload['stations'])
    assert not any('ip' in key.lower() for key in payload['installation'])
    due = installation().state['report']['due']
    assert 3595 < due - time.time() <= 3660
    Reporter(api.factory).tick()
    assert sum(call[1] == '/v1/heartbeat' for call in api.calls) == 1
    assert reporter.store.read() == credentials


@pytest.mark.parametrize('fields,expected', [
    ({'latest_version': '0.2.0', 'update_available': True}, ('0.2.0', True)),
    ({'latest_version': '0.1.0', 'update_available': False}, ('0.1.0', False)),
    # Use the server boolean, even if a local comparison would disagree.
    ({'latest_version': '9.0.0', 'update_available': False}, ('9.0.0', False)),
    ({'latest_version': '0.2.0', 'update_available': None}, ('0.2.0', None)),
    ({'latest_version': '0.2.0'}, ('0.2.0', None)),
    ({'latest_version': None, 'update_available': None}, (None, None)),
    ({}, (None, None)),
    ({'latest_version': 'invalid', 'update_available': 'false'}, (None, None)),
    ({'latest_version': [], 'update_available': 1}, (None, None)),
    ({'latest_version': '0.2.0', 'update_available': 0}, ('0.2.0', None)),
])
def test_optional_heartbeat_release_fields(central, fields, expected):
    reporter, api = central
    # An unknown result must replace a previous known result on an accepted heartbeat.
    api.heartbeat_fields = {'latest_version': '0.2.0', 'update_available': True}
    reporter.tick()
    api.heartbeat_fields = dict(fields, future_field={'ignored': 'value'})
    reporter.heartbeat(installation(), api.factory('https://api.freo.live', TOKEN), [])
    receipt = installation().state['last_heartbeat']
    assert (receipt['latest_version'], receipt['update_available']) == expected
    assert 'future_field' not in receipt
    assert receipt['stations_accepted'] == 0
    db.session.remove()
    assert installation().state['last_heartbeat'] == receipt


@pytest.mark.parametrize('error', [
    APIError('connection_or_response_error'), APIError('http_503', status=503),
    APIError('http_429', status=429, retry_after=120),
])
def test_failed_reporting_keeps_receipt_license_credentials_and_broadcasts(central, error):
    reporter, api = central
    api.heartbeat_fields = {'latest_version': '0.2.0', 'update_available': True}
    reporter.tick()
    row = installation()
    cache = copy.deepcopy(row.license_cache)
    receipt = copy.deepcopy(row.state['last_heartbeat'])
    credentials = reporter.store.read()
    stations = [(s.id, s.enabled, s.desired_state) for s in Station.query]
    row.state = dict(row.state, report={'due': 0})
    db.session.commit()
    api.fail['/v1/heartbeat'] = error
    reporter.tick()
    assert row.state['last_heartbeat'] == receipt
    assert row.license_cache['entitlement'] == cache['entitlement']
    assert row.license_cache['received_at'] == cache['received_at']
    assert reporter.store.read() == credentials
    assert [(s.id, s.enabled, s.desired_state) for s in Station.query] == stations
    assert row.state['report']['failures'] == 1
    count = len(api.calls)
    reporter.tick()
    assert len(api.calls) == count


@pytest.mark.parametrize('older,newer', [
    ('0.1.9', '0.1.10'), ('0.9.0', '0.10.0'), ('1.99.99', '2.0.0'),
    ('1.0.0-alpha', '1.0.0-alpha.1'), ('1.0.0-alpha.1', '1.0.0-alpha.beta'),
    ('1.0.0-alpha.beta', '1.0.0-beta'), ('1.0.0-beta', '1.0.0-beta.2'),
    ('1.0.0-beta.2', '1.0.0-beta.11'), ('1.0.0-beta.11', '1.0.0-rc.1'),
    ('1.0.0-rc.1', '1.0.0'), ('1.0.0-999', '1.0.0-a'),
    ('1.0.0-Z', '1.0.0-a'), ('1.0.0-0', '1.0.0-1'),
])
def test_semver_precedence(older, newer):
    assert semver_key(older) < semver_key(newer)


def test_semver_build_metadata_does_not_change_precedence():
    assert semver_key('1.2.3+001') == semver_key('1.2.3+other') == semver_key('1.2.3')
    assert semver_key('1.2.3-rc.1+001') == semver_key('1.2.3-rc.1+other')
    assert semver_key('1.2.3-01a+001') < semver_key('1.2.3')


@pytest.mark.parametrize('invalid', [None, True, 1, [], {}, '', 'v1.2.3', '1.2',
    '01.2.3', '1.02.3', '1.2.03', '1.2.3-01', '1.2.3-rc.01', '1.2.3-',
    '1.2.3+', '1.2.3-a..b', '1.2.3+a..b', '1.2.3_a', '1.2.3\n', ' 1.2.3', '１.2.3'])
def test_invalid_semver_is_rejected(invalid):
    with pytest.raises(ValueError):
        semver_key(invalid)


@pytest.fixture
def transport(monkeypatch):
    """Exercise the real client with an in-memory HTTPS connection."""
    state = {'body': b'{"latest_version":"0.1.0","future_field":true}',
             'status': 200, 'error': None, 'calls': [], 'closed': 0}
    class Connection:
        def __init__(self, host, port, timeout, context):
            assert (host, port, timeout) == ('api.freo.live', 443, 5)
            assert context.check_hostname
            self.sock = self
        def connect(self):
            if state['error']:
                raise state['error']
        def settimeout(self, timeout):
            assert timeout == 30
        def request(self, method, path, body, headers):
            state['calls'].append((method, path, body, headers))
        def getresponse(self):
            self.status = state['status']
            return self
        def read(self, limit):
            return state['body'][:limit]
        def getheader(self, name, default=''):
            return default
        def close(self):
            state['closed'] += 1
    monkeypatch.setattr('app.services.central_api.client.http.client.HTTPSConnection', Connection)
    return state


def test_transport_heartbeat_headers_and_public_discovery(transport):
    client = Client(token=TOKEN)
    payload = {'installation': {'freo_version': VERSION}, 'stations': []}
    client.request('POST', '/v1/heartbeat', payload)
    method, path, body, headers = transport['calls'][-1]
    assert (method, path, json.loads(body)) == ('POST', '/v1/heartbeat', payload)
    assert headers == {'Accept': 'application/json', 'Content-Type': 'application/json',
                       'Authorization': 'Bearer ' + TOKEN}
    client.request('GET', '/v1/releases/latest')
    assert transport['calls'][-1] == ('GET', '/v1/releases/latest', None,
        {'Accept': 'application/json', 'Content-Type': 'application/json'})
    assert transport['closed'] == 2


@pytest.mark.parametrize('latest,available', [
    ('0.2.0', False), ('0.1.9', False), ('0.3.0', True),
    ('0.2.0-rc.1', False), ('0.2.0+new', False), ('0.3.0-rc.3', False),
])
def test_public_discovery_without_identity_or_license(app, transport, latest, available):
    transport['body'] = json.dumps({'latest_version': latest, 'future': 'ignored'}).encode()
    with app.app_context():
        assert CentralInstallation.query.count() == 0
        result = app.test_cli_runner().invoke(args=['central-api', 'check-version'])
        assert CentralInstallation.query.count() == 0
    assert result.exit_code == 0, result.output
    assert 'Installed version: ' + VERSION in result.output
    assert 'Latest version: ' + latest in result.output
    assert ('Update available.' if available else 'No newer version available.') in result.output
    assert len(transport['calls']) == 1
    assert 'Authorization' not in transport['calls'][0][3]


@pytest.mark.parametrize('changes', [
    {'error': TimeoutError()}, {'error': ssl.SSLError()},
    {'error': http.client.RemoteDisconnected()}, {'status': 503}, {'status': 429},
    {'body': b'not json'}, {'body': b'[]'}, {'body': b'{}'},
    {'body': b'{"latest_version":null}'}, {'body': b'{"latest_version":"0.01.0"}'},
])
def test_discovery_failure_is_unknown_and_preserves_all_state(app, central, transport, changes):
    reporter, _ = central
    reporter.tick()
    row = installation()
    saved = copy.deepcopy((row.state, row.license_cache, row.registration_state))
    credentials = reporter.store.read()
    stations = [(s.id, s.enabled, s.desired_state) for s in Station.query]
    transport.update(changes)
    result = app.test_cli_runner().invoke(args=['central-api', 'check-version'])
    assert result.exit_code == 1
    assert 'Version check unavailable; update status unknown' in result.output
    assert 'No newer version' not in result.output
    assert (row.state, row.license_cache, row.registration_state) == saved
    assert reporter.store.read() == credentials
    assert [(s.id, s.enabled, s.desired_state) for s in Station.query] == stations
    assert transport['closed'] == 1


@pytest.mark.parametrize('available,label', [(True, 'Update available'),
    (False, 'No newer version available'), (None, 'Unknown')])
def test_installation_page_uses_cached_update_status(app, central, available, label, monkeypatch):
    reporter, api = central
    api.heartbeat_fields = {'latest_version': '0.2.0', 'update_available': available}
    reporter.tick()
    count = len(api.calls)
    def no_network(*args, **kwargs):
        pytest.fail('Installation page must use cached data only')
    monkeypatch.setattr(Client, 'request', no_network)
    page = admin_client(app).get('/admin/installation')
    assert page.status_code == 200
    assert 'Installed version: <strong>' + VERSION in page.text
    assert 'Latest reported version: <strong>0.2.0' in page.text
    assert 'Update status: <strong>' + label in page.text
    assert len(api.calls) == count
    assert TOKEN not in page.text


@pytest.mark.parametrize('failed,reported_version', [(True, VERSION), (False, '0.0.9')])
def test_installation_page_does_not_present_old_status_as_current(app, central, failed, reported_version):
    reporter, api = central
    api.heartbeat_fields = {'latest_version': '0.2.0', 'update_available': True}
    reporter.tick()
    row = installation()
    row.state = dict(row.state, last_heartbeat=dict(row.state['last_heartbeat'], freo_version=reported_version),
                     report={'failures': 1} if failed else row.state['report'])
    db.session.commit()
    page = admin_client(app).get('/admin/installation').text
    assert 'Update status: <strong>Unknown' in page
    assert 'Latest reported version: <strong>0.2.0' in page
