"""Destination authority preservation for explicit root-run recovery attachment.

Isolated recovery never changes live authority. Attach tools must keep this
context around replacement of customer config, code, units, and database.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
from . import hosting as h


@contextmanager
def preserve_authority():
    if os.geteuid()!=0:
        raise h.HostingError('unauthorized','Recovery attachment requires root.')
    with h.administrative_lock():
        policy=h.read()
        if not policy['hosted']:
            yield
            return
        # This state is outside both /etc/freo and /var/lib/freo customer roots.
        h.atomic(h.STATE/'inhibit',True)
        from .hosting_admin import stop_broadcasts
        stop_broadcasts()
        saved={}
        for path in (h.CONFIG,Path('/etc/freo/hosting-storage.json')):
            h.trusted(path);saved[str(path)]=json.loads(path.read_text())
        h.atomic(h.STATE/'recovery-authority.json',saved,0o600)
        try:
            yield
        finally:
            restore_authority()


def restore_authority():
    """Idempotent continuation after an interrupted attachment; never activates."""
    if os.geteuid()!=0:
        raise h.HostingError('unauthorized','Recovery attachment requires root.')
    path=h.STATE/'recovery-authority.json'
    h.trusted(path)
    saved=json.loads(path.read_text())
    if set(saved)!={'/etc/freo/hosting.json','/etc/freo/hosting-storage.json'}:
        raise h.HostingError('invalid_configuration','Recovery authority journal is invalid.')
    h.validate(saved['/etc/freo/hosting.json'])
    for filename,value in saved.items():
        target=Path(filename);target.parent.mkdir(parents=True,exist_ok=True)
        h.atomic(target,value)
    # Standalone enforcement survives attaching older application code.
    for unit in ('icecast2.service','freo-playout.service','freo-playout@.service','freo-mic.service'):
        directory=Path('/etc/systemd/system')/(unit+'.d');directory.mkdir(exist_ok=True)
        (directory/'hosting-authority.conf').write_text('[Service]\nExecCondition=/usr/bin/python3 /usr/local/lib/freo-hosting/guard.py\n')
    web=Path('/etc/systemd/system/freo.service.d');web.mkdir(exist_ok=True)
    (web/'hosting-authority.conf').write_text('[Service]\nExecCondition=/usr/bin/python3 /usr/local/lib/freo-hosting/guard.py --web\n')
    protect_request_spooling()
    subprocess.run(['systemctl','daemon-reload'],check=True)


def protect_request_spooling():
    """Hosted dedicated-server HTTP policy: let Flask reserve before body spooling."""
    path=Path('/etc/nginx/conf.d/freo-hosting-bodies.conf')
    body='proxy_request_buffering off;\nproxy_http_version 1.1;\n'
    if path.is_symlink() or (path.exists() and path.read_text()!=body):
        raise h.HostingError('invalid_configuration','Unmanaged hosting proxy configuration requires review.')
    path.write_text(body);path.chmod(0o644)
    subprocess.run(['nginx','-t'],check=True,capture_output=True)
    subprocess.run(['systemctl','reload','nginx'],check=True,capture_output=True)
