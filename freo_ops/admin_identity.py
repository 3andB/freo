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


def install_maintenance_guards():
    """Persistent guards outside every customer restore root, including /etc."""
    root=Path('/usr/local/lib/systemd/system')
    body='[Unit]\nConditionPathExists=!/var/lib/freo-updates/maintenance\n'
    for unit in (Path(__file__).resolve().parents[1]/'deploy/systemd').iterdir():
        if unit.suffix not in ('.service','.timer'):continue
        if not (unit.name.startswith('freo') or unit.name=='icecast2.service'):continue
        directory=root/(unit.name+'.d');directory.mkdir(parents=True,exist_ok=True)
        for parent in (directory,root):
            if parent.is_symlink() or parent.stat().st_uid!=0 or parent.stat().st_mode & 0o022:
                raise h.HostingError('invalid_configuration','Unsafe persistent maintenance guard directory.')
            parent.chmod(0o755)
        target=directory/'00-freo-lifecycle-guard.conf'
        if target.exists():
            h.trusted(target)
            if target.read_text()!=body:
                raise h.HostingError('invalid_configuration','Customized lifecycle guard requires review.')
        else:
            with target.open('x') as stream:
                os.fchmod(stream.fileno(),0o644)
                stream.write(body);stream.flush();os.fsync(stream.fileno())

        for parent in (directory,root,root.parent,root.parent.parent):
            fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
