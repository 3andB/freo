#!/usr/bin/env python3
"""Root-only, atomic renderer for the Phase 2 test radio configuration."""
import json
import os
from pathlib import Path
import pwd
import grp
import secrets
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path('/etc/freo')
RADIO = ROOT / 'radio'
SECRETS = ROOT / 'secrets'
KEYS = SECRETS / 'engine.json'
SOURCE = Path(__file__).resolve().parents[1]


def stage(path, data, user, group, mode):
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=RADIO)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
        os.chown(tmp, pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid)
        os.chmod(tmp, mode)
        return tmp
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run radio config rendering as root.')
    RADIO.mkdir(parents=True, exist_ok=True, mode=0o755)
    SECRETS.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(RADIO, 0o755)
    os.chmod(SECRETS, 0o700)
    if not KEYS.exists():
        generated = {name: secrets.token_hex(32) for name in ('source', 'relay', 'admin')}
        fd = os.open(KEYS, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(generated, stream)
        print('Generated restricted radio credentials.')
    if KEYS.stat().st_mode & 0o077:
        raise SystemExit('Radio credentials file has unsafe permissions.')
    credentials = json.loads(KEYS.read_text())
    if any(not isinstance(credentials.get(key), str) or len(credentials[key]) < 40 for key in ('source', 'relay', 'admin')):
        raise SystemExit('Radio credentials are incomplete or weak.')
    icecast = (SOURCE / 'deploy/icecast/icecast.xml.template').read_text()
    for key in ('source', 'relay', 'admin'):
        icecast = icecast.replace(f'__{key.upper()}_PASSWORD__', credentials[key])
    liquidsoap = (SOURCE / 'deploy/liquidsoap/freo-test.liq.template').read_text().replace('__SOURCE_PASSWORD__', credentials['source'])
    ET.fromstring(icecast)
    icecast_path = RADIO / 'icecast.xml'
    liquidsoap_path = RADIO / 'freo-test.liq'
    icecast_tmp = stage(icecast_path, icecast, 'root', 'icecast', 0o640)
    liquidsoap_tmp = stage(liquidsoap_path, liquidsoap, 'root', 'freo-playout', 0o640)
    try:
        result = subprocess.run(['liquidsoap', '--check', str(liquidsoap_tmp)], capture_output=True, timeout=45)
        if result.returncode:
            raise SystemExit('Liquidsoap validation failed; previous configuration retained. Inspect a private validation run.')
        for path, tmp in ((icecast_path, icecast_tmp), (liquidsoap_path, liquidsoap_tmp)):
            if path.exists():
                shutil.copy2(path, path.with_suffix(path.suffix + '.previous'))
            os.replace(tmp, path)
        print('Validated and installed restricted radio configuration.')
    finally:
        icecast_tmp.unlink(missing_ok=True)
        liquidsoap_tmp.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
