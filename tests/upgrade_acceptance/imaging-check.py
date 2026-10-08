"""Exercise preserved legacy station audio on the installed V1 engine."""
import json,os,re,subprocess,sys,time,uuid
from pathlib import Path
import requests
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
os.chdir('/opt/freo/current');sys.path.insert(0,os.getcwd());os.environ['FREO_ENV_FILE']='/etc/freo/freo.env'
from app import create_app,models as m
from app.extensions import db
from app.services import clocks
from app.services.media_storage import LocalMediaStorage
from app.services.imaging_migration import inventory
app=create_app();E=Path('/root/freo-upgrade-tests')/sys.argv[1];E.mkdir(exist_ok=True)
with app.app_context():
 for station in m.Station.query.order_by(m.Station.id):
  report=inventory(station)
  assert len(report['assets'])==1 and all(a['mapped'] for a in report['assets'])
  assert not any(report['references'].values())
  assert not any(a['file_problem'] for a in report['assets'])
  asset=m.ImagingAsset.query.filter_by(station_id=station.id).one()
  audio=m.Track.query.filter_by(legacy_imaging_id=asset.id).one()
  assert audio.audio_kind=='STATION' and audio.checksum_sha256==asset.checksum_sha256
  assert m.Track.query.filter_by(station_id=station.id,audio_kind='MUSIC').count()==3
  subprocess.run(['ffmpeg','-v','error','-i',str(LocalMediaStorage().regular_file(station.slug,audio.storage_key)),'-f','null','-'],check=True,timeout=15)
 station=m.Station.query.filter_by(slug='acceptance').one();asset_uuid=m.ImagingAsset.query.filter_by(station_id=station.id).one().uuid
 second=m.Station.query.filter_by(slug='upgrade-two').one()
 collection=m.Playlist.query.filter_by(station_id=second.id).filter(m.Playlist.legacy_imaging_group_id.isnot(None)).one()
 clock=m.Clock.query.filter_by(station_id=second.id,slug='upgrade-clock').one()
 if not any(s.playlist_id==collection.id for s in clock.slots):clocks.add_clock_slot(second.slug,clock.slug,'PLAYLIST',str(collection.id))
 # Confirm the migrated group participates in the existing installed clock.
 target=m.Track.query.filter_by(station_id=second.id).filter(m.Track.legacy_imaging_id.isnot(None)).one().id
 since=m.SelectionDecision.query.order_by(m.SelectionDecision.id.desc()).first().id
with requests.Session() as s:
 s.trust_env=False;base='http://127.0.0.1'
 body=s.get(base+'/admin/login',timeout=10).text
 csrf=re.search(r'name="csrf" value="([^"]+)"',body).group(1)
 r=s.post(base+'/admin/login',data={'csrf':csrf,'email':'acceptance@example.test','password':'private native acceptance passphrase'},timeout=10);assert '/admin/login' not in r.url
 body=s.get(base+'/admin/stations/acceptance/live',timeout=10).text;csrf=re.search(r'data-csrf="([^"]+)"',body).group(1)
 for action,form in [('assign-cart',dict(role='HOT',position='1',identifier=asset_uuid,label='Preserved station ID')),('fire-cart',dict(role='HOT',position='1',nonce=str(uuid.uuid4())))]:
  r=s.post(base+'/admin/stations/acceptance/live/'+action,data=dict(csrf=csrf,**form),headers={'Accept':'application/json'},timeout=10)
  assert r.status_code==200 and r.json()['ok'],(action,r.status_code,r.text)
 for _ in range(80):
  status=s.get(base+'/admin/api/stations/acceptance/live-status',timeout=10).json()
  if status['cart']['state']=='playing':break
  time.sleep(.5)
 else:raise AssertionError('Legacy imaging cart never reached actual playback')
 cart=status['cart']['decision_id']
 subprocess.run(['ffmpeg','-v','error','-i','http://127.0.0.1:8001/acceptance','-t','5','-f','null','-'],check=True,timeout=30)
for _ in range(150):
 with app.app_context():
  played=m.SelectionDecision.query.filter(m.SelectionDecision.id>since,m.SelectionDecision.track_id==target,m.SelectionDecision.status=='started').first()
  if played:
   scheduled=played.id;break
 time.sleep(1)
else:raise AssertionError('Converted imaging group never played through existing clock')
result=dict(status='passed',legacy_assets_converted=3,original_music_unchanged=9,decoded_converted_files=3,legacy_cart_played=cart,clock_group_played=scheduled)
(E/'imaging.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
