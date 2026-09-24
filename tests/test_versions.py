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
from app.services.central_api.releases import heartbeat_release, check_version, version_view
from app.version import VERSION
from tests.test_central_api import TOKEN, central
from tests.test_web import app, admin_client


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



def test_authoritative_version_ignores_legacy_overrides(app, monkeypatch):
    monkeypatch.setenv('FREO_VERSION', '9.9.9')
    app.config['FREO_VERSION'] = 'development'
    with app.app_context():
        snapshot = machine_snapshot()
    assert snapshot['freo_version'] == VERSION == '0.3.0-rc.7.dev3'
    assert snapshot['os'] == platform.system()
    assert snapshot['architecture'] == platform.machine()
    assert {'cpu_count', 'ram_bytes', 'disk_total_bytes', 'disk_free_bytes'} <= snapshot.keys()


def test_version_heartbeat_preserves_payload_identity_and_startup_cadence(central):
    reporter, api = central
    reporter.tick()
    credentials = reporter.store.read()
    method, _, payload, token = next(call for call in api.calls if call[1] == '/v1/heartbeat')
    assert method == 'POST' and token == TOKEN
    assert set(payload) == {'installation', 'stations'}
    assert set(payload['installation']) == set(machine_snapshot())
    assert payload['installation']['freo_version'] == VERSION
    assert len(payload['stations']) == Station.query.count()
    assert all(set(s) == {'station_id', 'on_air', 'metrics'} for s in payload['stations'])
    assert 3595 < installation().state['report']['due'] - time.time() <= 3660
    reporter.tick()
    assert sum(c[1] == '/v1/heartbeat' for c in api.calls) == 1
    restarted = Reporter(api.factory)
    restarted.tick()
    restarted.tick()
    assert sum(c[1] == '/v1/heartbeat' for c in api.calls) == 2
    assert reporter.store.read() == credentials
    assert sum(c[1] == '/v1/register' for c in api.calls) == 1


@pytest.mark.parametrize('running', ['v1.0.0', '1.0.0-rc.1', '1.1.0-rc.1', 'unknown'])
def test_restart_after_upgrade_reports_actual_changed_version(central, monkeypatch, running):
    reporter, api = central
    reporter.tick()
    identity = reporter.store.read()
    monkeypatch.setattr('app.services.central_api.metrics.VERSION', running)
    Reporter(api.factory).tick()
    calls = [c for c in api.calls if c[1] == '/v1/heartbeat']
    assert calls[0][2]['installation']['freo_version'] == VERSION
    assert calls[-1][2]['installation']['freo_version'] == running
    assert installation().state['last_heartbeat']['freo_version'] == running
    assert reporter.store.read() == identity


@pytest.mark.parametrize('status,available,label', [
    ('CURRENT', False, 'Current'), ('UPDATE_AVAILABLE', True, 'Update Available'),
    ('AHEAD', False, 'Ahead'), ('UNKNOWN', None, 'Unknown'),
])
def test_all_statuses_are_server_owned_and_shared_by_ui(app, central, status, available, label, monkeypatch):
    from app.services.operations import connection
    reporter, api = central
    # Intentionally inconsistent numerical order: the client must trust the status.
    api.heartbeat_fields = dict(installed_version=VERSION, latest_version='v9.0.0',
                                version_status=status, update_available=available)
    reporter.tick()
    receipt = installation().state['last_heartbeat']
    assert receipt['installed_version'] == VERSION
    assert receipt['version_status'] == status and receipt['update_available'] is available
    assert receipt['latest_version'] == 'v9.0.0'
    def no_network(*args, **kwargs):
        pytest.fail('UI must use cached data')
    monkeypatch.setattr(Client, 'request', no_network)
    page = admin_client(app).get('/admin/installation')
    assert page.status_code == 200
    assert '<dd>' + VERSION + '</dd>' in page.text
    assert '<dd>' + label + '</dd>' in page.text
    assert ('An update is available' in page.text) is (available is True)
    assert TOKEN not in page.text
    panel = connection(Station.query.all(), time.time())
    assert panel['update_status'] == label
    assert panel['update_available'] is available


@pytest.mark.parametrize('fields', [
    {}, {'update_available': False}, {'version_status': 'FUTURE', 'update_available': False},
    {'version_status': []}, {'version_status': None},
    {'version_status': 'CURRENT', 'latest_version': None, 'update_available': False},
    {'version_status': 'UNKNOWN', 'update_available': True},
])
def test_missing_unknown_and_first_release_replace_previous_status(central, fields):
    reporter, api = central
    api.heartbeat_fields = dict(latest_version='1.0.0', version_status='CURRENT', update_available=False)
    reporter.tick()
    api.heartbeat_fields = dict(fields, future={'ignored': True})
    reporter.heartbeat(installation(), api.factory('https://api.freo.live', TOKEN), [])
    receipt = installation().state['last_heartbeat']
    assert receipt['version_status'] == 'UNKNOWN' and receipt['update_available'] is None
    assert 'future' not in receipt
    db.session.remove()
    assert installation().state['last_heartbeat'] == receipt


@pytest.mark.parametrize('value', [True, 1, 'false', [], {}])
def test_inconsistent_or_nonboolean_flag_cannot_announce_update(value):
    result = heartbeat_release(dict(latest_version='1.0.0', version_status='AHEAD', update_available=value))
    assert result['version_status'] == 'AHEAD' and result['update_available'] is None


@pytest.mark.parametrize('error', [APIError('connection_or_response_error'),
    APIError('http_503', status=503), APIError('http_429', status=429, retry_after=7200)])
def test_outage_keeps_cached_information_and_restart_respects_backoff(central, error):
    reporter, api = central
    api.heartbeat_fields = dict(latest_version='1.0.0', version_status='AHEAD', update_available=False)
    reporter.tick()
    row = installation()
    receipt, cache, credentials = copy.deepcopy(row.state['last_heartbeat']), copy.deepcopy(row.license_cache), reporter.store.read()
    stations = [(s.id, s.enabled, s.desired_state) for s in Station.query]
    row.state = dict(row.state, report={'due': 0})
    db.session.commit()
    api.fail['/v1/heartbeat'] = error
    reporter.tick()
    count = sum(c[1] == '/v1/heartbeat' for c in api.calls)
    Reporter(api.factory).tick()
    assert sum(c[1] == '/v1/heartbeat' for c in api.calls) == count
    assert row.state['last_heartbeat'] == receipt
    assert row.license_cache['entitlement'] == cache['entitlement']
    assert reporter.store.read() == credentials
    assert [(s.id, s.enabled, s.desired_state) for s in Station.query] == stations
    view = version_view(row.state, time.time())
    assert view['update_status'] == 'Ahead' and 'stale' in view['version_note']
    if error.retry_after:
        assert row.state['retry_after'] > time.time() + 7100


def test_upgrade_does_not_present_previous_running_version_status_as_current(central):
    reporter, api = central
    api.heartbeat_fields = dict(latest_version='1.0.0', version_status='CURRENT', update_available=False)
    reporter.tick()
    state = copy.deepcopy(installation().state)
    state['last_heartbeat']['freo_version'] = 'old-build'
    view = version_view(state, time.time())
    assert view['update_status'] == 'Unknown'
    assert 'running version' in view['version_note']


@pytest.mark.parametrize('seconds', [30, 60, 1800, 7200, 86401])
def test_server_heartbeat_interval_is_respected(central, seconds):
    reporter, api = central
    api.heartbeat_fields = {'next_heartbeat_seconds': seconds}
    reporter.tick()
    due = installation().state['report']['due']
    assert seconds - 5 < due - time.time() <= seconds + 60


@pytest.mark.parametrize('seconds', [0, -1, True, '3600'])
def test_bad_interval_retains_previous_receipt_and_retries(central, seconds):
    reporter, api = central
    reporter.tick()
    row = installation()
    receipt = copy.deepcopy(row.state['last_heartbeat'])
    row.state = dict(row.state, report={'due': 0})
    db.session.commit()
    api.heartbeat_fields = {'next_heartbeat_seconds': seconds}
    reporter.tick()
    assert row.state['last_heartbeat'] == receipt
    assert row.state['report']['failures'] == 1


@pytest.mark.parametrize('latest', ['v1.0.0', '1.0.0', None])
@pytest.mark.parametrize('checked', [None, '2026-09-23T20:31:24.157161Z'])
def test_public_discovery_is_metadata_only_and_first_release_is_normal(app, transport, latest, checked):
    transport['body'] = json.dumps(dict(latest_version=latest, source='github_release', checked_at=checked,
        release_url='https://github.com/3andB/freo/releases/tag/v1.0.0' if latest else None)).encode()
    with app.app_context():
        assert CentralInstallation.query.count() == 0
        result = app.test_cli_runner().invoke(args=['central-api', 'check-version'])
        assert CentralInstallation.query.count() == 0
    assert result.exit_code == 0, result.output
    assert 'Latest stable version: ' + (latest or 'Unknown') in result.output
    assert 'Version status: Unknown' in result.output
    assert 'Release discovered at: ' + (checked or 'Unknown') in result.output
    assert 'Authorization' not in transport['calls'][0][3]


@pytest.mark.parametrize('changes', [
    {'error': TimeoutError()}, {'error': ssl.SSLError()}, {'error': http.client.RemoteDisconnected()},
    {'status': 503}, {'status': 429}, {'status': 302}, {'body': b'not json'},
    {'body': b'[]'}, {'body': b'{}'}, {'body': b'{"latest_version":[]}'},
])
def test_discovery_failures_are_bounded_private_and_do_not_follow_redirects(app, transport, changes):
    transport.update(changes)
    result = app.test_cli_runner().invoke(args=['central-api', 'check-version'])
    assert result.exit_code == 1 and 'Version check unavailable' in result.output
    assert 'up to date' not in result.output
    assert transport['closed'] == 1 and len(transport['calls']) <= 1
    assert TOKEN not in result.output


@pytest.mark.parametrize('url', ['http://github.com/3andB/freo/releases/tag/v1',
    'https://evil.test/releases/v1', 'https://github.com.evil/3andB/freo/releases/tag/v1',
    'javascript:alert(1)', 'https://user@github.com/3andB/freo/releases/tag/v1',
    'https://github.com/3andB/freo/releases/tag/../../other',
    'https://github.com/3andB/freo/releases/tag/%2e%2e/%2e%2e/other'])
def test_untrusted_release_link_is_not_rendered(transport, url):
    transport['body'] = json.dumps(dict(latest_version='1.0.0', release_url=url)).encode()
    assert check_version('https://api.freo.live')['release_url'] is None


def test_public_metadata_is_cached_and_discovery_time_is_not_contact_time(central):
    from app.services.central_api.connection_check import queue_check
    reporter, api = central
    api.heartbeat_fields = dict(installed_version=VERSION, latest_version='1.0.0', version_status='UPDATE_AVAILABLE', update_available=True)
    discovered = '2026-09-23T12:00:00Z'
    link = 'https://github.com/3andB/freo/releases/tag/v1.0.0'
    api.release = dict(latest_version='1.0.0', checked_at=discovered, release_url=link)
    reporter.tick()
    assert not any(c[1] == '/v1/releases/latest' for c in api.calls)
    queue_check()
    reporter.process_connection_check()
    view = version_view(installation().state, time.time())
    assert view['release_checked_at'] == discovered
    assert view['version_checked_at'] != discovered
    assert view['release_url'] == link
    reporter.discover_release(installation(), time.time() + 61)
    assert sum(c[1] == '/v1/releases/latest' for c in api.calls) == 1


@pytest.mark.parametrize('license_state', ['absent', 'expired', 'suspended'])
def test_reporting_is_independent_of_paid_entitlement(central, license_state):
    reporter, api = central
    row = installation()
    row.manager_email = ''
    row.registration_state = 'unconfigured'
    db.session.commit()
    if license_state == 'absent':
        api.fail['/v1/license'] = APIError('http_404', status=404)
    else:
        api.entitlement.update(plan='free', status=license_state)
    reporter.tick()
    assert row.state['last_heartbeat']['freo_version'] == VERSION
    assert any(c[1] == '/v1/heartbeat' for c in api.calls)
    assert not row.state.get('owner_profile_id')


def test_legacy_public_cache_does_not_relabel_local_time_as_discovery_time():
    from types import SimpleNamespace
    check = SimpleNamespace(finished_at=time.time(), status='failed', result=dict(
        latest_version='1.0.0', checked_at=time.time(), version_source='public', update_available=False))
    view = version_view({}, time.time(), manual=check)
    assert view['release_checked_at'] == 'Unknown'
    assert view['update_status'] == 'Unknown'
