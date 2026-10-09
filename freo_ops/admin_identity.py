"""Local administrative identity; standard library only for early installation."""
import json
import os
from pathlib import Path
import shlex
import uuid
from . import hosting as h

STATE=Path('/var/lib/freo-admin')


def initialize():
    STATE.mkdir(mode=0o700,exist_ok=True)
    info=STATE.lstat()
    if STATE.is_symlink() or info.st_uid!=0 or info.st_mode & 0o077:
        raise h.HostingError('invalid_configuration','Administrative state must be root-owned and private.')
    path=STATE/'identity.json'
    if not path.exists():
        identifier=None
        directory='/var/lib/freo/central-api'
        for env in (Path('/etc/freo/freo.env'),Path('/opt/freo/.env')):
            if env.exists():
                h.trusted(env)
                for line in env.read_text().splitlines():
                    if line.startswith('FREO_API_STATE_DIR='):
                        parts=shlex.split(line.split('=',1)[1],comments=True)
                        if len(parts)==1:directory=parts[0]
                break
        saved=Path(directory)/'identity.json'
        try:
            if saved.is_file() and not saved.is_symlink():
                identifier=str(uuid.UUID(json.loads(saved.read_text())['installation_id']))
        except (OSError,ValueError,KeyError):pass
        h.atomic(path,dict(installation_id=identifier or str(uuid.uuid4())),0o600)
    h.trusted(path)
    return str(uuid.UUID(json.loads(path.read_text())['installation_id']))
