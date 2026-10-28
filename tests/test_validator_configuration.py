"""Execute configuration selection without invoking services or reading secrets."""
import os
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('layout,explicit', [('fresh',False), ('managed',False), ('fresh',True), ('managed',True)])
def test_validator_selects_one_configuration_for_each_layout(tmp_path, layout, explicit):
    root = tmp_path/'install'; root.mkdir()
    fresh = root/'.env'; fresh.write_text('fresh')
    canonical = tmp_path/'canonical.env'; canonical.write_text('managed')
    override = tmp_path/'explicit.env'; override.write_text('explicit')
    if layout == 'managed':
        release = tmp_path/'release'; release.mkdir()
        (root/'current').symlink_to(release)
    source = (ROOT/'scripts/validate-install.sh').read_text()
    selection = source.split('# Policy errors',1)[0].replace('/etc/freo/freo.env',str(canonical))
    script = tmp_path/'selection.sh'
    script.write_text(selection + '\nprintf "%s" "$FREO_ENV_FILE"\n')
    env = dict(os.environ, FREO_INSTALL_DIR=str(root))
    env.pop('FREO_ENV_FILE',None)
    if explicit: env['FREO_ENV_FILE'] = str(override)
    result = subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(override if explicit else canonical if layout=='managed' else fresh)
    assert '$install_dir/.env' not in source.split('# Policy errors',1)[1]


def test_validator_rejects_missing_explicit_configuration(tmp_path):
    source = (ROOT/'scripts/validate-install.sh').read_text().split('# Policy errors',1)[0]
    result = subprocess.run(['bash','-c',source],env=dict(os.environ,FREO_INSTALL_DIR=str(tmp_path),
        FREO_ENV_FILE=str(tmp_path/'missing')),capture_output=True,text=True)
    assert result.returncode != 0
    assert 'existing absolute configuration' in result.stderr
