"""Exercise the source installer in /tmp with host operations replaced by stubs.

No packages, databases, system services, or installed Freo paths are touched.
Actual source copying, environment generation and dependency selection still run.
"""
import json
from pathlib import Path
import subprocess
import sys

from cryptography.fernet import Fernet
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installer(tmp_path):
    root = tmp_path / 'host'
    commands = tmp_path / 'commands'
    commands.mkdir()
    log = tmp_path / 'commands.jsonl'
    installed = root / 'opt/freo'
    (installed / 'venv/bin').mkdir(parents=True)
    for directory in ('etc/systemd/system', 'etc/nginx/snippets',
                      'etc/nginx/sites-available', 'etc/nginx/sites-enabled'):
        (root / directory).mkdir(parents=True)
    stub = commands / 'stub'
    stub.write_text(f'#!{sys.executable}\n' + r'''
import json, os, secrets, sys
from pathlib import Path
name, args = Path(sys.argv[0]).name, sys.argv[1:]
with open(os.environ['INSTALL_TEST_LOG'], 'a') as stream:
    stream.write(json.dumps([name, *args]) + '\n')
if name == 'install':
    cleaned = []
    while args:
        item = args.pop(0)
        if item in ('-o', '-g'):
            args.pop(0)
        else:
            cleaned.append(item)
    os.execv('/usr/bin/install', ['install', *cleaned])
elif name == 'openssl':
    print(secrets.token_hex(32))
elif name == 'runuser':
    if args[1] != 'postgres':
        command = args[args.index('--') + 1:]
        os.execvp(command[0], command)
elif name in ('python', 'python3') and args[0] == '-':
    os.execv(os.environ['INSTALL_TEST_PYTHON'], ['python', *args])
elif name == 'bash' and Path(args[0]).name == 'install-python.sh':
    os.execv('/bin/bash', ['bash', *args])
elif name == 'git':
    print('test-source')
elif name not in ('apt-get', 'systemctl', 'id', 'useradd', 'usermod', 'chown',
                  'nginx', 'certbot', 'flask', 'bash', 'python', 'python3'):
    raise SystemExit('Unexpected host command: ' + name)
''')
    stub.chmod(0o755)
    for command in ('apt-get', 'systemctl', 'id', 'useradd', 'usermod', 'chown',
                    'nginx', 'certbot', 'bash', 'python3', 'runuser', 'install',
                    'openssl', 'git'):
        (commands / command).symlink_to(stub)
    for command in ('python', 'flask'):
        (installed / 'venv/bin' / command).symlink_to(stub)
    script = (ROOT / 'scripts/provision.sh').read_text()
    for path in ('/opt/freo', '/etc/freo', '/var/lib/freo', '/var/log/icecast2',
                 '/etc/systemd/system', '/etc/nginx'):
        script = script.replace(path, str(root) + path)
    script_path = tmp_path / 'provision.sh'
    script_path.write_text(script)

    def run(**options):
        environment = dict(PATH=f'{commands}:/usr/bin:/bin',
            FREO_DOMAIN='209.38.64.12', FREO_ENV_FILE='/dev/null',
            PYTHONDONTWRITEBYTECODE='1', INSTALL_TEST_LOG=str(log),
            INSTALL_TEST_PYTHON=sys.executable, **options)
        result = subprocess.run(['/bin/bash', str(script_path), str(ROOT)],
            env=environment, text=True, capture_output=True, timeout=30)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls
    return run, root, installed


@pytest.mark.parametrize('microphone', ['0', '1'])
def test_fresh_source_install_contains_v1_and_optional_microphone(installer, microphone):
    run, root, installed = installer
    result, calls = run(FREO_LIVE_MIC=microphone)
    assert result.returncode == 0, result.stderr
    env_file = installed / '.env'
    values = dict(line.split('=', 1) for line in env_file.read_text().splitlines())
    key = values['FREO_PROVIDER_ENCRYPTION_KEY']
    Fernet(key.encode())
    assert key != values['SECRET_KEY']
    assert key not in result.stdout + result.stderr
    assert env_file.stat().st_mode & 0o777 == 0o640
    assert values['FREO_LIVE_MIC'] == microphone
    assert values['PUBLIC_BASE_URL'] == 'http://209.38.64.12'
    assert (root / 'var/lib/freo/uploads/production').stat().st_mode & 0o7777 == 0o2770
    for unit in ('freo-production', 'freo-mic', 'freo-automation', 'freo-ingest', 'freo-provision'):
        assert (root / f'etc/systemd/system/{unit}.service').read_bytes() == (ROOT / f'deploy/systemd/{unit}.service').read_bytes()
    assert ['systemctl', 'enable', '--now', 'freo-production.service'] in calls
    assert (['systemctl', 'enable', '--now', 'freo-mic.service'] in calls) == (microphone == '1')
    requirement = 'requirements-live-mic.txt' if microphone == '1' else 'requirements.txt'
    assert ['python', '-m', 'pip', 'install', '-r', str(ROOT / requirement)] in calls
    if microphone == '1':
        assert ['python', '-B', '-m', 'freo_ops.dependencies', '--live-mic'] in calls
    assert calls.index(['flask', '--app', 'wsgi:app', 'db', 'upgrade']) < calls.index(['systemctl', 'enable', '--now', 'freo-production.service'])
    assert (installed / 'scripts/recording-storage.py').is_file()
    assert (installed / 'V1_UPGRADE_NOTES.md').read_bytes() == (ROOT / 'V1_UPGRADE_NOTES.md').read_bytes()
    assert (installed / 'docs/public-api-v1.md').read_bytes() == (ROOT / 'docs/public-api-v1.md').read_bytes()
    for directory in ('app', 'migrations', 'deploy'):
        for path in (ROOT / directory).rglob('*'):
            from freo_ops.inventory import customer_path
            relative = path.relative_to(ROOT)
            if path.is_file() and customer_path(relative.as_posix()):
                assert (installed / relative).read_bytes() == path.read_bytes(), relative
    # A second run must refuse before package or service activity and preserve identity.
    before = env_file.read_bytes()
    result, repeated = run(FREO_LIVE_MIC=microphone)
    assert result.returncode == 1 and 'Existing Freo state' in result.stderr
    assert repeated == calls and env_file.read_bytes() == before


def test_invalid_provider_key_refuses_before_host_actions_and_is_private(installer):
    run, root, installed = installer
    invalid = 'invalid-provider-key'
    result, calls = run(FREO_PROVIDER_ENCRYPTION_KEY=invalid)
    assert result.returncode != 0
    assert invalid not in result.stdout + result.stderr
    assert 'Invalid FREO_PROVIDER_ENCRYPTION_KEY' in result.stderr
    assert not (installed / '.env').exists()
    assert not calls


def test_operator_provider_key_survives_fresh_install(installer):
    run, _, installed = installer
    key = Fernet.generate_key().decode()
    result, _ = run(FREO_PROVIDER_ENCRYPTION_KEY=key)
    assert result.returncode == 0, result.stderr
    assert f'FREO_PROVIDER_ENCRYPTION_KEY={key}\n' in (installed / '.env').read_text()
    assert key not in result.stdout + result.stderr


def test_invalid_microphone_flag_refuses_before_host_actions(installer):
    run, _, installed = installer
    result, calls = run(FREO_LIVE_MIC='yes')
    assert result.returncode == 1 and 'FREO_LIVE_MIC must be 0 or 1' in result.stderr
    assert not calls and not (installed / '.env').exists()


def test_v1_migration_chain_has_one_complete_head():
    from alembic.script import ScriptDirectory
    scripts = ScriptDirectory(str(ROOT / 'migrations'))
    assert scripts.get_heads() == ['f906a1b2c3d4']
    chain = {revision.revision for revision in scripts.walk_revisions()}
    assert {f'f{phase}06a1b2c3d4' for phase in range(1, 10)} <= chain
    assert 'f316a1b2c3d4' in chain  # Recording-manager permission/history migration.
