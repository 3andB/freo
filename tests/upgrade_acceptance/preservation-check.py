import json,sys,subprocess
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
sys.path.insert(0,'/root/freo-v1-source')
from freo_ops import recovery
from freo_ops.__main__ import configuration
E=Path('/root/freo-upgrade-tests');name=sys.argv[1]
baseline=json.loads((E/'healthy-baseline.json').read_text())
report=json.loads((E/'baseline-verified.json').read_text())
def old(path):
 path=Path(path)
 for index,root in enumerate(map(Path,report['roots'])):
  if path==root or path.is_relative_to(root):return E/'baseline-verified'/f'root-{index}'/path.relative_to(root)
 raise KeyError(path)
values=configuration('/etc/freo/freo.env');prior=configuration(old('/opt/freo/.env'))
assert all(values.get(k)==v for k,v in prior.items()),'original environment changed'
assert values.get('FREO_PROVIDER_ENCRYPTION_KEY'),'new encryption key missing'
for path,digest in baseline['files'].items():assert recovery.digest(Path(path))==digest,path
secrets=Path('/etc/freo/secrets');secret_files=[p for p in secrets.rglob('*') if p.is_file()]
for path in secret_files:
 previous=old(path)
 if previous.exists():assert recovery.digest(path)==recovery.digest(previous),str(path)
custom=Path('/etc/systemd/system/freo-ingest.service.d/custom-media.conf');assert custom.read_bytes()==old(custom).read_bytes()
conn=recovery.connect(values['DATABASE_URL'])
with conn.cursor() as c:
 c.execute('SELECT id,slug,name,timezone,desired_state FROM stations ORDER BY id');stations=c.fetchall()
 assert list(map(list,stations))==baseline['stations']
 c.execute('SELECT id,email,active,installation_admin FROM admin_users WHERE id IN (1,2) ORDER BY id');users=c.fetchall();assert list(map(list,users))==baseline['users']
 c.execute("SELECT count(*) FROM selection_decisions WHERE status='started'");history=c.fetchone()[0];assert history>=baseline['confirmed_history']
 for table in ('tracks','playlists','playlist_items','rotations','rotation_slots','clocks','clock_slots','schedule_assignments','imaging_assets','imaging_groups','imaging_group_assets'):
  c.execute('SELECT count(*) FROM '+table);assert c.fetchone()[0]>=baseline['counts'][table]['rows'],table
 c.execute('SELECT values FROM installation_settings WHERE id=1');assert c.fetchone()[0]==baseline['settings']
conn.close()
assert subprocess.run(['systemctl','is-active','--quiet','freo-playout@upgrade-stopped.service']).returncode!=0
result={'status':'passed','stations':stations,'original_accounts':len(users),'original_media_files':len(baseline['files']),'original_environment_keys':len(prior),'station_secret_files_checked':len(secret_files),'historical_starts_before':baseline['confirmed_history'],'historical_starts_after':history,'custom_media_root_preserved':True,'custom_ingest_override_preserved':True,'stopped_station_preserved':True}
(E/(name+'-preservation.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
