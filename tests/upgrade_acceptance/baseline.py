import os,sys,subprocess,json,shutil
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
sys.path.insert(0,'/opt/freo')
from freo_ops import recovery
from freo_ops.__main__ import configuration,inventory,active_units
os.umask(0o077)
E=Path('/root/freo-upgrade-tests');P=Path('/root/freo-upgrade-preservation')
units=active_units(include_updater=True)
(E/'baseline-active.json').write_text(json.dumps(units))
subprocess.run(['systemctl','stop',*units],check=True)
try:
 if not Path('/srv/freo-upgrade-media').exists():
  shutil.move('/var/lib/freo/media','/srv/freo-upgrade-media')
  with open('/opt/freo/.env','a') as f:f.write('\nFREO_MEDIA_ROOT=/srv/freo-upgrade-media\n')
 d=Path('/etc/systemd/system/freo-ingest.service.d');d.mkdir(exist_ok=True,mode=0o755);d.chmod(0o755)
 (d/'custom-media.conf').write_text('[Service]\nReadWritePaths=\nReadWritePaths=/var/lib/freo/uploads /srv/freo-upgrade-media\n');(d/'custom-media.conf').chmod(0o644)
 values=configuration('/opt/freo/.env')
 env=dict(os.environ,**{k:v for k,v in values.items() if v is not None},FREO_ENV_FILE='/opt/freo/.env')
 for slug in ('acceptance','upgrade-two','upgrade-stopped'):
  subprocess.run(['/opt/freo/venv/bin/flask','--app','wsgi:app','station','render',slug],cwd='/opt/freo',env=env,check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','start',*units],check=True)
 import time;time.sleep(6)
 for unit in ('freo.service','freo-ingest.service','freo-automation.service','freo-stats.service'):
  subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
 subprocess.run(['systemctl','stop',*active_units(include_updater=True)],check=True)
 roots=inventory('/opt/freo/.env',values)+[Path('/opt/freo')]
 result=recovery.create(values['DATABASE_URL'],roots,E/'baseline.gpg',(P/'passphrase').read_bytes(),version='0.3.2',media_root=values['FREO_MEDIA_ROOT'],upload_root='/var/lib/freo/uploads')
 (E/'baseline-backup.json').write_text(json.dumps(result))
 verified=recovery.restore(E/'baseline.gpg',(P/'passphrase').read_bytes(),configuration(P/'verification.env')['DATABASE_URL'],E/'baseline-verified',preserve_ownership=True)
 (E/'baseline-verified.json').write_text(json.dumps(verified))
 connection=recovery.connect(values['DATABASE_URL'])
 (E/'baseline-counts.json').write_text(json.dumps(recovery.database_inventory(connection),indent=2));connection.close()
 print(json.dumps({'status':verified['status'],'database':verified['database']}))
finally:
 subprocess.run(['systemctl','start',*units],check=True)
