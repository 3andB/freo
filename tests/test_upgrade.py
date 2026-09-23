"""Failure injection for upgrade orchestration; no real services or live paths."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from freo_ops import upgrade as updater
from freo_ops import recovery
from freo_ops import __main__ as management


@pytest.fixture
def host(tmp_path, monkeypatch):
    root = tmp_path / 'opt/freo'
    state = tmp_path / 'var/lib/freo-updates'
    config = tmp_path / 'etc/freo'
    units = tmp_path / 'etc/systemd/system'
    for path in (root / 'app', state, config, units, root / 'deploy/systemd'):
        path.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    (root / 'app/version.py').write_text("VERSION = '0.1.0'\n")
    environment = config / 'freo.env'
    environment.write_text('DATABASE_URL=postgresql://test@localhost/source\nSECRET_KEY=fixture\n')
    template = '[Service]\nWorkingDirectory=/opt/freo\nEnvironmentFile=/opt/freo/.env\nExecStart=/opt/freo/venv/bin/python -m app\n'
    for name in ('freo.service', 'freo-automation.service'):
        (units / name).write_text(template)
        (root / 'deploy/systemd' / name).write_text(template)
    mapped = {'/opt/freo': root, '/var/lib/freo-updates': state,
              '/etc/freo/freo.env': environment, '/etc/systemd/system': units}
    monkeypatch.setattr(updater, 'Path', lambda value: mapped.get(str(value), Path(value)))
    monkeypatch.setattr(updater.os, 'geteuid', lambda: 0)
    # Host paths/ownership are simulated; these tests also run as an unprivileged CI user.
    monkeypatch.setattr(updater, 'require_root_directory', lambda *args, **kwargs: None)
    monkeypatch.setattr(updater.platform, 'freedesktop_os_release', lambda: {'ID': 'ubuntu', 'VERSION_ID': '24.04'})
    monkeypatch.setattr(updater.platform, 'machine', lambda: 'x86_64')
    active = ['freo.service', 'freo-automation.service']
    calls = []
    info = dict(revision='a71d25b609ef', failure=None)
    monkeypatch.setattr(management, 'inventory', lambda *args: [config])
    monkeypatch.setattr(management, 'active_units', lambda: list(active))
    monkeypatch.setattr(recovery, 'connect', lambda url: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(recovery, 'schema_revision', lambda connection: info['revision'])

    def extract(artifact, directory, **kwargs):
        calls.append('verify-release')
        if info['failure'] == 'signature':
            raise recovery.RecoveryError('Signature rejected')
        for name in ('app', 'deploy/systemd', 'wheels'):
            (directory / name).mkdir(parents=True, exist_ok=True)
        (directory / 'app/version.py').write_text("VERSION = '0.2.0'\n")
        (directory / 'requirements.lock').write_text('fixture==1 --hash=sha256:fixture\n')
        for name in ('freo.service', 'freo-automation.service'):
            (directory / 'deploy/systemd' / name).write_text(template)
        manifest = dict(platform='ubuntu-24.04-x86_64', python='3.12', version='0.2.0',
                        schema_head='d02f9a41c830', supported_source_revisions=['a71d25b609ef', 'd02f9a41c830'])
        (directory / 'release.json').write_text(json.dumps(manifest))
        return manifest
    monkeypatch.setattr(updater.releases, 'extract_verified', extract)

    def run(command, **kwargs):
        calls.append(command)
        if command[:2] == ['systemctl', 'stop']:
            active.clear()
        if command[:2] == ['systemctl', 'start']:
            if info['failure'] == 'start':
                raise recovery.RecoveryError('Injected service failure')
            active[:] = command[2:]
        if command[-2:] == ['db', 'upgrade']:
            info['revision'] = 'd02f9a41c830'
            if info['failure'] == 'migration':
                raise recovery.RecoveryError('Injected migration failure')
        return b''
    monkeypatch.setattr(recovery, 'run', run)

    def backup(*args, **kwargs):
        calls.append('backup')
        assert not active
        if info['failure'] == 'backup':
            raise recovery.RecoveryError('Injected backup failure')
    monkeypatch.setattr(recovery, 'create', backup)
    def restore(*args, **kwargs):
        calls.append('restore-verified')
        assert not active
        return {'database': 'freo_restore_fixture'}
    monkeypatch.setattr(recovery, 'restore', restore)
    def preserve(*args):
        calls.append('preservation-verified')
        assert not active
        if info['failure'] == 'preservation':
            raise recovery.RecoveryError('Preservation failed')
    monkeypatch.setattr(updater, 'verify_preservation', preserve)
    class Ready:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(updater, 'build_opener', lambda *args: SimpleNamespace(open=lambda *a, **k: Ready()))
    def execute(check=False):
        return updater.upgrade('artifact', 'signature', 'trusted-keyring', environment,
                               tmp_path / 'backup.gpg', b'fixture-passphrase', environment,
                               tmp_path / 'verification', check=check)
    return SimpleNamespace(execute=execute, calls=calls, active=active, info=info,
                           root=root, units=units, state=state, template=template)


def test_upgrade_orders_backup_restore_migration_preservation_and_activation(host):
    result = host.execute()
    assert result['status'] == 'complete'
    migration = next(i for i, call in enumerate(host.calls) if isinstance(call, list) and call[-2:] == ['db', 'upgrade'])
    assert host.calls.index('backup') < host.calls.index('restore-verified') < migration < host.calls.index('preservation-verified')
    assert host.root.joinpath('current').is_symlink()
    assert 'WorkingDirectory=/opt/freo/current' in (host.units / 'freo.service').read_text()
    assert host.active == ['freo.service', 'freo-automation.service']
    assert not (host.state / 'maintenance').exists()
    assert 'ConditionPathExists=!' in (host.units / 'freo.service.d/00-freo-upgrade-guard.conf').read_text()
    journal = json.loads((host.state / 'journal.json').read_text())
    assert journal['phase'] == 'complete' and len(journal['previous_units']) == 2
    assert all('dropdb' not in str(call) and '--clean' not in str(call) for call in host.calls)


@pytest.mark.parametrize('failure', ['signature', 'backup', 'migration', 'preservation', 'start'])
def test_failures_never_reset_database_or_activate_unverified_state(host, failure):
    host.info['failure'] = failure
    with pytest.raises(recovery.RecoveryError):
        host.execute()
    journal = json.loads((host.state / 'journal.json').read_text())
    if failure in ('signature', 'backup'):
        assert host.active == ['freo.service', 'freo-automation.service']
        assert not (host.root / 'current').exists()
    else:
        assert journal['phase'] == 'recovery_required'
        assert host.active == []
        assert (host.state / 'maintenance').is_file()
        with pytest.raises(recovery.RecoveryError, match='unfinished'):
            host.execute()
    if failure in ('signature', 'backup', 'migration', 'preservation'):
        assert (host.units / 'freo.service').read_text() == host.template
    assert all('--clean' not in str(call) and 'dropdb' not in str(call) for call in host.calls)


def test_preflight_does_not_stop_services_or_migrate(host):
    assert host.execute(check=True)['status'] == 'preflight_passed'
    assert host.active == ['freo.service', 'freo-automation.service']
    assert host.calls == ['verify-release']


def test_repeating_the_same_release_does_not_migrate_or_restart(host):
    host.execute()
    host.calls.clear()
    assert host.execute()['status'] == 'already_installed'
    assert host.calls == ['verify-release']


def test_custom_units_are_not_overwritten(host):
    (host.units / 'freo.service').write_text(host.template + 'MemoryMax=100M\n')
    with pytest.raises(recovery.RecoveryError, match='Customized service'):
        host.execute()
    assert host.active == ['freo.service', 'freo-automation.service']


def test_in_place_code_replacement_is_not_mistaken_for_a_recoverable_old_release(host):
    (host.root / 'app/version.py').write_text("VERSION = '0.2.0'\n")
    with pytest.raises(recovery.RecoveryError, match='matched baseline'):
        host.execute()
    assert host.active == ['freo.service', 'freo-automation.service']


def test_unit_rewrite_is_repeatable_and_preserves_other_settings():
    original = 'EnvironmentFile=/opt/freo/.env\nWorkingDirectory=/opt/freo\nExecStart=/opt/freo/venv/bin/flask\nUser=freo\n'
    rewritten = updater.rewrite_unit(original)
    assert rewritten == updater.rewrite_unit(rewritten)
    assert 'User=freo\n' in rewritten and '/etc/freo/freo.env' in rewritten


def test_privileged_journal_rejects_links_and_writable_directories(tmp_path):
    directory = tmp_path / 'unsafe'
    directory.mkdir()
    directory.chmod(0o777)
    with pytest.raises(recovery.RecoveryError):
        updater.require_root_directory(directory)
    link = tmp_path / 'link'
    link.symlink_to(directory)
    with pytest.raises(recovery.RecoveryError):
        updater.require_root_directory(link)


@pytest.mark.parametrize('outcome', ['delayed', 'unavailable', 'empty', 'wrong-type'])
def test_upgrade_waits_for_station_audio_and_preserves_failure_recovery(host, monkeypatch, outcome):
    """An active playout unit does not yet guarantee an Icecast mount exists."""
    from email.message import Message
    host.active.append('freo-playout@fixture.service')
    elapsed = [0.0]
    monkeypatch.setattr(updater.time, 'monotonic', lambda: elapsed[0])
    monkeypatch.setattr(updater.time, 'sleep', lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    attempts = []

    class Response:
        status = 200
        def __init__(self, content_type='audio/mpeg', body=b'fixture-mp3-data'):
            self.headers = Message()
            self.headers['Content-Type'] = content_type
            self.body = body
        def read(self, size): return self.body[:size]
        def __enter__(self): return self
        def __exit__(self, *args): pass

    def open_url(url, timeout):
        if url.endswith('/ready'):
            return Response('application/json', b'{}')
        assert url == 'http://127.0.0.1:8001/fixture'
        assert 0 < timeout <= 10
        attempts.append(elapsed[0])
        if outcome == 'unavailable' or (outcome == 'delayed' and len(attempts) <= 2):
            raise OSError('Mount has not connected yet')
        return Response('text/html' if outcome == 'wrong-type' else 'audio/mpeg',
                        b'' if outcome == 'empty' else b'fixture-mp3-data')

    monkeypatch.setattr(updater, 'build_opener', lambda *args: SimpleNamespace(open=open_url))
    if outcome == 'delayed':
        assert host.execute()['status'] == 'complete'
        assert len(attempts) == 3 and elapsed[0] >= 2
        assert 'freo-playout@fixture.service' in host.active
        assert not (host.state / 'maintenance').exists()
    else:
        with pytest.raises(recovery.RecoveryError, match='station.*audio'):
            host.execute()
        assert 1 < len(attempts) <= 60 and elapsed[0] == 60
        journal = json.loads((host.state / 'journal.json').read_text())
        assert journal['phase'] == 'recovery_required' and journal['failure_phase'] == 'starting'
        assert host.active == [] and (host.state / 'maintenance').exists()
