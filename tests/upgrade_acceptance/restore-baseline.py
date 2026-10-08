"""Disposable-host acceptance recovery. Restores, never drops, a database.
Requires the baseline backup, known matching service identities and reviewed
original root paths. This is a test harness, not a general host-recovery CLI.
"""
import os,sys,json,subprocess,shutil
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
sys.path.insert(0,'/root/freo-v1-source')
from freo_ops import recovery
from freo_ops.__main__ import configuration,active_units
from psycopg2 import sql
os.umask(0o077)
E=Path('/root/freo-upgrade-tests');P=Path('/root/freo-upgrade-preservation')
name=sys.argv[1]
bundle=Path(sys.argv[2]) if len(sys.argv)>2 else E/'baseline.gpg'
assert name.isalnum()
save=E/('preserved-'+name);save.mkdir(mode=0o700)
report=json.loads((E/'baseline-verified.json').read_text())
oldroot=E/'baseline-verified'/('root-'+str(report['roots'].index('/opt/freo')))
values=configuration(oldroot/'.env')
units=active_units(include_updater=True)
subprocess.run(['systemctl','stop',*units,'icecast2.service'],check=True)
# Keep all failed state; never use pg_restore --clean or drop a database.
def psql(statement):
 subprocess.run(['runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1'],input=statement,text=True,check=True,stdout=subprocess.DEVNULL)
psql('ALTER ROLE freo CREATEDB;')
try:
 restored=recovery.restore(bundle,(P/'passphrase').read_bytes(),values['DATABASE_URL'],E/('recovered-'+name),preserve_ownership=True)
finally:psql('ALTER ROLE freo NOCREATEDB;')
assert restored['status']=='verified'
with recovery.unpack(bundle,(P/'passphrase').read_bytes()) as (_,manifest):
 entries=manifest['entries']
# The existing production-style DB is preserved under a unique failure name.
psql('ALTER DATABASE freo RENAME TO freo_preserved_'+name+'; ALTER DATABASE '+restored['database']+' RENAME TO freo;')
selected=[Path('/opt/freo'),Path('/var/lib/freo'),Path('/etc/freo'),Path('/etc/nginx'),Path('/srv/freo-upgrade-media')]
selected += list(Path('/etc/systemd/system').glob('freo*'))+[Path('/etc/systemd/system/icecast2.service'),Path('/etc/systemd/system/icecast2.service.d'),Path('/var/lib/freo-updates')]
for source in selected:
 if source.exists() or source.is_symlink():
  target=save/source.relative_to('/');target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(source),target)
if '/opt/freo' not in restored['roots']:
 Path('/opt/freo').mkdir(mode=0o755);Path('/opt/freo').chmod(0o755)
activated=[]
for index,namepath in enumerate(restored['roots']):
 original=Path(namepath)
 if namepath in ('/etc/postgresql','/etc/letsencrypt'):continue
 source=E/('recovered-'+name)/f'root-{index}'
 if original.exists() or original.is_symlink():raise RuntimeError('Refusing to merge recovered root: '+str(original))
 original.parent.mkdir(parents=True,exist_ok=True)
 subprocess.run(['cp','-a','--',str(source),str(original)],check=True)
 activated.append(index)
for entry in entries:
 if entry['root'] not in activated or entry['kind']!='symlink':continue
 target=Path(restored['roots'][entry['root']])/entry['path']
 target.unlink(missing_ok=True);target.symlink_to(entry['target'])
subprocess.run(['systemctl','disable','freo-production.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['nginx','-t'],check=True)
subprocess.run(['systemctl','restart','icecast2.service'],check=True)
subprocess.run(['systemctl','reload','nginx.service'],check=True)
active=json.loads((E/'baseline-active.json').read_text())
subprocess.run(['systemctl','start',*active],check=True)
(E/('recovery-'+name+'.json')).write_text(json.dumps({'status':'restored_and_activated','verified_database':restored['database'],'preserved_database':'freo_preserved_'+name,'preserved_host':str(save),'active_units':active}))
print('Verified 0.3.2 backup activated; prior database and host files retained')
