"""Offline entitlements and the boundary between station admins and root upgrades."""
import base64
from copy import deepcopy
from io import BytesIO
import json
import uuid
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.test_web import app, admin_client
from app.extensions import db
from app.models import AdminUser, SoftwareLicense, SystemUpgrade
from app.services import software_license
from app.services.stations import create_station

@pytest.fixture
def signed(app):
    key = Ed25519PrivateKey.generate()
    app.config['FREO_LICENSE_PUBLIC_KEYS'] = {'fixture': base64.b64encode(key.public_key().public_bytes_raw()).decode()}
    payload = dict(license_id=str(uuid.uuid4()), owner='Fixture purchaser', issued_at='2000-01-01T00:00:00+00:00',
                   product='Freo', edition='unlimited', updates='all-future', installations='all-owned', expires=None)
    def sign(payload):
        return dict(payload=payload, key_id='fixture', signature=base64.b64encode(key.sign(software_license.signing_bytes(payload))).decode())
    return sign(payload), sign


def operator(app):
    with app.app_context():
        AdminUser.query.first().installation_admin = True
        db.session.commit()
    return admin_client(app)


def test_perpetual_license_survives_sessions_and_allows_more_than_three(app, signed, monkeypatch):
    monkeypatch.setattr('socket.create_connection', lambda *a, **k: pytest.fail('License attempted network access'))
    with app.app_context():
        document, _ = signed
        software_license.activate(document)
        db.session.remove()
        assert software_license.status()['owner'] == 'Fixture purchaser'
        for n in range(3, 6):
            create_station('Station ' + str(n), 'station-' + str(n))
        assert db.session.get(SoftwareLicense, 1).document == document
    # No host/installation identifier enters verification.
    app.config['PUBLIC_BASE_URL'] = 'https://another-owned-install.example'
    with app.app_context():
        assert software_license.verify(document)['expires'] is None
    overview = admin_client(app).get('/admin').text
    assert '5 / unlimited stations' in overview
    assert 'action="/admin/stations/create"' in overview
    assert 'Unlimited · perpetual' in overview


@pytest.mark.parametrize('change', ['tamper', 'key', 'signature', 'expiry', 'id', 'payload'])
def test_rejects_invalid_license_without_overwriting_existing(app, signed, change):
    document, sign = signed
    with app.app_context():
        software_license.activate(document)
        bad = deepcopy(document)
        if change == 'tamper': bad['payload']['owner'] = 'Someone else'
        elif change == 'key': bad['key_id'] = 'unknown'
        elif change == 'signature': bad['signature'] = 'invalid-base64'
        elif change == 'expiry': bad = sign(dict(bad['payload'], expires='2027-01-01'))
        elif change == 'id': bad = sign(dict(bad['payload'], license_id=123))
        else: bad = sign(None)
        with pytest.raises(ValueError): software_license.activate(bad)
        assert software_license.status()['owner'] == 'Fixture purchaser'


def test_roles_csrf_and_upload_bounds(app, signed):
    assert app.test_client().get('/admin/software').status_code == 302
    station_admin = admin_client(app)
    assert station_admin.get('/admin/software').status_code == 403
    assert station_admin.post('/admin/software/license').status_code == 403
    client = operator(app)
    assert client.get('/admin/software').status_code == 200
    assert client.post('/admin/software/license').status_code == 400
    document, _ = signed
    def upload(raw):
        return client.post('/admin/software/license', data={'csrf': 'test-admin-csrf-token', 'license': (BytesIO(raw), 'license.json')})
    assert upload(json.dumps(document).encode()).status_code == 302
    assert upload(b'x' * 16385).status_code == 400
    assert upload(b'not-json').status_code == 400
    assert 'Fixture purchaser' in client.get('/admin/software').text


def test_only_confirmed_prepared_upgrade_can_be_queued_once(app):
    identifier = str(uuid.uuid4())
    with app.app_context():
        db.session.add(SystemUpgrade(id=identifier, version='1.0.0', state='prepared'))
        db.session.commit()
    path = '/admin/software/upgrades/' + identifier
    station_admin = admin_client(app)
    assert station_admin.post(path, data={'csrf': 'test-admin-csrf-token', 'maintenance': 'yes'}).status_code == 403
    client = operator(app)
    assert client.post(path).status_code == 400
    assert client.post(path, data={'csrf': 'test-admin-csrf-token'}).status_code == 400
    data = {'csrf': 'test-admin-csrf-token', 'maintenance': 'yes'}
    assert client.post(path, data=data).status_code == 302
    assert client.post(path, data=data).status_code == 409
    assert client.post('/admin/software/upgrades/not-a-uuid', data=data).status_code == 404
    with app.app_context():
        row = db.session.get(SystemUpgrade, identifier)
        assert row.state == 'queued' and row.requested_by == AdminUser.query.first().id


def test_root_role_grant_is_explicit(app, monkeypatch):
    runner = app.test_cli_runner()
    import importlib
    module = importlib.import_module('app.admin_cli')
    monkeypatch.setattr(module.os, 'geteuid', lambda: 1000)
    assert runner.invoke(args=['admin', 'installation-role', 'admin@example.test', '--grant']).exit_code != 0
    monkeypatch.setattr(module.os, 'geteuid', lambda: 0)
    assert runner.invoke(args=['admin', 'installation-role', 'admin@example.test']).exit_code != 0
    assert runner.invoke(args=['admin', 'installation-role', 'admin@example.test', '--grant']).exit_code == 0
    with app.app_context(): assert AdminUser.query.first().installation_admin


def test_updater_excludes_its_own_units_and_uses_stable_environment(monkeypatch):
    from freo_ops.__main__ import active_units
    from freo_ops.upgrade import rewrite_unit
    rows = [{'unit': u, 'active': 'active'} for u in ['freo.service', 'freo-updater.service', 'freo-updater.timer']]
    monkeypatch.setattr('freo_ops.recovery.run', lambda *a, **k: json.dumps(rows).encode())
    assert active_units() == ['freo.service']
    assert active_units(include_updater=True) == [row['unit'] for row in rows]
    from pathlib import Path
    body = rewrite_unit(Path('deploy/systemd/freo-updater.service').read_text())
    assert '--env-file /etc/freo/freo.env run' in body
    assert '/opt/freo/current/venv/bin/python' in body


def test_plan_identifiers_cannot_select_arbitrary_paths():
    from freo_ops.web_updates import plan_path
    for value in ['../../etc/passwd', 'not-an-id', str(uuid.uuid4()).upper()]:
        with pytest.raises(ValueError): plan_path(value)

@pytest.mark.parametrize('scenario', ['success', 'running', 'failure', 'unsafe-plan'])
def test_root_runner_closes_database_before_backup_and_never_replays_interruption(tmp_path, monkeypatch, scenario):
    from freo_ops import web_updates as worker
    from freo_ops.recovery import RecoveryError
    monkeypatch.setattr(worker, 'STATE', tmp_path)
    tmp_path.chmod(0o700)
    identifier = str(uuid.uuid4())
    directory = tmp_path / 'plans' / identifier
    directory.mkdir(parents=True, mode=0o700)
    plan = {key: '/operator/' + key for key in ('artifact', 'signature', 'keyring', 'env_file', 'backup', 'passphrase_file', 'verification_env_file', 'verification_directory')}
    path = directory / 'plan.json'
    path.write_text(json.dumps(plan))
    path.chmod(0o644 if scenario == 'unsafe-plan' else 0o600)
    calls = []
    class Connection:
        closed = False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def cursor(self): return self
        def execute(self, query, args=None): self.query = query; calls.append(('sql', query))
        def fetchone(self):
            if "state='running'" in self.query: return (identifier,) if scenario == 'running' else None
            return (identifier,)
        def close(self): self.closed = True
    con = Connection()
    monkeypatch.setattr(worker.recovery, 'connect', lambda *a: con)
    monkeypatch.setattr(worker, 'configuration', lambda *a: {'DATABASE_URL': 'fixture'})
    monkeypatch.setattr(worker, 'passphrase', lambda *a: b'private-fixture')
    monkeypatch.setattr(worker, 'finish', lambda url, ident, state, msg: calls.append(('finish', state)))
    # Exercise ownership checks on a portable test runner without requiring uid 0.
    monkeypatch.setattr(worker, 'require_root_directory', lambda path, private=False: None)
    import os
    if os.geteuid() != 0 and scenario in ('success', 'failure'):
        pytest.skip('Root plan ownership integration is exercised in root-run VM/PG suite')
    def upgrade(*args):
        assert con.closed, 'Worker must release its database connection before backup'
        assert args[:5] == tuple(plan[key] for key in ('artifact', 'signature', 'keyring', 'env_file', 'backup'))
        calls.append(('upgrade', identifier))
        if scenario == 'failure': raise RecoveryError('Injected failure')
        return {'version': '1.0.0'}
    monkeypatch.setattr(worker, 'upgrade', upgrade)
    if scenario in ('failure', 'unsafe-plan'):
        with pytest.raises(RecoveryError): worker.run_once('/operator/env_file')
        assert ('finish', 'failed') in calls
    else:
        worker.run_once('/operator/env_file')
    if scenario == 'running':
        assert not any(c[0] in ('upgrade', 'finish') for c in calls)
    if scenario == 'unsafe-plan':
        assert not any(c[0] == 'upgrade' for c in calls)
    if scenario == 'success': assert ('finish', 'complete') in calls
    assert con.closed
