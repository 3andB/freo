"""Record/verify the real reboot surrounding an interrupted disposable restore."""
import json
from pathlib import Path
import socket
import subprocess
import sys
assert socket.gethostname() == 'Freo-v1-Test-1'
root = Path('/root/freo-phase-c')
boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
policy = json.loads(Path('/etc/freo/hosting.json').read_text())
assert policy['status'] == 'suspended'
if sys.argv[1:] == ['before']:
    (root/'final-reboot-before.json').write_text(json.dumps(dict(boot_id=boot, policy=policy)))
else:
    assert sys.argv[1:] == ['after']
    before = json.loads((root/'final-reboot-before.json').read_text())
    assert boot != before['boot_id'] and policy == before['policy']
    assert Path('/var/lib/freo-updates/maintenance').exists()
    assert Path('/var/lib/freo-hosting/inhibit').exists()
    activation = subprocess.run(['freo-admin','hosting','activate'], capture_output=True, text=True)
    assert activation.returncode == 6 and json.loads(activation.stdout)['error'] == 'recovery_required'
    units = ['icecast2.service', 'freo-mic.service', 'freo-playout@acceptance.service', 'freo-playout@upgrade-two.service']
    subprocess.run(['systemctl', 'start', *units], check=True, capture_output=True)
    for unit in units:
        state = subprocess.check_output(['systemctl','show',unit,'--property=ActiveState','--value'], text=True).strip()
        assert state == 'inactive', (unit, state)
        guards = subprocess.check_output(['systemctl','show',unit,'--property=DropInPaths','--value'], text=True)
        assert '/usr/local/lib/systemd/system/' in guards and '00-freo-lifecycle-guard.conf' in guards
    with socket.socket() as stream:
        stream.settimeout(3)
        assert stream.connect_ex(('127.0.0.1',8001)) != 0
    result = dict(reboot_verified=True, destination_policy_preserved=True,
                  explicit_service_starts_inhibited=True, persistent_guards_loaded=True,
                  public_icecast_port_closed=True, premature_activation_refused=True)
    (root/'final-reboot-inhibition.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
