"""Kill the real updater at its migration boundary, then recover through the CLI.

The child uses the verified candidate's tools (the Phase A supported upgrade
entrypoint). Only process death is injected; backup, SQL, services, signatures,
restore and activation are real. No production host is accepted.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
assert socket.gethostname()=='Freo-v1-Test-1'
SOURCE=Path('/root/freo-v1-source')
E=Path('/root/freo-phase-c')
sys.path.insert(0,str(SOURCE))
version=os.environ.get('FREO_TEST_VERSION','1.0.0-dev.8')
selfhost=os.environ.get('FREO_TEST_SELFHOST')=='1'
if sys.argv[1:] == ['child']:
    from freo_ops import admin,recovery
    actual=recovery.run
    def run(args,**kwargs):
        if args[-2:]==['db','upgrade']:
            os.kill(os.getpid(),signal.SIGKILL)
        return actual(args,**kwargs)
    recovery.run=run
    raise SystemExit(admin.main(['upgrade','apply','--version',version]))
python='/root/freo-upgrade-tool-venv/bin/python'
result=subprocess.run([python,'-I',__file__,'child'],capture_output=True,text=True)
assert result.returncode==-signal.SIGKILL,result.stdout
journal=json.loads(Path('/var/lib/freo-updates/journal.json').read_text())
assert journal['phase']=='migration',journal['phase']
assert Path('/var/lib/freo-updates/maintenance').exists()
cli=['/usr/local/sbin/freo-admin']
def command(*args,expected=0):
    print('Running '+' '.join(args),flush=True)
    p=subprocess.run([*cli,*args],capture_output=True,text=True)
    value=json.loads(p.stdout)
    assert p.returncode==expected,(p.returncode,value)
    return value
result=command('services','recover',expected=6)
assert result['error']=='recovery_required'
backup=result['backup_id']
identity=command('status')['installation_id']
restored=command('backup','restore','--id',backup,'--confirm-installation',identity)
if selfhost:
    assert restored['state']['hosted'] is False
    assert command('health')['health']=='healthy'
else:
    assert restored['state']['status']=='suspended'
    assert command('health')['health']=='intentionally_suspended'
(E/('interruption-selfhost.json' if selfhost else 'interruption.json')).write_text(json.dumps(dict(killed_at='migration',recovery_required=True,backup_id=backup,restore=restored),indent=2))
print('Interrupted upgrade recovered; destination authority preserved',flush=True)
