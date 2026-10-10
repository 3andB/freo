"""Attach the verified pre-hosting Phase A backup on the disposable host.

All displaced roots and the current database are retained. Never run elsewhere.
The recovery library deliberately restores only to isolated destinations; this
fixture performs the explicit, destination-specific attachment under authority.
"""
import json, os, shutil, subprocess, sys
from pathlib import Path
assert subprocess.check_output(['hostname'], text=True).strip() == 'Freo-v1-Test-1'
sys.path.insert(0, '/root/freo-phase-b-source')
from freo_ops import hosting, recovery
from freo_ops.hosting_recovery import preserve_authority
from freo_ops.__main__ import active_units, configuration
os.umask(0o077)
E = Path('/root/freo-phase-b')
P = Path('/root/freo-upgrade-preservation')
name = sys.argv[1]
assert name.isalnum()
save = E / ('preserved-' + name)
save.mkdir(mode=0o700)
subprocess.run(['freo-admin', 'hosting', 'suspend', '--reason', 'recovery-test'], check=True, capture_output=True)
policy = hosting.read()
assert policy['hosted'] and policy['status'] == 'suspended'
values = configuration('/etc/freo/freo.env')
def psql(statement):
    subprocess.run(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-v', 'ON_ERROR_STOP=1'],
                   input=statement, text=True, check=True, stdout=subprocess.DEVNULL)
with preserve_authority():
    units = active_units(include_updater=True)
    subprocess.run(['systemctl', 'stop', *units, 'icecast2.service'], check=True)
    psql('ALTER ROLE freo CREATEDB;')
    try:
        restored = recovery.restore(E/'phase-a.gpg', (P/'passphrase').read_bytes(), values['DATABASE_URL'],
                                    E/('recovered-'+name), preserve_ownership=True)
    finally:
        psql('ALTER ROLE freo NOCREATEDB;')
    assert restored['status'] == 'verified'
    with recovery.unpack(E/'phase-a.gpg', (P/'passphrase').read_bytes()) as (_, manifest):
        entries = manifest['entries']
    psql('ALTER DATABASE freo RENAME TO freo_preserved_'+name+'; ALTER DATABASE '+restored['database']+' RENAME TO freo;')
    selected = [Path(p) for p in ('/opt/freo','/var/lib/freo','/etc/freo','/etc/nginx','/srv/freo-upgrade-media','/var/lib/freo-updates')]
    selected += list(Path('/etc/systemd/system').glob('freo*'))
    selected += [Path('/etc/systemd/system/icecast2.service'), Path('/etc/systemd/system/icecast2.service.d')]
    for source in selected:
        if source.exists() or source.is_symlink():
            target = save/source.relative_to('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), target)
    activated = []
    for index, root in enumerate(restored['roots']):
        if root in ('/etc/postgresql', '/etc/letsencrypt'):
            continue
        target = Path(root)
        assert not target.exists() and not target.is_symlink(), root
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cp', '-a', '--', str(E/('recovered-'+name)/f'root-{index}'), root], check=True)
        activated.append(index)
    for entry in entries:
        if entry['root'] in activated and entry['kind'] == 'symlink':
            target = Path(restored['roots'][entry['root']])/entry['path']
            target.unlink(missing_ok=True)
            target.symlink_to(entry['target'])
assert hosting.read() == policy
assert (hosting.STATE/'inhibit').exists()
subprocess.run(['systemctl', 'start', 'icecast2.service', 'freo.service'], check=True)
for unit in ('icecast2.service', 'freo.service'):
    assert subprocess.run(['systemctl','is-active','--quiet',unit]).returncode != 0
result = subprocess.run(['freo-admin','hosting','status'],capture_output=True,text=True,check=True)
state = json.loads(result.stdout)
assert state['state'] == policy and state['inhibited'] and not state['compatible_release']
result = subprocess.run(['freo-admin','hosting','activate'],capture_output=True,text=True)
assert result.returncode == 6 and json.loads(result.stdout)['error'] == 'incompatible_release'
report = dict(status='passed', restored_version=restored['version'], policy_preserved=True,
              older_code_blocked=True, activation_refused=True, suspended=True,
              preserved_database='freo_preserved_'+name, preserved_host=str(save))
(E/('recovery-'+name+'.json')).write_text(json.dumps(report,indent=2))
print(json.dumps(report))
