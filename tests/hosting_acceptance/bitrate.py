"""Actual encoder changes and rejected conflicting plan reduction."""
import json,os,subprocess,sys
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
os.chdir('/opt/freo/current');sys.path.insert(0,str(Path.cwd()));os.environ['FREO_ENV_FILE']='/etc/freo/freo.env'
from app import create_app
from app.extensions import db
from app.models import Station,AdminUser
from app.services.station_audio import queue_settings,process_audio,validate_settings,active_settings
app=create_app()
with app.app_context():
 station=Station.query.filter_by(slug='acceptance').one();original=station.stream.bitrate;original_settings=active_settings(station.stream)
 def change(rate):
  db.session.refresh(station.stream)
  user=AdminUser.query.filter_by(installation_admin=True).first()
  queue_settings(station,validate_settings(dict(original_settings,bitrate=rate)),station.stream.audio_revision,user)
  db.session.commit();process_audio(station)
 try:
  change(128)
  p=subprocess.run(['ffprobe','-v','error','-read_intervals','%+#50','-show_entries','stream=codec_name,bit_rate','-of','json','http://127.0.0.1:8001/acceptance'],capture_output=True,text=True,timeout=20,check=True)
  observed=json.loads(p.stdout)['streams'][0];assert observed['bit_rate']=='128000',observed
  p=subprocess.run(['freo-admin','hosting','configure','--plan','custom','--stations','3','--listeners','3','--bitrate','64','--storage-gb','1'],capture_output=True,text=True)
  value=json.loads(p.stdout);assert p.returncode==4 and value['error']=='bitrate_limit_exceeded',value
  assert value['state']['limits']['bitrate_kbps']==192 and value['state']['status']=='active'
  Path('/root/freo-phase-b/bitrate-results.json').write_text(json.dumps(dict(actual_stream=observed,invalid_downgrade_rejected=True),indent=2))
  print('Actual 128 kbps MP3 verified; conflicting 64 kbps downgrade refused.')
 finally:change(original)
