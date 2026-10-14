"""Scoped libigloo selection and failures before hosted policy/service changes."""
from contextlib import nullcontext
from pathlib import Path
import json
import os
import shlex
import shutil
import subprocess
import sys

import pytest

from freo_ops import hosting, hosting_admin, recovery, v1
from tests.test_web import app


ROOT = Path(__file__).resolve().parents[1]


def preferences():
    source = (ROOT / 'scripts/configure-icecast-repository.sh').read_text()
    return source.split("/etc/apt/preferences.d/freo-icecast <<'EOF'\n", 1)[1].split('\nEOF', 1)[0] + '\n'


@pytest.mark.skipif(not shutil.which('apt-cache') or not shutil.which('apt-get'), reason='APT required')
def test_real_apt_resolver_selects_matching_pair_and_excludes_unrelated_xiph_packages(tmp_path):
    # Synthetic repository metadata, real APT resolver, no network or host state.
    for name in ('empty', 'lists/partial', 'cache/archives/partial'):
        (tmp_path / name).mkdir(parents=True)
    sources = tmp_path / 'sources.list'
    sources.write_text('deb https://download.opensuse.org/repositories/multimedia:/xiph/xUbuntu_24.04/ /\n'
                       'deb http://archive.ubuntu.com/ubuntu noble main\n')
    (tmp_path / 'status').write_text('')
    pref = tmp_path / 'preferences'
    options = []
    for key, value in {
        'Dir::Etc::sourcelist': sources, 'Dir::Etc::sourceparts': tmp_path / 'empty',
        'Dir::Etc::main': '/dev/null', 'Dir::Etc::parts': tmp_path / 'empty',
        'Dir::Etc::preferences': pref, 'Dir::Etc::preferencesparts': tmp_path / 'empty',
        'Dir::State::lists': tmp_path / 'lists', 'Dir::State::status': tmp_path / 'status',
        'Dir::Cache': tmp_path / 'cache', 'Debug::NoLocking': '1',
    }.items():
        options += ['-o', f'{key}={value}']

    def apt(tool, *args):
        return subprocess.run([tool, *options, *args], check=True, capture_output=True,
                              text=True, env=dict(os.environ, LC_ALL='C')).stdout

    architecture = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()

    def package(name, version, dependency=None):
        fields = [f'Package: {name}', f'Version: {version}', f'Architecture: {architecture}',
                  'Maintainer: Test <test@example.invalid>', 'Description: isolated APT fixture',
                  f'Filename: {name}_{version}.deb', 'Size: 1']
        if dependency:
            fields.append('Depends: ' + dependency)
        return '\n'.join(fields) + '\n\n'

    for line in apt('apt-get', '--print-uris', 'update').splitlines():
        fields = shlex.split(line)
        if not fields or not fields[0].endswith('/Packages.xz'):
            continue
        url, filename = fields[:2]
        if 'download.opensuse.org' in url:
            metadata = (package('libigloo0', '0.9.5-1') +
                        package('libigloo-dev', '0.9.5-1', 'libigloo0 (= 0.9.5-1)') +
                        package('unrelated-xiph', '99.0'))
        elif f'binary-{architecture}/' in url:
            metadata = (package('libigloo0t64', '0.9.2-1.1build1') +
                        package('libigloo-dev', '0.9.2-1.1build1', 'libigloo0t64 (= 0.9.2-1.1build1)'))
        else:
            metadata = ''
        (tmp_path / 'lists' / filename).write_text(metadata)

    pref.write_text(preferences().replace('Package: libigloo0 libigloo-dev', 'Package: libigloo0'))
    assert 'Candidate: 0.9.2-1.1build1' in apt('apt-cache', 'policy', 'libigloo-dev')
    before = apt('apt-get', '--simulate', '--no-remove', 'install', 'libigloo-dev')
    assert 'Inst libigloo0t64 (0.9.2-1.1build1' in before

    pref.write_text(preferences())
    for name in ('libigloo-dev', 'libigloo0'):
        assert 'Candidate: 0.9.5-1' in apt('apt-cache', 'policy', name)
    after = apt('apt-get', '--simulate', '--no-remove', 'install', 'libigloo-dev', 'libigloo0')
    assert 'Inst libigloo-dev (0.9.5-1' in after
    assert 'Inst libigloo0 (0.9.5-1' in after
    assert 'Inst libigloo0t64' not in after and 'Remv ' not in after
    assert 'Candidate: (none)' in apt('apt-cache', 'policy', 'unrelated-xiph')


@pytest.mark.parametrize('version', ['0.9.5-1', '0.9.6-2'])
def test_dependency_setup_resolves_pair_simulates_before_install_and_is_repeatable(monkeypatch, version):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ['apt-cache', 'policy']:
            return f'{args[-1]}:\n  Candidate: {version}\n'.encode()
        return b''

    monkeypatch.setattr(recovery, 'run', run)
    for _ in range(2):
        v1.prepare_icecast_dependencies(ROOT)
    simulations = [args for args, _ in calls if '--simulate' in args]
    installs = [args for args, _ in calls if args[:2] == ['apt-get', 'install'] and '--simulate' not in args]
    assert len(simulations) == len(installs) == 2
    assert simulations[0] == simulations[1] and installs[0] == installs[1]
    for simulate, install in zip(simulations, installs):
        assert '--no-remove' in simulate and '--no-remove' in install
        assert 'libigloo-dev=' + version in install and 'libigloo0=' + version in install
        assert simulate == install[:2] + ['--simulate'] + install[2:]
        assert calls.index(next(row for row in calls if row[0] == simulate)) < calls.index(next(row for row in calls if row[0] == install))
    assert all(kwargs['env']['NEEDRESTART_MODE'] == 'l' for _, kwargs in calls)
    assert not any(args[0] == 'systemctl' or 'upgrade' in args or 'remove' in args for args, _ in calls)


@pytest.mark.parametrize('failure', ['missing', 'old', 'mismatch', 'update', 'simulation', 'install', 'pkg-config', 'runtime'])
def test_dependency_preflight_fails_actionably_without_build(monkeypatch, tmp_path, failure):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if (failure == 'update' and args[-1] == 'update' or
                failure == 'simulation' and '--simulate' in args or
                failure == 'install' and args[:2] == ['apt-get', 'install'] and '--simulate' not in args or
                failure == 'pkg-config' and args[0] == 'pkg-config' or
                failure == 'runtime' and args[-1].endswith('check-igloo.py')):
            raise recovery.RecoveryError('Injected unavailable dependency')
        if args[:2] == ['apt-cache', 'policy']:
            version = '(none)' if failure == 'missing' else '0.9.2-1.1build1' if failure == 'old' else '0.9.5-1'
            if failure == 'mismatch' and args[-1] == 'libigloo0':
                version = '0.9.6-1'
            return f'  Candidate: {version}\n'.encode()
        if args[0] == 'dpkg' and failure == 'old':
            raise recovery.RecoveryError('Version below minimum')
        return b''

    monkeypatch.setattr(recovery, 'run', run)
    archive = tmp_path / 'icecast-2.5.0.tar.gz'
    archive.touch()
    monkeypatch.setattr(recovery, 'digest', lambda path: 'd9aa07c7429aec19d950ff6fd425c371f77158cd34ff220fc191b2c186c67c7a')
    with pytest.raises(v1.IcecastDependencyError, match='apt-cache policy libigloo-dev libigloo0'):
        v1.prepare_icecast(ROOT, tmp_path)
    assert not any('build-icecast-2.5.sh' in ' '.join(args) for args in calls)
    if failure not in ('install', 'pkg-config', 'runtime'):
        assert not any(args[:2] == ['apt-get', 'install'] and '--simulate' not in args for args in calls)


@pytest.mark.skipif(not shutil.which('cc'), reason='C compiler required for isolated runtime fixture')
@pytest.mark.parametrize('version,success', [((0, 9, 2), False), ((0, 9, 4), True), ((0, 9, 5), True)])
def test_runtime_probe_checks_loaded_library_even_with_newer_headers(tmp_path, version, success):
    # Real ELF loading/version call against a tiny synthetic library; no installed libraries changed.
    source = tmp_path / 'igloo.c'
    source.write_text('int igloo_version_get(const char **s, int *a, int *b, int *c) { '
                      f'*s="fixture"; *a={version[0]}; *b={version[1]}; *c={version[2]}; return 0; }}\n')
    subprocess.run(['cc', '-shared', '-fPIC', str(source), '-o', str(tmp_path / 'libigloo.so.0')], check=True)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-igloo.py')],
                            capture_output=True, text=True,
                            env=dict(os.environ, LD_LIBRARY_PATH=str(tmp_path)))
    assert (result.returncode == 0) == success
    if success:
        assert 'Loaded libigloo runtime ' + '.'.join(map(str, version)) in result.stdout
    else:
        assert 'loaded version 0.9.2' in result.stderr
        assert 'libigloo0t64' in result.stderr and 'dpkg-query -S' in result.stderr


@pytest.mark.parametrize('failure', ['dependencies', 'build'])
def test_first_hosting_failure_keeps_policy_and_services_unchanged(app, tmp_path, monkeypatch, failure):
    from app.services import station_runtime
    config, state = tmp_path / 'hosting.json', tmp_path / 'state'
    state.mkdir()
    config.write_text('{"hosted":false}\n')
    original = config.read_bytes()
    monkeypatch.setattr(hosting, 'CONFIG', config)
    monkeypatch.setattr(hosting, 'STATE', state)
    monkeypatch.setattr(hosting, 'trusted', lambda path: None)
    monkeypatch.setattr(station_runtime, 'operation_lock', nullcontext)
    monkeypatch.setattr(hosting_admin, 'constraints', lambda policy: [])
    binary = tmp_path / 'icecast'
    binary.write_bytes(b'unpatched fixture')
    calls = []
    monkeypatch.setattr(hosting_admin, 'run', lambda args, **kwargs: calls.append(args) or f'{{ path={binary} ; }}')
    monkeypatch.setattr(v1, 'activate_icecast', lambda *args, **kwargs: pytest.fail('Failed build was activated'))
    monkeypatch.setattr(hosting_admin, 'provision_storage', lambda: pytest.fail('Failed build changed storage'))

    def fail(*args):
        if failure == 'dependencies':
            raise v1.IcecastDependencyError('Check apt-cache policy libigloo-dev libigloo0; compatible packages unavailable.')
        raise recovery.RecoveryError('Icecast build failed')

    monkeypatch.setattr(v1, 'prepare_icecast', fail)
    requested = dict(hosted=True, plan='starter', status='active', limits=dict(hosting.PLANS['starter']))
    with app.app_context(), pytest.raises((hosting.HostingError, recovery.RecoveryError)) as error:
        hosting_admin.apply(requested, 'configure')
    if failure == 'dependencies':
        assert error.value.code == 'icecast_dependencies_unavailable'
        assert 'apt-cache policy' in str(error.value)
    assert config.read_bytes() == original and hosting.read() == {'hosted': False}
    assert not any((state / name).exists() for name in ('enabled', 'inhibit', 'transaction.json'))
    assert calls == [['systemctl', 'show', 'icecast2.service', '--property=ExecStart', '--value']]
    assert json.loads((state / 'audit.jsonl').read_text())['result']['success'] is False


def test_existing_t64_runtime_ownership_blocks_all_package_installs(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ['apt-cache', 'policy']:
            return b'  Candidate: 0.9.5-1\n'
        if args[:2] == ['dpkg-query', '-W']:
            return b'libigloo0:amd64 ii \nlibigloo0t64:amd64 ii \n'
        if args[:2] == ['dpkg-query', '-S']:
            return b'libigloo0t64:amd64: /usr/lib/x86_64-linux-gnu/libigloo.so.0\n'
        return b''
    monkeypatch.setattr(recovery, 'run', run)
    with pytest.raises(v1.IcecastDependencyError, match='libigloo0t64'):
        v1.prepare_icecast_dependencies(ROOT)
    assert not any(args[:2] == ['apt-get', 'install'] for args in calls)
