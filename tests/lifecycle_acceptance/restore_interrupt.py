"""Kill live restore after retaining the old DB; reboot, then CLI-only recovery."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
assert socket.gethostname()=='Freo-v1-Test-1'
source=Path('/opt/freo/current').resolve()
sys.path.insert(0,str(source))
E=Path('/root/freo-phase-c')
if sys.argv[1:2]==['child']:
    from freo_ops import admin,admin_backup
    real=admin_backup.pg
    def pg(statement):
        result=real(statement)
        if statement.startswith('ALTER DATABASE ') and 'RENAME TO "freo_preserved_' in statement:
            os.kill(os.getpid(),signal.SIGKILL)
        return result
    admin_backup.pg=pg
    raise SystemExit(admin.main(['backup','restore','--id',sys.argv[2],'--confirm-installation',sys.argv[3]]))
result=json.loads(subprocess.check_output(['freo-admin','backup','list']))
status=json.loads(subprocess.check_output(['freo-admin','status']))
backup=max((row for row in result['backups'] if row['role']=='backup' and row.get('version')==status['version'] and row['status'].startswith('integrity_verified')),key=lambda row:row['created_at'])['id']
identity=status['installation_id']
subprocess.run(['freo-admin','hosting','suspend','--reason','restore-interruption'],check=True,capture_output=True)
p=subprocess.run([str(source/'venv/bin/python'),'-I',__file__,'child',backup,identity],capture_output=True,text=True)
assert p.returncode==-signal.SIGKILL,(p.returncode,p.stdout)
assert Path('/var/lib/freo-updates/maintenance').exists()
assert Path('/var/lib/freo-hosting/inhibit').exists()
(E/'restore-interruption.json').write_text(json.dumps(dict(killed_after='retaining_old_database',backup_id=backup,installation_id=identity),indent=2))
print('Restore interrupted safely; actual reboot and services recover remain.',flush=True)
