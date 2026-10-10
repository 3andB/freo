"""Wire fixtures follow freo-live/api/docs/contract.md, commit 506a3ee."""
import json
import os
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from tests.test_web import app, admin_client
from app.extensions import db
from app.models import CentralInstallation, CentralHourlyMetric, Station, CentralStationState
from app.services.central_api import Reporter, installation, metadata
from app.services.central_api.client import APIError, Client, license_response
from app.services.central_api.identity import IdentityStore
from app.services.central_api.licensing import check_expansion, effective_time, checkpoint
from app.services.central_api.metrics import sample, wire_metric
from app.services.stations import set_enabled, create_station

INSTALLATION_ID = '018b81d4-7998-4b20-8cde-a128bc561d1f'
TOKEN = 'freo_' + 'x' * 43


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def license_payload(now=None, **changes):
    now = time.time() if now is None else now
    result = dict(installation_id=INSTALLATION_ID, plan='self-hosted', channel_limit=3, status='active',
        issued_at=iso(now - 60), expires_at=iso(now + 86400), renews_at=None,
        grace_until=iso(now + 3 * 86400), server_time=iso(now), refresh_after_seconds=3600,
        outage_policy='keep_existing_stations_on_air')
    return dict(result, **changes)


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.fail = {}
        self.entitlement = license_payload()
        self.token = TOKEN
        self.heartbeat_fields = {}
        self.release = {'latest_version': '0.1.0'}

    def factory(self, url, token=None):
        outer = self
        class Connection:
            def request(self, method, path, payload=None):
                outer.calls.append((method, path, payload, token))
                if path in outer.fail:
                    raise outer.fail[path]
                if path == '/v1/releases/latest':
                    assert token is None and method == 'GET' and payload is None
                    return outer.release
                if path == '/v1/register':
                    return dict(installation_id=INSTALLATION_ID, access_token=TOKEN,
                        token_type='Bearer', server_time=iso(time.time()), heartbeat_interval_seconds=3600)
                if path == '/v1/enroll':
                    outer.token = token
                    return dict(installation_id=INSTALLATION_ID, token_type='Bearer',
                        server_time=iso(time.time()), heartbeat_interval_seconds=3600, station_profile_id=None)
                assert token == outer.token
                if path == '/v1/license':
                    return outer.entitlement
                if path == '/v1/stations/sync':
                    return {'stations': [{'station_id': row['station_id'], 'created_at': iso(time.time()),
                        'updated_at': iso(time.time())} for row in payload['stations']], 'server_time': iso(time.time())}
                assert path == '/v1/heartbeat'
                return dict(dict(server_time=iso(time.time()), next_heartbeat_seconds=3600,
                    stations_accepted=len(payload['stations']), metrics_accepted=sum(len(s['metrics']) for s in payload['stations'])),
                    **outer.heartbeat_fields)
        return Connection()


@pytest.fixture
def central(app, tmp_path, monkeypatch):
    app.config.update(FREO_API_STATE_DIR=str(tmp_path / 'identity'), PUBLIC_BASE_URL='https://radio.example.org')
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (True, 4))
    with app.app_context():
        row = installation()
        row.manager_email = 'manager@example.org'
        row.registration_state = 'pending'
        db.session.commit()
        api = FakeAPI()
        reporter = Reporter(api.factory)
        reporter.store.prepare()
        yield reporter, api


def test_registration_and_restart_preserve_credentials_and_station_ids(central):
    reporter, api = central
    before = [station.freo_station_id for station in Station.query.all()]
    reporter.tick()
    assert [path for _, path, _, _ in api.calls] == ['/v1/register', '/v1/license', '/v1/stations/sync', '/v1/heartbeat']
    assert api.calls[0][2]['manager_email'] == 'manager@example.org'
    assert os.stat(reporter.store.path).st_mode & 0o777 == 0o600
    assert os.stat(reporter.store.directory).st_mode & 0o777 == 0o700
    assert TOKEN not in repr(installation().state) + repr(installation().license_cache)
    Reporter(api.factory).tick()
    assert sum(path == '/v1/register' for _, path, _, _ in api.calls) == 1
    assert [station.freo_station_id for station in Station.query.all()] == before
    for _, path, payload, token in api.calls[1:]:
        assert token == TOKEN
        assert 'manager_email' not in json.dumps(payload)


def test_uncertain_registration_requires_deliberate_retry(central):
    reporter, api = central
    api.fail['/v1/register'] = APIError('connection_or_response_error')
    reporter.tick()
    reporter.tick()
    Reporter(api.factory).tick()
    assert len(api.calls) == 1
    assert installation().registration_state == 'registration_uncertain'
    assert reporter.store.read() == {'registration_attempted': True}
    del api.fail['/v1/register']
    installation().registration_state = 'retry_registration'
    db.session.commit()
    reporter.tick()
    assert installation().installation_id == INSTALLATION_ID


def test_crash_before_or_after_credentials_are_saved(central):
    reporter, api = central
    reporter.store.write({'registration_attempted': True})
    reporter.tick()
    assert not api.calls
    assert installation().registration_state == 'registration_uncertain'
    reporter.store.write({'installation_id': INSTALLATION_ID, 'access_token': TOKEN})
    reporter.tick()
    assert not any(path == '/v1/register' for _, path, _, _ in api.calls)
    assert installation().installation_id == INSTALLATION_ID


def test_missing_or_revoked_credentials_never_register_again(central):
    reporter, api = central
    reporter.tick()
    cache = installation().license_cache
    api.fail['/v1/license'] = APIError('unauthorized', status=401)
    Reporter(api.factory).tick()
    assert installation().registration_state == 'credentials_rejected'
    assert installation().license_cache['entitlement'] == cache['entitlement']
    assert installation().license_cache['received_at'] == cache['received_at']
    reporter.store.path.unlink()
    reporter.tick()
    assert 'credentials_missing' in installation().last_error
    assert sum(path == '/v1/register' for _, path, _, _ in api.calls) == 1
    assert all(station.enabled for station in Station.query)


def test_station_uuid_unique_immutable_and_rename_sync(central):
    reporter, api = central
    stations = Station.query.all()
    uuids = [station.freo_station_id for station in stations]
    assert len(set(uuids)) == 2
    assert all(UUID(value).version == 4 for value in uuids)
    reporter.tick()
    stations[0].name = 'Renamed'
    stations[0].country = 'AU'
    stations[0].city = 'Perth'
    stations[0].region = 'WA'
    stations[0].genre = 'Rock'
    stations[0].directory_categories = ['Independent']
    stations[0].directory_opt_in = True
    db.session.commit()
    installation().state = {}
    db.session.commit()
    reporter.tick()
    syncs = [payload for _, path, payload, _ in api.calls if path == '/v1/stations/sync']
    changed = syncs[-1]['stations'][0]
    assert changed == dict(station_id=uuids[0], name='Renamed', description='Test stream', genre='Rock',
        categories=['Independent'], city='Perth', region='WA', country='AU', latitude=None, longitude=None,
        public_url='https://radio.example.org/player/test-station', directory_opt_in=True)
    stations[0].freo_station_id = str(uuid4())
    with pytest.raises(ValueError, match='cannot be changed'):
        db.session.commit()
    db.session.rollback()
    db.session.add(Station(name='Duplicate', slug='duplicate', freo_station_id=uuids[0]))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_weighted_hours_gaps_and_privacy(central, monkeypatch):
    reporter, api = central
    installation().registration_state = 'unconfigured'
    db.session.commit()
    now = int(time.time() // 3600) * 3600
    sample(now - 120)
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (True, 10))
    sample(now - 60)
    sample(now)
    metric = db.session.get(CentralHourlyMetric, (1, now - 3600))
    wire = wire_metric(metric)
    assert wire['average_listeners'] == 7
    assert wire['peak_listeners'] == 10
    assert wire['listener_hours'] == pytest.approx(14 / 60)
    assert wire['songs_in_library'] == 1
    assert wire['artists'] == wire['albums'] == 1
    assert wire['library_duration_seconds'] == 20
    assert wire['library_storage_bytes'] == 1000
    sample(now + 600)  # Restart/outage gaps are not attributed listeners.
    assert metric.observed_seconds == 120
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (None, None))
    assert sample(now + 660) == {}
    assert db.session.get(CentralStationState, 1).last_sample['listeners'] is None
    reporter.tick()
    # Resume known observations and deliver the completed UTC hour.
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (False, 0))
    installation().state = {}
    db.session.commit()
    reporter.tick()
    heartbeat = [payload for _, path, payload, _ in api.calls if path == '/v1/heartbeat'][-1]
    assert heartbeat['stations'][0]['on_air'] is False
    assert heartbeat['stations'][0]['metrics'][0] == wire
    raw = json.dumps(heartbeat)
    for forbidden in ('manager_email', 'Verified Test Track', 'Test Artist', 'Test Album', 'internal.mp3', 'checksum', 'claimant', 'listeners_ip'):
        assert forbidden not in raw
    assert metric.sent


def test_outage_retains_backlog_and_cached_license(central):
    reporter, api = central
    reporter.tick()
    cache = installation().license_cache
    installation().state = {}
    db.session.commit()
    now = int(time.time() // 3600) * 3600
    for state in CentralStationState.query:
        state.last_sample = None
    db.session.commit()
    sample(now - 120)
    sample(now - 60)
    api.fail['/v1/license'] = APIError('connection_or_response_error')
    api.fail['/v1/heartbeat'] = APIError('http_503', status=503)
    reporter.tick()
    assert installation().license_cache['entitlement'] == cache['entitlement']
    assert not db.session.get(CentralHourlyMetric, (1, now - 3600)).sent
    count = len(api.calls)
    reporter.tick()
    assert len(api.calls) == count
    assert Station.query.filter_by(slug='test-station').one().desired_state == 'running'
    installation().state = {}
    db.session.commit()
    api.fail.clear()
    reporter.tick()
    assert db.session.get(CentralHourlyMetric, (1, now - 3600)).sent


def test_unknown_metrics_are_omitted_and_backlog_is_bounded(central, monkeypatch):
    reporter, api = central
    now = int(time.time())
    db.session.add(CentralHourlyMetric(station_id=1, period_start=now - 8 * 86400,
        observed_seconds=60, listener_seconds=60, peak_listeners=1, snapshot={}, sent=False))
    db.session.commit()
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (None, None))
    reporter.tick()
    assert CentralHourlyMetric.query.count() == 0
    heartbeat = [payload for _, path, payload, _ in api.calls if path == '/v1/heartbeat'][-1]
    assert heartbeat['stations'] == []


def test_local_allowance_survives_remote_cache_expiry(central):
    reporter, api = central
    reporter.tick()
    row = installation()
    from copy import deepcopy
    cache = deepcopy(row.license_cache)
    cache['entitlement']['expires_at'] = iso(time.time() - 30)
    row.license_cache = dict(cache)
    db.session.commit()
    check_expansion()  # Expired date alone does not end outage grace.
    third = create_station('Third', 'third')
    with pytest.raises(ValueError, match='three stations'):
        check_expansion()
    set_enabled(third, False)
    check_expansion()
    cache = dict(row.license_cache)
    cache['entitlement'] = dict(cache['entitlement'], grace_until=iso(time.time() - 1))
    row.license_cache = cache
    db.session.commit()
    set_enabled(third, True)  # Remote grace cannot revoke the local allowance.
    first = Station.query.filter_by(slug='test-station').one()
    set_enabled(first, True)  # Already enabled stations remain recoverable.
    assert first.enabled and first.desired_state == 'running'
    assert third.enabled


@pytest.mark.parametrize('changes', [dict(status='suspended'), dict(status='expired'), dict(channel_limit=1)])
def test_remote_license_changes_do_not_revoke_local_allowance(central, changes):
    reporter, api = central
    api.entitlement.update(changes)
    reporter.tick()
    check_expansion()
    assert all(station.enabled for station in Station.query)


@pytest.mark.parametrize('change', [dict(installation_id=str(uuid4())), dict(channel_limit=True),
    dict(status='unknown'), dict(grace_until='bad'), dict(outage_policy='stop'), dict(expires_at='nope'), dict(station_profile_id=0), dict(station_profile_id=''), dict(registration_status='registered', station_profile_id=None),
    dict(registration_status='unregistered', station_profile_id=INSTALLATION_ID),
    dict(registration_status='unknown', station_profile_id=None)])
def test_invalid_entitlement_is_rejected(change):
    with pytest.raises(APIError, match='invalid_license_response'):
        license_response(license_payload(**change), INSTALLATION_ID)


def test_clock_rollback_is_sticky_until_valid_verification(central):
    reporter, api = central
    reporter.tick()
    row = installation()
    received = row.license_cache['received_at']
    checkpoint(row, received - 3600)
    db.session.commit()
    assert effective_time(row.license_cache, received + 1) is None
    check_expansion()
    installation().state = {}
    db.session.commit()
    reporter.tick()
    assert not row.license_cache.get('clock_uncertain')


def test_unconfigured_self_hosted_baseline_and_registered_without_cache(central):
    reporter, api = central
    check_expansion()
    row = installation()
    row.installation_id = INSTALLATION_ID
    db.session.commit()
    check_expansion()
    assert all(station.enabled for station in Station.query)


def test_admin_configuration_auth_csrf_and_private_data(app):
    authenticated = admin_client(app)
    client = app.test_client()
    assert client.get('/admin/installation').status_code == 302
    assert authenticated.post('/admin/installation', data={'manager_email': 'm@example.org'}).status_code == 400
    page = authenticated.get('/admin/installation')
    assert page.status_code == 200
    assert page.headers['Cache-Control'] == 'private, no-store'
    with authenticated.session_transaction() as state:
        csrf = state['admin_csrf']
    response = authenticated.post('/admin/installation', data={'csrf': csrf, 'manager_email': 'manager@example.org'})
    assert response.status_code == 302
    with app.app_context():
        assert installation().registration_state == 'pending'
    assert 'manager@example.org' not in client.get('/api/stations').get_data(as_text=True)


def test_https_and_credential_store_guards(tmp_path):
    for base in ('http://api.freo.live', 'https://user:secret@api.freo.live', 'https://api.freo.live/v1', 'https://api.freo.live/#x'):
        with pytest.raises(ValueError):
            Client(base)
    store = IdentityStore(tmp_path / 'private')
    with store.lock():
        with pytest.raises(APIError, match='already_running'):
            with IdentityStore(store.directory).lock():
                pass
        store.write({'installation_id': INSTALLATION_ID, 'access_token': TOKEN})
        os.chmod(store.path, 0o644)
        with pytest.raises(APIError, match='unsafe_credential_file'):
            store.read()


def test_transport_timeouts_no_redirects_and_retry_after(monkeypatch):
    import app.services.central_api.client as transport
    connections = []
    class Socket:
        def settimeout(self, timeout):
            assert timeout == 30
    class Response:
        status = 429
        def read(self, size):
            assert size == 256 * 1024 + 1
            return b'{"error":{"message":"secret must not be logged"}}'
        def getheader(self, name, default=''):
            return '120' if name == 'Retry-After' else default
    response = Response()
    class Connection:
        def __init__(self, host, port, timeout, context):
            assert (host, port, timeout) == ('api.freo.live', 443, 5)
            assert context.check_hostname
            self.sock = Socket()
            connections.append(self)
        def connect(self):
            pass
        def request(self, method, path, body, headers):
            assert headers['Authorization'] == 'Bearer ' + TOKEN
        def getresponse(self):
            return response
        def close(self):
            self.closed = True
    monkeypatch.setattr(transport.http.client, 'HTTPSConnection', Connection)
    client = Client(token=TOKEN)
    with pytest.raises(APIError) as error:
        client.request('GET', '/v1/license')
    assert error.value.retry_after == 120 and error.value.status == 429
    assert 'secret' not in str(error.value)
    response.status = 302
    with pytest.raises(APIError, match='http_302'):
        client.request('GET', '/v1/license')
    assert len(connections) == 2 and all(connection.closed for connection in connections)
    response.status = 201
    with pytest.raises(APIError, match='invalid_heartbeat_status'):
        client.request('POST', '/v1/heartbeat', {'installation': {}, 'stations': []})


def test_retry_after_and_invalid_payload_do_not_spin(central):
    reporter, api = central
    api.fail['/v1/license'] = APIError('http_429', status=429, retry_after=7200)
    reporter.tick()
    assert len(api.calls) == 2  # Registration and license; respect global Retry-After.
    reporter.tick(now=time.time() + 3600)
    assert len(api.calls) == 2
    installation().state = {}
    db.session.commit()
    api.fail.clear()
    api.fail['/v1/stations/sync'] = APIError('http_400', status=400)
    reporter.tick()
    count = len(api.calls)
    reporter.tick(now=time.time() + 3600)
    assert sum(path == '/v1/stations/sync' for _, path, _, _ in api.calls) == 1
    assert len(api.calls) <= count + 1  # License can still refresh independently.


def test_unknown_station_resyncs_and_deleted_station_opts_out(central):
    reporter, api = central
    reporter.tick()
    installation().state = {}
    db.session.commit()
    api.fail['/v1/heartbeat'] = APIError('station_not_synced', status=409)
    reporter.tick()
    assert all(state.synced_digest is None for state in CentralStationState.query)
    api.fail.clear()
    installation().state = {}
    station = db.session.get(Station, 1)
    station.directory_opt_in = True
    station.deleted_at = datetime.now(timezone.utc)
    db.session.commit()
    reporter.tick()
    synced = [payload for _, path, payload, _ in api.calls if path == '/v1/stations/sync'][-1]
    heartbeat = [payload for _, path, payload, _ in api.calls if path == '/v1/heartbeat'][-1]
    assert not synced['stations'][0]['directory_opt_in']
    assert not next(row for row in heartbeat['stations'] if row['station_id'] == station.freo_station_id)['on_air']


def test_minute_tick_does_not_spend_request_budget_when_nothing_is_due(central):
    reporter, api = central
    reporter.tick()
    budget = installation().state['budget']
    for _ in range(15):
        reporter.tick()
    assert installation().state['budget'] == budget
    assert len(api.calls) == 4


def test_station_settings_country_directory_fields_and_uuid(app):
    client = admin_client(app)
    with app.app_context():
        identity = db.session.get(Station, 1).freo_station_id
    data = dict(csrf='test-admin-csrf-token', name='Local Radio', description='Local description',
                public_slug='local-radio', timezone='UTC', city='Perth', region='Western Australia',
                country='au', genre='Rock', directory_categories='Independent, Community', directory_opt_in='yes')
    assert client.post('/admin/stations/test-station/settings', data=data).status_code == 302
    with app.app_context():
        station = db.session.get(Station, 1)
        assert station.country == 'AU' and station.freo_station_id == identity
        assert station.directory_opt_in and station.directory_categories == ['Independent', 'Community']
    assert 'Western Australia, AU' in client.get('/player/local-radio').get_data(as_text=True)
    data['country'] = 'A1'
    assert client.post('/admin/stations/test-station/settings', data=data).status_code == 400


@pytest.mark.skipif(not os.environ.get('FREO_API_CONTRACT_SOURCE'), reason='Optional pinned API source validation')
def test_payloads_against_actual_server_validators(central):
    import importlib.util
    from pathlib import Path
    root = Path(os.environ['FREO_API_CONTRACT_SOURCE'])
    source = root / 'validation.py' if (root / 'validation.py').exists() else root / 'freo_api' / 'validation.py'
    spec = importlib.util.spec_from_file_location('freo_api_contract_validation', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reporter, api = central
    installation().registration_state = 'unconfigured'
    db.session.commit()
    now = int(time.time() // 3600) * 3600
    sample(now - 120)
    sample(now - 60)
    reporter.tick()
    from app.routes.central_api import queue_activation
    api.fail['/v1/activate'] = APIError('http_400', status=400)
    queue_activation('FREO-7K4P-M9Q2')
    reporter.tick()
    validators = {'/v1/enroll': module.Enrollment, '/v1/register': module.Registration, '/v1/stations/sync': module.StationSync,
                  '/v1/heartbeat': module.Heartbeat, '/v1/activate': module.Activation}
    for _, path, payload, _ in api.calls:
        if path in validators:
            validators[path].model_validate_json(json.dumps(payload))


def test_unicode_station_sync_batches_respect_wire_byte_limit():
    from app.services.central_api import sync_batches
    from app.services.central_api.client import MAX_BYTES
    payload = dict(station_id=str(uuid4()), name='📻' * 120, description='📻' * 500,
        genre='📻' * 100, categories=['📻' * 100 for _ in range(20)], city='📻' * 120, region='📻' * 120)
    items = [(None, payload) for _ in range(40)]
    batches = list(sync_batches(items))
    assert sum(len(batch) for batch in batches) == 40
    assert len(batches) > 2
    assert all(len(json.dumps({'stations': [item[1] for item in batch]}, separators=(',', ':')).encode()) <= MAX_BYTES for batch in batches)


def test_sampler_clock_rollback_does_not_double_count(central):
    now = int(time.time() // 3600) * 3600
    sample(now - 120)
    sample(now - 60)
    sample(now - 90)
    sample(now - 60)
    sample(now)
    metric = db.session.get(CentralHourlyMetric, (1, now - 3600))
    assert metric.observed_seconds == 120
    assert metric.listener_seconds == 4 * 120


def test_missing_observation_keeps_clock_high_watermark(central, monkeypatch):
    now = int(time.time() // 3600) * 3600
    sample(now - 120)
    sample(now - 60)
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (None, None))
    sample(now - 90)
    monkeypatch.setattr('app.services.central_api.metrics.observation', lambda slug: (True, 4))
    sample(now - 80)
    sample(now - 60)
    sample(now)
    metric = db.session.get(CentralHourlyMetric, (1, now - 3600))
    assert metric.observed_seconds == 60  # Unknown interval is never attributed twice.


def test_reporting_configuration_error_does_not_break_web(app):
    app.config['FREO_INSTALL_TYPE'] = 'misconfigured'
    assert app.test_client().get('/stations', follow_redirects=True).status_code == 200
    from app.services.central_api.metrics import machine_snapshot
    with app.app_context(), pytest.raises(APIError, match='invalid_install_type'):
        machine_snapshot()


def test_malformed_license_retains_last_successful_entitlement(central):
    reporter, api = central
    reporter.tick()
    saved = installation().license_cache
    installation().state = {}
    db.session.commit()
    api.entitlement = {'unexpected': 'response'}
    reporter.tick()
    assert installation().license_cache['entitlement'] == saved['entitlement']
    assert installation().license_cache['received_at'] == saved['received_at']
    assert installation().last_error == 'license:invalid_license_response'


def test_reporter_cli_and_hidden_credential_recovery(central, monkeypatch, app):
    reporter, api = central
    monkeypatch.setattr('app.routes.central_api.Reporter', lambda: reporter)
    runner = app.test_cli_runner()
    result = runner.invoke(args=['central-api', 'run', '--once'])
    assert result.exit_code == 0, result.output
    assert installation().installation_id == INSTALLATION_ID
    result = runner.invoke(args=['central-api', 'recover-credential', '--installation-id', INSTALLATION_ID], input=TOKEN + '\n')
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert reporter.store.read()['installation_id'] == INSTALLATION_ID


@pytest.mark.parametrize('existing', [False, True])
def test_owner_activation_preserves_identity_and_survives_restart(central, existing):
    from app.routes.central_api import queue_activation
    reporter, api = central
    if existing:
        reporter.tick()
    station_ids = [s.freo_station_id for s in Station.query]
    original_factory = api.factory
    exchanges = []
    profile_id = str(uuid4())

    def factory(url, token=None):
        original = original_factory(url, token)
        class Connection:
            def request(self, method, path, payload=None):
                if path != '/v1/activate':
                    return original.request(method, path, payload)
                exchanges.append((token, payload))
                result = dict(installation_id=INSTALLATION_ID, station_profile_id=profile_id,
                    token_type='Bearer', heartbeat_interval_seconds=3600,
                    server_time=iso(time.time()), license=api.entitlement)
                return result
        return Connection()

    reporter.client_factory = factory
    queue_activation('freo-7k4p-m9q2')
    reporter.tick()
    assert exchanges[0][0] == api.token
    assert exchanges[0][1]['activation_code'] == 'FREO-7K4P-M9Q2'
    assert reporter.store.read() == {'installation_id': INSTALLATION_ID, 'access_token': api.token}
    assert installation().state['owner_profile_id'] == profile_id
    assert 'activation' not in installation().state
    assert installation().registration_state == 'enrolled'
    assert [s.freo_station_id for s in Station.query] == station_ids
    Reporter(factory).tick()
    assert len(exchanges) == 1
    assert sum(path == '/v1/register' for _, path, _, _ in api.calls) == int(existing)


def test_activation_lost_response_retries_same_identity_after_backoff(central):
    from app.routes.central_api import queue_activation
    reporter, api = central
    queue_activation('FREO-7K4P-M9Q2')
    api.fail['/v1/activate'] = APIError('connection_or_response_error')
    reporter.tick()
    identity = reporter.store.read()
    reporter.tick()
    Reporter(api.factory).tick()
    assert sum(path == '/v1/enroll' for _, path, _, _ in api.calls) == 1
    assert sum(path == '/v1/activate' for _, path, _, _ in api.calls) == 1
    assert installation().registration_state == 'enrolled'
    assert 'activation' in installation().state
    assert all(s.enabled for s in Station.query)
    installation().state = dict(installation().state, claim={'due': 0})
    db.session.commit()
    Reporter(api.factory).tick()
    assert sum(path == '/v1/activate' for _, path, _, _ in api.calls) == 2
    assert reporter.store.read() == identity


def test_rejected_activation_allows_new_code_without_new_identity(central):
    from app.routes.central_api import queue_activation
    reporter, api = central
    api.fail['/v1/activate'] = APIError('http_400', status=400)
    queue_activation('FREO-7K4P-M9Q2')
    reporter.tick()
    identity = reporter.store.read()
    assert identity['installation_id'] == INSTALLATION_ID
    assert installation().registration_state == 'enrolled'
    assert 'activation' not in installation().state
    queue_activation('FREO-7K4P-M9Q3')
    reporter.tick()
    assert reporter.store.read() == identity
    assert sum(path == '/v1/enroll' for _, path, _, _ in api.calls) == 1


def test_activation_admin_csrf_and_code_not_reflected(app):
    client = admin_client(app)
    code = 'FREO-7K4P-M9Q2'
    assert client.post('/admin/installation', data={'action':'activate','activation_code':code}).status_code == 400
    client.get('/admin/installation')
    with client.session_transaction() as state:
        csrf = state['admin_csrf']
    assert client.post('/admin/installation', data={'csrf':csrf,'action':'activate','activation_code':code}).status_code == 302
    assert code not in client.get('/admin/installation').text
    with app.app_context():
        assert installation().registration_state == 'activation_queued'


def test_unconfigured_installation_enrolls_without_email(central):
    reporter, api = central
    row = installation()
    row.registration_state, row.manager_email = 'unconfigured', ''
    db.session.commit()
    reporter.tick()
    assert api.calls[0][1] == '/v1/enroll'
    assert set(api.calls[0][2]) == {'installation'}
    assert api.calls[0][3].startswith('freo_')
    assert row.installation_id == INSTALLATION_ID
    assert row.license_cache['entitlement']['status'] == 'active'
    assert any(path == '/v1/heartbeat' for _, path, _, _ in api.calls)
    identity = reporter.store.read()
    assert identity['access_token'] not in repr(row.state) + repr(row.license_cache)
    Reporter(api.factory).tick()
    assert reporter.store.read() == identity
    assert sum(path == '/v1/enroll' for _, path, _, _ in api.calls) == 1


def test_enrollment_lost_response_reuses_durable_token_across_restart(central):
    reporter, api = central
    installation().registration_state = 'unconfigured'
    db.session.commit()
    api.fail['/v1/enroll'] = APIError('connection_or_response_error')
    reporter.tick()
    saved = reporter.store.read()
    assert saved['enrollment_token'] == api.calls[0][3]
    Reporter(api.factory).tick()
    assert len(api.calls) == 1
    installation().state = dict(installation().state, enrollment={'due': 0})
    db.session.commit()
    del api.fail['/v1/enroll']
    Reporter(api.factory).tick()
    assert api.calls[1][3] == saved['enrollment_token']
    assert reporter.store.read()['access_token'] == saved['enrollment_token']
    assert installation().registration_state == 'enrolled'


def test_enrollment_credential_save_failure_prevents_network(central, monkeypatch):
    reporter, api = central
    installation().registration_state = 'unconfigured'
    db.session.commit()
    def fail_write(data):
        raise OSError('disk unavailable')
    monkeypatch.setattr(reporter.store, 'write', fail_write)
    with pytest.raises(OSError):
        reporter.tick()
    assert not api.calls


def test_enrollment_response_save_failure_recovers_same_identity(central, monkeypatch):
    reporter, api = central
    installation().registration_state = 'unconfigured'
    db.session.commit()
    write = reporter.store.write
    def fail_response(data):
        if 'installation_id' in data:
            raise OSError('disk unavailable')
        write(data)
    monkeypatch.setattr(reporter.store, 'write', fail_response)
    with pytest.raises(OSError):
        reporter.tick()
    pending = reporter.store.read()
    Reporter(api.factory).tick()
    assert reporter.store.read()['access_token'] == pending['enrollment_token']
    assert [token for _, path, _, token in api.calls if path == '/v1/enroll'] == [pending['enrollment_token']] * 2


def test_missing_pending_enrollment_credential_does_not_duplicate(central):
    reporter, api = central
    installation().registration_state = 'enrolling'
    db.session.commit()
    reporter.tick()
    assert not api.calls
    assert installation().last_error == 'credentials_missing_recovery_required'


def test_revoked_pending_enrollment_never_generates_replacement(central):
    reporter, api = central
    installation().registration_state = 'unconfigured'
    db.session.commit()
    api.fail['/v1/enroll'] = APIError('unauthorized', status=401)
    reporter.tick()
    saved = reporter.store.read()
    Reporter(api.factory).tick()
    assert len(api.calls) == 1 and reporter.store.read() == saved
    assert installation().registration_state == 'credentials_rejected'


def test_license_refresh_recovers_owner_link_after_lost_activation(central):
    reporter, api = central
    reporter.tick()
    profile_id = str(uuid4())
    api.entitlement['station_profile_id'] = profile_id
    Reporter(api.factory).tick()
    assert installation().state['owner_profile_id'] == profile_id


def test_reporting_does_not_mark_installation_registered(app, central):
    reporter, api = central
    row = installation()
    row.registration_state, row.manager_email = 'unconfigured', ''
    api.entitlement.update(station_profile_id=None, registration_status='unregistered')
    db.session.commit()
    reporter.tick()
    client = admin_client(app)
    page = client.get('/admin/installation').text
    assert 'Registration: <strong>Unregistered</strong>' in page
    assert 'Registered with Freo' not in page
    identity = reporter.store.read()
    api.entitlement.update(station_profile_id=str(uuid4()), registration_status='registered')
    Reporter(api.factory).tick()
    assert 'Registration: <strong>Registered with Freo</strong>' in client.get('/admin/installation').text
    assert reporter.store.read() == identity
    assert all(s.enabled for s in Station.query)


@pytest.mark.parametrize('registered', [False, True])
def test_community_entitlement_reports_without_purchase(central, registered):
    reporter, api = central
    row = installation()
    row.registration_state, row.manager_email = 'unconfigured', ''
    api.entitlement.update(plan='free', channel_limit=2, expires_at=None, renews_at=None,
        station_profile_id=str(uuid4()) if registered else None,
        registration_status='registered' if registered else 'unregistered')
    db.session.commit()
    reporter.tick()
    assert [path for _, path, _, _ in api.calls] == ['/v1/enroll', '/v1/license', '/v1/stations/sync', '/v1/heartbeat']
    assert row.license_cache['entitlement'] == api.entitlement
    assert bool(row.state['owner_profile_id']) is registered
    assert row.state['last_heartbeat']['stations_accepted'] == Station.query.count()


@pytest.mark.parametrize('cached', [False, True])
def test_license_unavailable_preserves_cache_and_allows_reporting(central, cached):
    reporter, api = central
    row = installation()
    row.registration_state, row.manager_email = 'unconfigured', ''
    if cached:
        reporter.tick()
        row.state = dict(row.state, license={'due': 0}, report={'due': 0})
    db.session.commit()
    previous = row.license_cache
    api.calls.clear()
    api.fail['/v1/license'] = APIError('license_unavailable', status=503)
    reporter.tick()
    if cached:
        assert row.license_cache['entitlement'] == previous['entitlement']
        assert row.license_cache['received_at'] == previous['received_at']
    else:
        assert row.license_cache is None
    assert any(path == '/v1/heartbeat' for _, path, _, _ in api.calls)
    assert all(s.enabled for s in Station.query)
    assert row.state['license']['failures'] == 1
    assert not row.state['license']['blocked']


def test_heartbeat_receipt_is_validated_durable_and_private(central, caplog, monkeypatch):
    import logging
    # Alembic's logging configuration in earlier migration tests may disable
    # existing application loggers. Keep this assertion independent of order.
    from flask import current_app
    monkeypatch.setattr(current_app.logger, 'disabled', False)
    reporter, api = central
    with caplog.at_level(logging.INFO):
        reporter.tick()
    receipt = dict(installation().state['last_heartbeat'])
    assert receipt['next_heartbeat_seconds'] == 3600
    assert receipt['stations_accepted'] == 2
    assert receipt['metrics_accepted'] == 0
    assert receipt['server_time'] in caplog.text
    assert TOKEN not in caplog.text
    Reporter(api.factory).tick()
    refreshed = dict(installation().state['last_heartbeat'])
    assert refreshed['server_time'] >= receipt['server_time']
    assert refreshed['freo_version'] == receipt['freo_version']
    receipt = refreshed
    class InvalidHeartbeat:
        def request(self, method, path, payload):
            return dict(server_time=iso(time.time()), stations_accepted=999,
                        metrics_accepted=0, next_heartbeat_seconds=3600)
    with pytest.raises(APIError, match='invalid_heartbeat_response'):
        reporter.heartbeat(installation(), InvalidHeartbeat(), [])
    assert installation().state['last_heartbeat'] == receipt


def test_empty_installation_reports_presence(central):
    reporter, api = central
    db.session.remove()
    db.drop_all()
    db.create_all()
    reporter.tick()
    heartbeat = next(payload for _, path, payload, _ in api.calls if path == '/v1/heartbeat')
    from app.version import VERSION
    assert heartbeat['installation']['freo_version'] == VERSION
    assert heartbeat['stations'] == []
    assert installation().state['last_heartbeat']['stations_accepted'] == 0
