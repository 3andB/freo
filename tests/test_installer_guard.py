"""Execute only the installer's refusal preflight against a fake filesystem."""
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('existing', ['.env', 'current', 'stable-env', 'media'])
def test_existing_state_refuses_before_any_provisioning(tmp_path, existing):
    root = tmp_path / 'install'
    root.mkdir()
    stable = tmp_path / 'stable.env'
    media = tmp_path / 'media'
    if existing in ('.env', 'current'):
        (root / existing).write_text('existing')
    elif existing == 'stable-env':
        stable.write_text('existing')
    else:
        media.mkdir()
    source = Path('scripts/provision.sh').read_text().split('. /etc/os-release', 1)[0]
    source = source.replace('/opt/freo', str(root)).replace('/etc/freo/freo.env', str(stable)).replace('/var/lib/freo/media', str(media))
    script = tmp_path / 'preflight.sh'
    script.write_text(source + '\nexit 97\n')
    result = subprocess.run(['bash', str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert 'Existing Freo state detected' in result.stderr
