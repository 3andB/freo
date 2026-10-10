"""Opt-in OS permission proof under /tmp, without installing service overrides."""
import importlib.util
import os
from pathlib import Path
import pwd
import subprocess

import pytest

pytestmark=pytest.mark.skipif(os.environ.get('FREO_STORAGE_TEST')!='1',reason='Explicit isolated service-account ACL proof')


def test_real_recording_acl_separates_web_playout_and_worker(tmp_path):
    assert os.geteuid()==0
    for account in ('freo','freo-playout','freo-automation','freo-ingest'):
        pwd.getpwnam(account)
    # These test-only parent directories must be traversable by the service UIDs.
    assert tmp_path.is_relative_to('/tmp')
    tmp_path.parent.chmod(0o755);tmp_path.chmod(0o755)
    root=tmp_path/'media';root.mkdir(mode=0o755)
    spec=importlib.util.spec_from_file_location('recording_storage','scripts/recording-storage.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.provision(root,'test-station',unit_root=tmp_path/'units')
    directory=root/'test-station'/'recordings';path=directory/('e'*32+'.mp3')
    def run(account,program):
        return subprocess.run(['runuser','-u',account,'--','/usr/bin/python3','-c',program],capture_output=True,text=True)
    create=f'import os; fd=os.open({str(path)!r},os.O_CREAT|os.O_WRONLY,0o640);os.write(fd,b"MP3 permission fixture");os.close(fd)'
    assert run('freo-playout',create).returncode==0
    assert run('freo',f'from pathlib import Path;assert Path({str(path)!r}).read_bytes()==b"MP3 permission fixture"').returncode==0
    assert run('freo',f'from pathlib import Path;Path({str(path)!r}).unlink()').returncode!=0
    assert run('freo',f'from pathlib import Path;Path({str(path)!r}).write_bytes(b"unauthorized")').returncode!=0
    assert run('freo-automation',f'from pathlib import Path;Path({str(path)!r}).unlink()').returncode==0
    assert not path.exists()
    # Only the recordings directory is writable, not the station root.
    assert run('freo-automation',f'from pathlib import Path;Path({str(directory.parent/"unrelated")!r}).touch()').returncode!=0
    worker=(tmp_path/'units'/'freo-automation.service.d'/'recordings-test-station.conf').read_text()
    assert worker==f'[Service]\nReadWritePaths="{directory}"\n'
