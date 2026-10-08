"""Read-only installed 0.3.2 recovery acceptance on the named disposable host."""
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
import requests
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
assert not Path('/opt/freo/current').exists()
sys.path.insert(0,'/opt/freo');os.environ['FREO_ENV_FILE']='/opt/freo/.env'
from freo_ops import recovery
from freo_ops.__main__ import configuration
from freo_ops.releases import version_at
E=Path('/root/freo-upgrade-tests');name=sys.argv[1]
base=json.loads((E/'healthy-baseline.json').read_text())
assert version_at(Path('/opt/freo'))=='0.3.2'
for path,digest in base['files'].items():assert recovery.digest(Path(path))==digest,path
values=configuration('/opt/freo/.env');conn=recovery.connect(values['DATABASE_URL'])
assert recovery.schema_revision(conn)=='c83d4e5f9012'
with conn.cursor() as c:
 c.execute('SELECT id,slug,name,timezone,desired_state FROM stations ORDER BY id');assert list(map(list,c.fetchall()))==base['stations']
 c.execute('SELECT id,email,active,installation_admin FROM admin_users ORDER BY id');assert list(map(list,c.fetchall()))==base['users']
 c.execute('SELECT values FROM installation_settings WHERE id=1');assert c.fetchone()[0]==base['settings']
conn.close()
for account,password in [('acceptance@example.test','private native acceptance passphrase'),('upgrade-dj@example.test','disposable upgrade DJ password')]:
 with requests.Session() as s:
  s.trust_env=False
  body=s.get('http://127.0.0.1/admin/login',timeout=10).text
  csrf=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
  r=s.post('http://127.0.0.1/admin/login',data={'csrf':csrf,'email':account,'password':password},timeout=10)
  assert r.status_code==200 and '/admin/login' not in r.url,(account,r.status_code)
  for station in ('acceptance','upgrade-two','upgrade-stopped'):
   assert s.get('http://127.0.0.1/admin/stations/'+station+'/media',timeout=10).status_code==200
for slug in ('acceptance','upgrade-two'):
 subprocess.run(['ffmpeg','-v','error','-i','http://127.0.0.1:8001/'+slug,'-t','4','-f','null','-'],check=True,timeout=25)
assert subprocess.run(['systemctl','is-active','--quiet','freo-playout@upgrade-stopped.service']).returncode!=0
result=dict(status='passed',version='0.3.2',schema='c83d4e5f9012',media_checksums=len(base['files']),original_accounts_authenticated=2,station_pages=3,audio_streams_decoded=2,stopped_station_preserved=True)
(E/(name+'-recovery-check.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
