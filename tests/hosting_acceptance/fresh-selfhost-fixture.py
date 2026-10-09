"""Explicit disposable-host reset for a NEW self-hosted baseline, not recovery.

Customer recovery must preserve authority; recovery.py separately verifies that.
This root-only fixture archives the whole hosted destination and intentionally
starts a distinct self-hosted test installation from the verified 0.3.2 fixture.
"""
import json, os, socket, subprocess
from pathlib import Path
assert socket.gethostname()=='Freo-v1-Test-1' and os.geteuid()==0
E=Path('/root/freo-phase-b');saved=E/'authority-before-fresh-selfhost'
assert not saved.exists()
subprocess.run(['freo-admin','hosting','suspend','--reason','fresh-disposable-fixture'],check=True,capture_output=True)
rows=json.loads(subprocess.check_output(['systemctl','list-units','--all','--output=json','--type=service','--type=timer','freo*'],text=True))
subprocess.run(['systemctl','stop',*[r['unit'] for r in rows],'icecast2.service'],check=True)
os.rename('/var/lib/freo-hosting',saved)
# The established Phase A test helper retains the complete current tree/database,
# then attaches the verified clean 0.3.2 fixture and its matching original units.
subprocess.run(['/root/freo-upgrade-tool-venv/bin/python','/root/restore-baseline.py','phasebfinal'],check=True)
assert not Path('/etc/freo/hosting.json').exists()
assert not Path('/var/lib/freo-hosting').exists()
assert Path('/opt/freo/app/version.py').read_text().find('0.3.2')>=0
print('New self-hosted 0.3.2 fixture ready; hosted authority and all displaced data retained.')
