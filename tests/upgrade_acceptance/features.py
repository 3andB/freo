import os,sys,json,subprocess,asyncio,re,uuid
from pathlib import Path
import aiohttp
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
os.environ['FREO_ENV_FILE']='/etc/freo/freo.env';sys.path.insert(0,'/opt/freo/current');os.chdir('/opt/freo/current')
from app import create_app
from app import models as m
from app.extensions import db
from app.services import public_api,listener_requests,playlists
app=create_app();E=Path('/root/freo-upgrade-tests')/sys.argv[1];E.mkdir(exist_ok=True)
results=[]
def note(name,**kw):
 results.append({'check':name,**kw});(E/'features.json').write_text(json.dumps(results,indent=2));print(name,flush=True)
with app.app_context():
 station=m.Station.query.filter_by(slug='acceptance').one();user=m.AdminUser.query.filter_by(installation_admin=True).one()
 api,key=public_api.create_credential(user,'Upgrade verification',[station.id]);api_id=api.id
 form={'requests_present':'yes','request_enabled':'yes','request_restrict_programming':'yes',**{'request_'+k:str(v) for k,v in listener_requests.DEFAULTS.items() if type(v)==int}}
 form.update(request_delay_songs='0',request_track_songs='0',request_artist_songs='0',request_cooldown_minutes='0')
 listener_requests.save_settings(station,form);db.session.commit()
base='http://209.38.64.12'
async def main():
 async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as s:
  for email,password in [('upgrade-dj@example.test','disposable upgrade DJ password'),('acceptance@example.test','private native acceptance passphrase')]:
   s.cookie_jar.clear()
   async with s.get(base+'/admin/login') as r:body=await r.text()
   csrf=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
   async with s.post(base+'/admin/login',data={'csrf':csrf,'email':email,'password':password}) as r:assert '/admin/login' not in str(r.url)
   note('Original account authenticates',account=email)
  async with s.get(base+'/admin/stations/acceptance/production') as r:body=await r.text()
  csrf=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
  for path,want in [('/api/v1/stations/acceptance',200),('/api/v1/stations/upgrade-two',403),('/api/v1/stations/acceptance/library/tracks',200)]:
   async with s.get(base+path,headers={'Authorization':'Bearer '+key}) as r:assert r.status==want,(path,r.status)
  note('Actual API bearer authentication and station scope')
  async with s.get(base+'/api/stations/acceptance/requests') as r:catalog=await r.json();assert r.status==200 and catalog['tracks'],catalog
  async with s.post(base+'/api/stations/acceptance/requests',headers={'X-Request-Token':catalog['token']},json={'track':catalog['tracks'][0]['uuid'],'nonce':str(uuid.uuid4())}) as r:
   request_result=await r.json();assert r.status in (200,201,202),request_result
  note('Listener request submitted over installed HTTP API')
  path='/admin/stations/acceptance/production'
  async with s.post(base+path+'/drafts',data={'csrf':csrf,'data':json.dumps({'mode':'voice','title':'Upgrade voice track'})}) as r:
   draft=await r.json();assert r.status==201,draft
  form=aiohttp.FormData();form.add_field('csrf',csrf);form.add_field('revision',str(draft['revision']));form.add_field('request_id',str(uuid.uuid4()));form.add_field('audio',Path('/root/freo-upgrade-tests/native-tone-1.mp3').read_bytes(),filename='voice.mp3',content_type='audio/mpeg')
  async with s.post(base+path+'/'+draft['id']+'/upload',data=form) as r:assert r.status==200,await r.text()
  for _ in range(120):
   async with s.get(base+path+'/'+draft['id']) as r:draft=await r.json()
   if draft['components'].get('render'):break
   assert not draft.get('error'),draft
   await asyncio.sleep(.5)
  else:raise AssertionError(('production did not render',draft))
  async with s.get(base+draft['components']['render']) as r:
   assert r.status==200;(E/'production-preview.mp3').write_bytes(await r.read())
  subprocess.run(['ffmpeg','-v','error','-i',str(E/'production-preview.mp3'),'-f','null','-'],check=True)
  async with s.post(base+path+'/'+draft['id']+'/save',data={'csrf':csrf,'revision':str(draft['revision']),'request_id':str(uuid.uuid4())}) as r:assert r.status==200,await r.text()
  for _ in range(120):
   async with s.get(base+path+'/'+draft['id']) as r:draft=await r.json()
   if draft.get('track_id'):break
   assert not draft.get('error'),draft
   await asyncio.sleep(.5)
  else:raise AssertionError(('production did not ingest',draft))
  note('Installed production and ingest workers created decoded voice track',track_id=draft['track_id'])
  with app.app_context():
   row=db.session.get(m.ApiCredential,api_id);public_api.revoke_credential(m.AdminUser.query.filter_by(installation_admin=True).one(),row);db.session.commit()
  async with s.get(base+'/api/v1/stations',headers={'Authorization':'Bearer '+key}) as r:assert r.status==401
  note('Revoked API credential rejected')
asyncio.run(main())
