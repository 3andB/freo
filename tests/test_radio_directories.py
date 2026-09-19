import ipaddress
import json
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from app.extensions import db
from app.models import Station, StationLogo, AdminUser
from app.services import radio_directories as directories, icecast_directory as yp
from tests.test_web import app, admin_client

BASE = '/admin/stations/test-station/settings/directories/'
CSRF = {'csrf': 'test-admin-csrf-token'}
UUID = '550e8400-e29b-41d4-a716-446655440000'


@pytest.fixture
def public_app(app, monkeypatch):
    app.config['PUBLIC_BASE_URL'] = 'https://radio.example.org'
    monkeypatch.setattr(directories, 'addresses', lambda host: {ipaddress.ip_address('8.8.8.8')})
    monkeypatch.setattr(directories, 'radio_browser_server', lambda: 'de1.api.radio-browser.info')
    with app.app_context():
        for row in Station.query.all():
            row.genre = 'Jazz'
        db.session.commit()
    return app


def station():
    return Station.query.filter_by(slug='test-station').one()


def config():
    return b'''<icecast><hostname>localhost</hostname><admin>operator@example.org</admin><authentication><admin-password>private-secret</admin-password></authentication>
      <!-- preserve me --><limits><clients>432</clients></limits><listen-socket><port>8001</port><bind-address>127.0.0.1</bind-address></listen-socket>
      <mount type="normal"><mount-name>/test-station</mount-name><password>source-secret</password><max-listeners>12</max-listeners></mount>
      <mount type="normal"><mount-name>/second-station</mount-name><password>other-secret</password></mount></icecast>'''


def test_submission_metadata_success_and_no_resubmit(public_app, monkeypatch):
    add = Mock(return_value=UUID)
    monkeypatch.setattr(directories, 'radio_browser_add', add)
    with public_app.app_context():
        row = station()
        row.country, row.genre, row.directory_categories = 'AU', 'Jazz', ['Jazz', 'Soul']
        row.logo = StationLogo(image=b'png', thumbnail=b'png', version='v1')
        db.session.commit()
    client = admin_client(public_app)
    assert client.post(BASE + 'radio-browser', data=CSRF).status_code == 303
    assert add.call_args.args[1] == {'name': 'Test Station', 'url': 'https://radio.example.org/stream/test-station',
        'homepage': 'https://radio.example.org/player/test-station',
        'favicon': 'https://radio.example.org/station-assets/test-station/logo.png', 'countrycode': 'AU', 'tags': 'Jazz,Soul'}
    assert client.post(BASE + 'radio-browser', data=CSRF).status_code == 303
    assert add.call_count == 1
    with public_app.app_context():
        assert station().radio_browser_uuid == UUID
        assert not Station.query.filter_by(slug='second-station').one().radio_browser_uuid
        assert not station().directory_opt_in
    page = client.get('/admin/stations/test-station/settings').text
    assert 'Listing active' in page and 'List My Station' not in page


@pytest.mark.parametrize('error,status,retry', [(OSError('secret-token'), 'error', True),
    (directories.SubmissionRejected(), 'error', True), (directories.SubmissionUncertain('secret-token'), 'uncertain', False)])
def test_submission_failure_is_local_safe_and_durable(public_app, monkeypatch, caplog, error, status, retry):
    add = Mock(side_effect=error)
    monkeypatch.setattr(directories, 'radio_browser_add', add)
    client = admin_client(public_app)
    client.post(BASE + 'radio-browser', data=CSRF)
    with public_app.app_context():
        assert station().radio_browser_status == status
        assert station().desired_state == 'running'
        assert station().radio_browser_uuid is None
    page = client.get('/admin/stations/test-station/settings').text
    assert ('List My Station' in page) == retry
    assert 'secret-token' not in page + caplog.text
    if not retry:
        client.post(BASE + 'radio-browser', data=CSRF)
        assert add.call_count == 1


def test_concurrent_claim_blocks_second_submission(public_app, monkeypatch):
    with public_app.app_context():
        row = station()
        row.radio_browser_status = 'submitting'
        db.session.commit()
    add = Mock()
    monkeypatch.setattr(directories, 'radio_browser_add', add)
    admin_client(public_app).post(BASE + 'radio-browser', data=CSRF)
    add.assert_not_called()


def test_simultaneous_submissions_make_one_api_call(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app import create_app
    from app.models import StreamMount
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'claims.sqlite'))
    monkeypatch.setenv('FREO_ENV_FILE', '/dev/null')
    application = create_app('testing')
    application.config['PUBLIC_BASE_URL'] = 'https://radio.example.org'
    with application.app_context():
        db.create_all()
        db.session.add(Station(name='Station', slug='station', stream=StreamMount()))
        db.session.add(AdminUser(email='test@example.org', password_hash='unused'))
        db.session.commit()
    monkeypatch.setattr(directories, 'addresses', lambda host: {ipaddress.ip_address('8.8.8.8')})
    monkeypatch.setattr(directories, 'radio_browser_server', lambda: 'de1.api.radio-browser.info')
    add = Mock(return_value=UUID)
    monkeypatch.setattr(directories, 'radio_browser_add', add)
    barrier = Barrier(2)
    original = directories.metadata
    def concurrent_metadata(row):
        result = original(row)
        barrier.wait(timeout=5)
        return result
    monkeypatch.setattr(directories, 'metadata', concurrent_metadata)
    def submit(_):
        with application.app_context():
            try:
                directories.submit_radio_browser(Station.query.one(), AdminUser.query.one())
                return True
            except ValueError:
                return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, range(2)))
    assert sorted(results) == [False, True]
    assert add.call_count == 1
    with application.app_context():
        assert Station.query.one().radio_browser_uuid == UUID


@pytest.mark.parametrize('url', ['http://127.0.0.1:8001', 'http://[::1]', 'http://10.0.0.1', 'http://169.254.169.254',
    'http://localhost', 'https://radio.local', 'https://user:password@radio.example.org', 'https://radio.example.org?token=secret',
    'https://radio.example.org/#secret', 'file:///etc/passwd', '/stream/test-station', 'https://radio.example.org\n'])
def test_private_or_credential_urls_never_submitted(public_app, monkeypatch, url):
    public_app.config['PUBLIC_BASE_URL'] = url
    add = Mock()
    monkeypatch.setattr(directories, 'radio_browser_add', add)
    admin_client(public_app).post(BASE + 'radio-browser', data=CSRF)
    add.assert_not_called()


def test_private_dns_and_missing_required_fields(public_app, monkeypatch):
    with public_app.test_request_context():
        row = station()
        monkeypatch.setattr(directories, 'addresses', lambda host: {ipaddress.ip_address('10.0.0.5')})
        with pytest.raises(ValueError): directories.metadata(row)
        monkeypatch.setattr(directories, 'addresses', lambda host: {ipaddress.ip_address('8.8.8.8')})
        row.name = ''
        with pytest.raises(ValueError): directories.metadata(row)
        row.name = 'Name'
        row.enabled = False
        with pytest.raises(ValueError): directories.metadata(row)


@pytest.mark.parametrize('directory', ['radio-browser', 'internet-radio'])
def test_authorization_csrf_and_get_no_side_effect(public_app, monkeypatch, directory):
    add = Mock()
    monkeypatch.setattr(directories, 'radio_browser_add', add)
    url = BASE + directory
    assert public_app.test_client().post(url, data=CSRF).status_code == 302
    client = admin_client(public_app)
    assert client.post(url, data={'enabled': 'yes'}).status_code == 400
    assert client.get(url).status_code == 405
    add.assert_not_called()


@pytest.mark.parametrize('body', [{'ok': True, 'uuid': UUID}, {'ok': False, 'message': 'secret'},
    {'ok': True, 'uuid': 'bad'}, [], 'not-json'])
def test_api_protocol_timeouts_response_validation(monkeypatch, body):
    connection = Mock()
    raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    connection.getresponse.return_value = SimpleNamespace(status=200, read=lambda size: raw)
    factory = Mock(return_value=connection)
    monkeypatch.setattr(directories.http.client, 'HTTPSConnection', factory)
    if isinstance(body, dict) and body.get('uuid') == UUID:
        assert directories.radio_browser_add('de1.api.radio-browser.info', {'name': 'A & B', 'url': 'https://radio.example.org/stream/a'}) == UUID
    else:
        with pytest.raises((directories.SubmissionRejected, directories.SubmissionUncertain)):
            directories.radio_browser_add('de1.api.radio-browser.info', {})
    assert factory.call_args.kwargs['timeout'] == 5
    connection.sock.settimeout.assert_called_once_with(10)
    assert connection.request.call_args.args == ('POST', '/json/add')
    assert 'Authorization' not in connection.request.call_args.kwargs['headers']
    connection.close.assert_called_once()


def test_yp_config_preserves_secrets_and_isolates_mounts(public_app):
    with public_app.test_request_context():
        row = station()
        row.name = 'Jazz <&> "radio"'
        enabled = yp.directory_config(config(), row, True)
        root = yp.parse_config(enabled)
        mounts = {m.findtext('mount-name'): m for m in root.findall('mount')}
        assert root.findtext('authentication/admin-password') == 'private-secret'
        assert root.findtext('limits/clients') == '432'
        assert mounts['/test-station'].findtext('password') == 'source-secret'
        assert mounts['/test-station'].findtext('max-listeners') == '12'
        assert mounts['/test-station'].findtext('stream-name') == row.name
        assert mounts['/test-station'].findtext('public') == '1'
        assert mounts['/second-station'].findtext('public') == '0'
        assert mounts[None].findtext('public') == '0'
        assert b'preserve me' in enabled
        assert yp.directory_config(enabled, row, True) == enabled
        disabled = yp.parse_config(yp.directory_config(enabled, row, False))
        assert disabled.find('yp-directory') is not None
        assert all(m.findtext('public') == '0' for m in disabled.findall('mount'))
        assert disabled.findtext('listen-socket/bind-address') == '127.0.0.1'


@pytest.mark.parametrize('extra', ['<directory><yp-url>https://other.example.org</yp-url></directory>',
    '<mount><mount-name>/test-station</mount-name></mount>'])
def test_yp_rejects_conflicts(public_app, extra):
    with public_app.test_request_context():
        with pytest.raises(ValueError):
            yp.directory_config(config().replace(b'</icecast>', extra.encode() + b'</icecast>'), station(), True)


def test_yp_cluster_credentials_never_advertised(public_app):
    raw = config().replace(b'<max-listeners>', b'<cluster-password>secret</cluster-password><max-listeners>')
    with public_app.test_request_context():
        with pytest.raises(ValueError): yp.directory_config(raw, station(), True)


def test_yp_missing_metadata_contact_and_changed_origin(public_app):
    with public_app.app_context():
        row = station()
        with pytest.raises(ValueError, match='technical contact'):
            yp.directory_config(config().replace(b'operator@example.org', b'operator@localhost'), row, True)
        row.genre = ''
        with pytest.raises(ValueError, match='genre'):
            yp.directory_config(config(), row, True)
        row.genre = 'Jazz'
        enabled = yp.directory_config(config(), row, True)
        public_app.config['PUBLIC_BASE_URL'] = 'https://new.example.org'
        with pytest.raises(ValueError, match='Public origin changed'):
            yp.directory_config(enabled, row, True)
        disabled = yp.directory_config(enabled, row, False)
        replaced = yp.parse_config(yp.directory_config(disabled, row, True))
        assert replaced.find(f"listen-socket[@id='{yp.SOCKET_ID}']/bind-address").text == 'new.example.org'


def test_yp_queue_apply_failure_rollback_and_noop(public_app, monkeypatch, tmp_path):
    monkeypatch.setattr(yp.runtime, 'ROOT', tmp_path)
    monkeypatch.setattr(yp.runtime, 'require_root', lambda: None)
    def stage(path, data, *args):
        target = path.with_suffix('.staged')
        target.write_text(data)
        return target
    monkeypatch.setattr(yp.runtime, 'atomic_install', stage)
    commands = Mock()
    monkeypatch.setattr(yp.runtime, 'run_checked', commands)
    path = tmp_path / 'radio/icecast.xml'
    path.parent.mkdir()
    path.write_bytes(config())
    client = admin_client(public_app)
    assert client.get('/test-station').status_code == 404
    client.post(BASE + 'internet-radio', data=dict(CSRF, enabled='yes'))
    with public_app.test_request_context():
        assert not station().internet_radio_enabled
        assert station().internet_radio_status == 'pending'
        assert yp.process_pending_directories() == []
        assert station().internet_radio_enabled
    assert client.get('/test-station').headers['Location'] == '/stream/test-station'
    assert client.get('/second-station').status_code == 404
    commands.assert_called_once_with(['/bin/systemctl', 'reload', 'icecast2.service'])
    client.post(BASE + 'internet-radio', data=dict(CSRF, enabled='yes'))
    with public_app.app_context(): assert yp.process_pending_directories() == []
    assert commands.call_count == 1
    working = path.read_bytes()
    client.post(BASE + 'internet-radio', data=dict(CSRF, enabled='no'))
    commands.side_effect = [OSError('secret'), None]
    with public_app.app_context():
        assert yp.process_pending_directories() == [station().id]
        assert station().internet_radio_enabled
        assert station().internet_radio_status == 'failed'
        assert 'secret' not in station().internet_radio_error
    assert path.read_bytes() == working
    commands.side_effect = None
    client.post(BASE + 'internet-radio', data=dict(CSRF, enabled='no'))
    with public_app.app_context():
        assert yp.process_pending_directories() == []
        assert not station().internet_radio_enabled
    assert client.get('/test-station').status_code == 404


def test_invalid_config_never_installed_or_reloaded(public_app, monkeypatch, tmp_path):
    monkeypatch.setattr(yp.runtime, 'ROOT', tmp_path)
    path = tmp_path / 'radio/icecast.xml'
    path.parent.mkdir()
    path.write_bytes(config())
    command = Mock()
    monkeypatch.setattr(yp.runtime, 'run_checked', command)
    with pytest.raises(ET.ParseError): yp.apply_config(b'<icecast>')
    assert path.read_bytes() == config()
    command.assert_not_called()


def test_documented_dns_discovery(monkeypatch):
    resolver = Mock(return_value=[SimpleNamespace(target='de1.api.radio-browser.info.'), SimpleNamespace(target='attacker.example.org.')])
    monkeypatch.setattr(directories.dns.resolver, 'resolve', resolver)
    assert directories.radio_browser_server() == 'de1.api.radio-browser.info'
    resolver.assert_called_once_with('_api._tcp.radio-browser.info.', 'SRV', lifetime=3, search=False)


@pytest.mark.parametrize('status,body,error', [(500, b'private failure', None), (302, b'', None),
    (200, b'x' * 16385, None), (200, b'', TimeoutError('secret'))])
def test_api_network_http_redirect_and_oversize_fail_closed(monkeypatch, status, body, error):
    connection = Mock()
    connection.getresponse.return_value = SimpleNamespace(status=status, read=lambda size: body)
    connection.getresponse.side_effect = error
    monkeypatch.setattr(directories.http.client, 'HTTPSConnection', lambda *a, **kw: connection)
    with pytest.raises(directories.SubmissionUncertain): directories.radio_browser_add('de1.api.radio-browser.info', {})
    assert connection.request.call_count == 1


def test_yp_two_opted_mounts_disable_one_preserves_other(public_app):
    with public_app.app_context():
        first = station()
        other = Station.query.filter_by(slug='second-station').one()
        raw = yp.directory_config(config(), first, True)
        raw = yp.directory_config(raw, other, True)
        raw = yp.directory_config(raw, first, False)
        root = yp.parse_config(raw)
        assert root.find('yp-directory') is not None
        values = {m.findtext('mount-name'): m.findtext('public') for m in root.findall('mount')}
        assert values == {'/test-station': '0', '/second-station': '1', None: '0'}


def test_public_redirect_is_station_scoped_and_routes_cannot_be_shadowed(public_app):
    client = admin_client(public_app)
    with public_app.app_context():
        row = station()
        row.slug = 'stations'
        db.session.commit()
    client.post(BASE.replace('test-station', 'stations') + 'internet-radio', data=dict(CSRF, enabled='yes'))
    with public_app.app_context():
        assert Station.query.filter_by(slug='stations').one().internet_radio_pending is None
    assert client.get('/stations').status_code != 307


def test_renderer_preserves_directory_settings_on_provision(public_app, monkeypatch, tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('radio_renderer', Path(__file__).resolve().parents[1] / 'scripts/render-radio-config.py')
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    radio = tmp_path / 'radio'
    secrets = tmp_path / 'secrets'
    station_secrets = secrets / 'stations'
    radio.mkdir()
    station_secrets.mkdir(parents=True)
    keys = secrets / 'engine.json'
    keys.write_text(json.dumps({key: 'a' * 64 for key in ('source', 'relay', 'admin')}))
    keys.chmod(0o600)
    for slug in ('test-station', 'second-station', 'new-station'):
        path = station_secrets / (slug + '.json')
        path.write_text(json.dumps({'source': 'b' * 64}))
        path.chmod(0o600)
    with public_app.app_context():
        original = yp.directory_config(config(), station(), True)
    (radio / 'icecast.xml').write_bytes(original)
    monkeypatch.setattr(renderer, 'ROOT', tmp_path)
    monkeypatch.setattr(renderer, 'RADIO', radio)
    monkeypatch.setattr(renderer, 'SECRETS', secrets)
    monkeypatch.setattr(renderer, 'KEYS', keys)
    monkeypatch.setattr(renderer.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(renderer.os, 'chown', lambda *a: None)
    monkeypatch.setattr(renderer.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
    renderer.main()
    root = yp.parse_config((radio / 'icecast.xml').read_bytes())
    assert root.find('yp-directory').get('url') == yp.YP_URL
    mounts = {m.findtext('mount-name'): m for m in root.findall('mount')}
    assert mounts['/test-station'].findtext('public') == '1'
    assert mounts['/new-station'].findtext('public') == '0'
    assert root.findtext('authentication/admin-password') == 'private-secret'


def test_additive_migration_preserves_station_and_defaults(monkeypatch):
    import importlib
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    migration = importlib.import_module('migrations.versions.a71d25b609ef_public_radio_directories')
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE stations (id INTEGER PRIMARY KEY, name TEXT)'))
        connection.execute(text("INSERT INTO stations VALUES (1, 'Existing')"))
        monkeypatch.setattr(migration, 'op', Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        row = connection.execute(text('SELECT * FROM stations')).mappings().one()
        assert row['name'] == 'Existing'
        assert row['radio_browser_uuid'] is None and row['radio_browser_status'] == 'not_listed'
        assert row['internet_radio_enabled'] == 0 and row['internet_radio_pending'] is None
        migration.downgrade()
        assert connection.execute(text('SELECT * FROM stations')).one() == (1, 'Existing')
