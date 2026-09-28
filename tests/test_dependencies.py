"""Installation contract: real DBAPI loading and no network fallback for broken kits."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_dependency_check_ignores_real_environment_and_registers_migrations(tmp_path):
    forbidden = tmp_path / 'must-not-load.env'
    forbidden.write_text('DATABASE_URL=invalid://\nSECRET_KEY=\n')
    result = subprocess.run([sys.executable, '-m', 'freo_ops.dependencies'], cwd=ROOT,
                            env=dict(os.environ, FREO_ENV_FILE=str(forbidden), DATABASE_URL='invalid://'),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['drivers'] == {'postgresql': 'psycopg2', 'postgresql+psycopg': 'psycopg',
                                 'postgresql+psycopg2': 'psycopg2'}
    assert report['migration_cli'] == 'passed'


@pytest.mark.parametrize('missing', ['psycopg', 'psycopg_binary', 'psycopg2'])
def test_dependency_check_rejects_missing_drivers(missing):
    probe = '''
import importlib.abc, runpy, sys
class MissingDriver(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == sys.argv[1]:
            raise ModuleNotFoundError('simulated missing driver: ' + fullname)
sys.meta_path.insert(0, MissingDriver())
sys.argv = [sys.argv[0], sys.argv[1]]
from freo_ops.dependencies import check
check()
'''
    result = subprocess.run([sys.executable, '-c', probe, missing], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert missing in result.stderr or 'requires the psycopg[binary]' in result.stderr


@pytest.mark.parametrize('contents,mode', [
    (['release.json'], 'auto'), (['requirements.lock'], 'auto'),
    (['wheels'], 'auto'), (['requirements.lock', 'wheels'], 'auto'), ([], '--offline'),
])
def test_incomplete_kit_refuses_before_creating_venv_or_using_pip(tmp_path, contents, mode):
    source = tmp_path / 'source'
    source.mkdir()
    for name in contents:
        path = source / name
        if name == 'wheels':
            path.mkdir()
        else:
            path.write_text('fixture\n')
    target = tmp_path / 'venv'
    result = subprocess.run(['bash', str(ROOT / 'scripts/install-python.sh'), str(source),
                             str(target), mode], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'Incomplete release' in result.stderr
    assert not target.exists()
