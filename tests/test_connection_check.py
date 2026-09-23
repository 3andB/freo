"""Manual checks are durable, bounded and isolated from broadcasting."""
import copy
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from packaging.version import Version

from app import create_app
from app.extensions import db
from app.models import CentralConnectionCheck, Station
from app.services.central_api import Reporter, installation
from app.services.central_api.client import APIError, Client
from app.services.central_api.connection_check import queue_check, check_status
from app.services.operations import connection
from app.version import VERSION
from tests.test_central_api import central
from tests.test_web import app, admin_client

URL = '/admin/installation/check-connection'


def post_check(client):
    return client.post(URL, data={'csrf': 'test-admin-csrf-token'}, headers={'Accept': 'application/json'})


def test_queue_requires_admin_csrf_and_never_contacts_api(app, monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail('Web requests must never call the mothership')
    monkeypatch.setattr(Client, 'request', no_network)
    assert app.test_client().post(URL).status_code == 302
    client = admin_client(app)
    assert client.post(URL).status_code == 400
    assert client.get(URL).status_code == 405
    with app.app_context():
        assert CentralConnectionCheck.query.count() == 0
    response = post_check(client)
    assert response.status_code == 202
    assert response.json['status'] == 'queued' and response.json['busy']
    assert response.headers['Cache-Control'] == 'private, no-store'
    duplicate = post_check(client)
    assert duplicate.status_code == 200
    assert duplicate.json['request_id'] == response.json['request_id']
    with app.app_context():
        assert CentralConnectionCheck.query.count() == 1


def test_native_form_queues_and_returns_to_overview(app):
    response = admin_client(app).post(URL, data={'csrf': 'test-admin-csrf-token'})
    assert response.status_code == 302 and response.headers['Location'] == '/admin'


def test_concurrent_clicks_create_only_one_request(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'checks.sqlite'))
    monkeypatch.setenv('SECRET_KEY', 'test-only')
    application = create_app('testing')
    with application.app_context():
        db.create_all()
    def race(now):
        barrier = Barrier(2)
        def submit():
            with application.app_context():
                barrier.wait(timeout=5)
                return queue_check(now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(submit) for _ in range(2)]
            assert sorted(job.result(timeout=10) for job in jobs) == [False, True]
    race(100)
    with application.app_context():
        row = db.session.get(CentralConnectionCheck, 1)
        first = row.request_id
        row.status = 'succeeded'
        db.session.commit()
        assert not queue_check(159)
    race(161)
    with application.app_context():
        assert CentralConnectionCheck.query.count() == 1
        assert db.session.get(CentralConnectionCheck, 1).request_id != first


def test_manual_check_refreshes_before_hourly_due_and_preserves_identity(central):
    reporter, api = central
    reporter.tick()
    row = installation()
    old_receipt = copy.deepcopy(row.state['last_heartbeat'])
    identity = reporter.store.read()
    api.calls.clear()
    api.heartbeat_fields = {'latest_version': '0.2.0', 'update_available': True}
    api.entitlement['channel_limit'] = 4
    station = Station.query.first()
    station.description = 'Changed metadata'
    db.session.commit()
    assert queue_check()
    request_id = check_status()['request_id']
    # Restart before processing must retain the queued request.
    reporter = Reporter(api.factory)
    assert reporter.process_connection_check()
    assert [call[1] for call in api.calls] == ['/v1/license', '/v1/stations/sync', '/v1/heartbeat']
    check = db.session.get(CentralConnectionCheck, 1)
    assert check.request_id == request_id and check.status == 'succeeded'
    assert check.result['latest_version'] == '0.2.0' and check.result['update_available'] is True
    assert check.result['version_source'] == 'heartbeat'
    assert check.result['checked_at'] == row.state['last_heartbeat']['server_time']
    assert row.state['last_heartbeat'] != old_receipt
    assert row.license_cache['entitlement']['channel_limit'] == 4
    assert reporter.store.read() == identity
    assert 3595 < row.state['report']['due'] - time.time() <= 3660
    assert not reporter.process_connection_check()
    reporter.tick()
    assert len(api.calls) == 3
    panel = connection(Station.query.all(), time.time())
    assert panel['connected'] and panel['update_status'] == 'Update available'
    assert panel['installed_version'] == VERSION


def test_manual_check_can_automatically_enroll_without_owner_or_paid_license(central):
    reporter, api = central
    row = installation()
    row.registration_state, row.manager_email = 'unconfigured', ''
    api.entitlement.update(plan='free', station_profile_id=None, registration_status='unregistered')
    db.session.commit()
    queue_check()
    reporter.process_connection_check()
    assert check_status()['status'] == 'succeeded'
    assert [call[1] for call in api.calls] == ['/v1/enroll', '/v1/license', '/v1/stations/sync', '/v1/heartbeat']
    assert not row.state.get('owner_profile_id')


def test_license_failure_does_not_prevent_a_successful_manual_heartbeat(central):
    reporter, api = central
    reporter.tick()
    cache = copy.deepcopy(installation().license_cache)
    api.fail['/v1/license'] = APIError('http_503', status=503)
    queue_check()
    reporter.process_connection_check()
    assert check_status()['status'] == 'succeeded'
    assert 'License refresh unavailable' in check_status()['message']
    assert installation().license_cache['entitlement'] == cache['entitlement']
    assert installation().license_cache['received_at'] == cache['received_at']


def test_existing_license_backoff_is_shown_as_partial_result(central):
    reporter, api = central
    reporter.tick()
    row = installation()
    row.state = dict(row.state, license={'failures': 1, 'due': time.time() + 300})
    db.session.commit()
    api.calls.clear()
    queue_check()
    reporter.process_connection_check()
    assert check_status()['status'] == 'succeeded'
    assert 'License refresh unavailable' in check_status()['message']
    assert [call[1] for call in api.calls] == ['/v1/heartbeat']


@pytest.mark.parametrize('fallback', [True, False])
def test_failed_heartbeat_is_not_success_and_public_version_is_separate(central, fallback):
    reporter, api = central
    reporter.tick()
    row = installation()
    receipt = copy.deepcopy(row.state['last_heartbeat'])
    cache = copy.deepcopy(row.license_cache)
    identity = reporter.store.read()
    stations = [(s.id, s.enabled, s.desired_state) for s in Station.query]
    api.fail['/v1/heartbeat'] = APIError('connection_or_response_error')
    api.fail['/v1/license'] = APIError('http_503', status=503)
    newer_version = f'{Version(VERSION).major + 1}.0.0'
    api.release = {'latest_version': newer_version}
    if not fallback:
        api.fail['/v1/releases/latest'] = APIError('connection_or_response_error')
    queue_check()
    reporter.process_connection_check()
    assert check_status()['status'] == 'failed'
    assert row.state['last_heartbeat'] == receipt
    assert row.license_cache['entitlement'] == cache['entitlement']
    assert reporter.store.read() == identity
    assert [(s.id, s.enabled, s.desired_state) for s in Station.query] == stations
    panel = connection(Station.query.all(), time.time())
    assert not panel['connected']
    assert panel['last_contact'] == receipt['server_time']
    if fallback:
        assert panel['latest_version'] == newer_version
        assert panel['update_status'] == 'Update available'
        assert panel['version_source'] == 'Public release discovery'
    else:
        assert panel['update_status'] == 'Unknown'
        assert 'Version check unavailable' in check_status()['message']


@pytest.mark.parametrize('limit', ['retry_after', 'budget', 'report_backoff', 'credentials'])
def test_manual_checks_respect_retry_limits_and_never_reset_credentials(central, limit):
    reporter, api = central
    reporter.tick()
    row = installation()
    now = time.time()
    if limit == 'retry_after':
        row.state = dict(row.state, retry_after=now + 7200)
    elif limit == 'budget':
        row.state = dict(row.state, budget={'hour': int(now // 3600), 'reserved': 90})
    elif limit == 'report_backoff':
        row.state = dict(row.state, report={'due': now + 3600, 'failures': 2})
    else:
        row.registration_state = 'credentials_rejected'
    db.session.commit()
    api.calls.clear()
    credentials = reporter.store.read()
    queue_check(now)
    reporter.process_connection_check(now)
    assert check_status()['status'] == 'failed'
    assert not any(call[1] == '/v1/heartbeat' for call in api.calls)
    assert reporter.store.read() == credentials
    if limit in ('retry_after', 'budget'):
        assert not api.calls
        assert check_status()['retry_at'] > now + 60
    else:
        assert any(call[1] == '/v1/releases/latest' for call in api.calls)
    if limit == 'credentials':
        assert row.registration_state == 'credentials_rejected'


def test_retry_after_from_failed_call_prevents_public_fallback(central):
    reporter, api = central
    reporter.tick()
    api.calls.clear()
    api.fail['/v1/heartbeat'] = APIError('http_429', status=429, retry_after=120)
    queue_check()
    reporter.process_connection_check()
    assert not any(call[1] == '/v1/releases/latest' for call in api.calls)
    assert check_status()['retry_at'] > time.time() + 110


def test_interrupted_check_reports_failure_without_repeating_requests(central):
    reporter, api = central
    queue_check()
    row = db.session.get(CentralConnectionCheck, 1)
    row.status = 'checking'
    db.session.commit()
    Reporter(api.factory).process_connection_check()
    assert check_status()['status'] == 'failed'
    assert 'interrupted' in check_status()['message']
    assert not api.calls


def test_unexpected_worker_error_finishes_check_without_secret_output(central, monkeypatch):
    reporter, api = central
    def fail(*args, **kwargs):
        raise OSError('secret-token-do-not-print')
    monkeypatch.setattr(reporter, 'tick', fail)
    queue_check()
    reporter.process_connection_check()
    assert check_status()['status'] == 'failed'
    assert 'secret-token' not in str(check_status())


def test_offline_reporter_shows_waiting_and_old_results_not_success(central):
    reporter, api = central
    reporter.tick()
    now = time.time()
    queue_check(now)
    assert check_status(now + 121)['status'] == 'queued'
    assert 'Waiting for the background reporter' in check_status(now + 121)['message']
    assert not queue_check(now + 121)


def test_public_fallback_retry_after_is_durable(central):
    reporter, api = central
    reporter.tick()
    api.fail['/v1/heartbeat'] = APIError('http_503', status=503)
    api.fail['/v1/releases/latest'] = APIError('http_429', status=429, retry_after=600)
    queue_check()
    reporter.process_connection_check()
    assert installation().state['retry_after'] > time.time() + 590
    assert check_status()['retry_at'] > time.time() + 590


def test_manual_check_migration_preserves_installation(app, monkeypatch):
    # Exercise the actual new migration against an existing populated schema.
    from app.models import CentralInstallation
    from sqlalchemy import inspect
    import logging.config
    # Alembic's CLI logging setup must not disable pytest's application log capture.
    monkeypatch.setattr(logging.config, 'fileConfig', lambda *args, **kwargs: None)
    with app.app_context():
        installation().license_cache = {'sentinel': 'cached-license'}
        db.session.commit()
        CentralConnectionCheck.__table__.drop(db.engine)
    runner = app.test_cli_runner()
    for args in (['db', 'stamp', 'd91f3a26b807'], ['db', 'upgrade', 'ab31e76f209d']):
        result = runner.invoke(args=args)
        assert result.exit_code == 0, result.output
    with app.app_context():
        assert 'central_connection_check' in inspect(db.engine).get_table_names()
        assert db.session.get(CentralInstallation, 1).license_cache == {'sentinel': 'cached-license'}
        assert queue_check()
    result = runner.invoke(args=['db', 'downgrade', 'd91f3a26b807'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert 'central_connection_check' not in inspect(db.engine).get_table_names()
        assert db.session.get(CentralInstallation, 1).license_cache == {'sentinel': 'cached-license'}


def test_queue_polling_preserves_minute_ticks_and_backs_off_on_errors(app, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import app.routes.central_api as routes
    clock, polls, ticks = [0], [], []
    class Worker:
        store = SimpleNamespace(lock=nullcontext)
        def process_connection_check(self):
            polls.append(clock[0])
            if clock[0] == 66:
                raise OSError('database unavailable')
            return clock[0] == 4
        def tick(self):
            ticks.append(clock[0])
    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= 126:
            raise KeyboardInterrupt()
    monkeypatch.setattr(routes, 'Reporter', Worker)
    monkeypatch.setattr(routes.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(routes.time, 'sleep', sleep)
    result = app.test_cli_runner().invoke(args=['central-api', 'run'])
    assert result.exit_code == 1  # Controlled loop termination.
    assert ticks == [0, 64]  # Manual work at t=4 defers the next regular sample.
    assert polls == list(range(0, 68, 2))
    assert clock[0] == 126  # Infrastructure errors retain the previous 60-second backoff.
