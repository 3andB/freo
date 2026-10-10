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


@pytest.mark.parametrize('options,expected,code', [
    ({'FREO_DOMAIN': 'radio.example.com'}, 'http://radio.example.com', 0),
    ({'FREO_DOMAIN': 'radio.example.com', 'FREO_ENABLE_HTTPS': '1', 'FREO_CERTBOT_EMAIL': 'operator@example.com'}, 'https://radio.example.com', 0),
    ({'FREO_ENABLE_HTTPS': '1', 'FREO_CERTBOT_EMAIL': 'operator@example.com'}, 'HTTPS requires', 1),
    ({'FREO_DOMAIN': 'radio.example.com', 'FREO_ENABLE_HTTPS': '1'}, 'HTTPS requires', 1),
    ({'FREO_DOMAIN': 'bad;domain'}, 'invalid characters', 1),
    ({'FREO_ENABLE_HTTPS': 'yes'}, 'must be 0 or 1', 1),
])
def test_https_preflight_saves_correct_scheme_and_rejects_incomplete_options(tmp_path, options, expected, code):
    import os
    source_root = tmp_path / 'source'
    (source_root / 'app').mkdir(parents=True)
    root, stable, media = tmp_path / 'install', tmp_path / 'stable.env', tmp_path / 'media'
    # Execute the real early preflight, stopping before its first package action.
    source = Path('scripts/provision.sh').read_text().split("printf '%s\\n' 'Freo automatically reports", 1)[0]
    source = source.replace('/opt/freo', str(root)).replace('/etc/freo/freo.env', str(stable)).replace('/var/lib/freo/media', str(media))
    script = tmp_path / 'https-preflight.sh'
    script.write_text(source + '\nprintf "%s\\n" "$public_base"\n')
    environment = {key: value for key, value in os.environ.items() if not key.startswith('FREO_')}
    result = subprocess.run(['bash', str(script), str(source_root)], capture_output=True, text=True, env=dict(environment, **options))
    assert result.returncode == code, result.stderr
    assert expected in result.stdout + result.stderr
    assert not root.exists() and not stable.exists() and not media.exists()
