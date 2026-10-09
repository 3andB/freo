"""Safety regressions for the reviewed V1 host transition."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet
from freo_ops import v1, recovery, releases


def test_provider_key_is_added_once_without_rewriting_configuration(tmp_path):
    path = tmp_path/'freo.env'
    original = b'# customer configuration\nSECRET_KEY=keep-me\nCUSTOM=value\n'
    path.write_bytes(original)
    values = {}
    v1.configure_environment(values, path)
    first = path.read_bytes()
    assert first.startswith(original)
    Fernet(values['FREO_PROVIDER_ENCRYPTION_KEY'].encode())
    v1.configure_environment(values, path)
    assert path.read_bytes() == first


def test_invalid_provider_key_is_never_rotated(tmp_path):
    path = tmp_path/'freo.env'; path.write_text('unchanged')
    with pytest.raises(recovery.RecoveryError, match='encryption key'):
        v1.configure_environment({'FREO_PROVIDER_ENCRYPTION_KEY':'broken'}, path)
    assert path.read_text() == 'unchanged'


def test_customized_legacy_template_is_refused(tmp_path):
    with pytest.raises(recovery.RecoveryError, match='Customized legacy template'):
        v1.check_legacy_templates(tmp_path)


def test_candidate_requires_explicit_opt_in(tmp_path, monkeypatch):
    import tarfile,io
    archive=tmp_path/'candidate.tar.gz'
    manifest={'format':1,'development':False,'candidate':True,'files':{},'supported_source_revisions':[],
              'version':'1.0.0-dev.1','schema_head':'head'}
    with tarfile.open(archive,'w:gz') as out:
        content=json.dumps(manifest).encode(); info=tarfile.TarInfo('release.json'); info.size=len(content)
        out.addfile(info,io.BytesIO(content))
    with pytest.raises(recovery.RecoveryError,match='explicit --allow-candidate'):
        releases._extract_trusted(archive,tmp_path/'denied')
    monkeypatch.setattr(releases,'version_at',lambda p:'1.0.0-dev.1')
    monkeypatch.setattr(releases,'migration_head',lambda p:'head')
    assert releases._extract_trusted(archive,tmp_path/'allowed',allow_candidate=True)['candidate']


@pytest.mark.parametrize('active,sub', [('failed','failed'),('activating','auto-restart')])
def test_failing_baseline_is_refused_before_maintenance(monkeypatch,active,sub):
    monkeypatch.setattr(recovery,'run',lambda *a,**k:json.dumps([
        {'unit':'freo-ingest.service','active':active,'sub':sub}]).encode())
    with pytest.raises(recovery.RecoveryError,match='failing baseline service'):
        v1.check_services()


def test_v1_provisions_bulletins_and_recordings_and_retains_mic_preference(tmp_path, monkeypatch):
    actual_path = Path
    (tmp_path / 'etc/systemd/system').mkdir(parents=True)
    monkeypatch.setattr(v1, 'Path', lambda p: tmp_path / str(p).lstrip('/') if str(p).startswith(('/etc/','/var/lib/')) else actual_path(p))
    calls = []
    monkeypatch.setattr(recovery, 'run', lambda args, **kw: calls.append(args))
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, query): pass
        def fetchall(self): return [('on-air', True), ('disabled', False)]
        def fetchone(self): return [{'FREO_LIVE_MIC': True}]
    monkeypatch.setattr(recovery, 'connect', lambda url: SimpleNamespace(cursor=Cursor, close=lambda: None))
    assert v1.provision(tmp_path, {'DATABASE_URL':'fixture'}, {}) is True
    assert ['install','-d','-o','freo-automation','-g','freo-playout','-m','2750','/var/lib/freo/bulletins'] in calls
    assert len([c for c in calls if any('recording-storage.py' in x for x in c)]) == 2
    renders = [c for c in calls if 'render' in c]
    assert len(renders) == 1 and renders[0][-1] == 'on-air'

    # A subsequent reviewed V1 transition may retain the identical managed override.
    assert v1.provision(tmp_path, {'DATABASE_URL':'fixture'}, {}) is True
    override = tmp_path / 'etc/systemd/system/freo-production.service.d/storage.conf'
    override.write_text('[Service]\nReadWritePaths=/customer/custom\n')
    with pytest.raises(recovery.RecoveryError, match='Custom production storage'):
        v1.provision(tmp_path, {'DATABASE_URL':'fixture'}, {})
