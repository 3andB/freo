"""Real PostgreSQL plan transitions and concurrent station allocation."""
import concurrent.futures,json,os,subprocess,sys,time
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
os.chdir('/opt/freo/current');sys.path.insert(0,str(Path.cwd()));os.environ['FREO_ENV_FILE']='/etc/freo/freo.env'

def admin(*args,code=0):
 p=subprocess.run(['freo-admin','hosting',*args],capture_output=True,text=True)
 value=json.loads(p.stdout);assert p.returncode==code,(p.returncode,value)
 return value

from app import create_app
from app.models import Station
from app.services.stations import request_delete
from app.services.station_lifecycle import process_station
app=create_app()
with app.app_context():
 for row in Station.query.filter(Station.slug.like('hosting-capacity-%'),Station.deleted_at.is_(None)).all():
  request_delete(row);process_station(row)

admin('configure','--plan','starter')
assert admin('status')['state']['limits']==dict(stations=3,listeners=100,bitrate_kbps=128,storage_gb=25)
admin('configure','--plan','pro')
assert admin('status')['state']['limits']==dict(stations=10,listeners=250,bitrate_kbps=128,storage_gb=50)

def create(index):
 code='''from app import create_app
from app.services.stations import create_station
from freo_ops.hosting import HostingError
import sys,json
app=create_app()
with app.app_context():
 try:
  s=create_station('Hosted concurrency '+sys.argv[1], 'hosting-capacity-'+sys.argv[1])
  print(json.dumps({'created':s.id}))
 except HostingError as e:print(json.dumps(e.response()))
'''
 p=subprocess.run(['/opt/freo/current/venv/bin/python','-c',code,str(int(time.time()))+'-'+str(index)],cwd='/opt/freo/current',capture_output=True,text=True,env=dict(os.environ,FREO_ENV_FILE='/etc/freo/freo.env'))
 assert p.returncode==0,p.stderr
 return json.loads(p.stdout)
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:rows=list(pool.map(create,range(10)))
assert sum('created' in row for row in rows)==7,rows
assert sum(row.get('error')=='station_limit_exceeded' for row in rows)==3,rows
rejected=admin('configure','--plan','starter',code=4)
assert rejected['error']=='station_limit_exceeded' and rejected['state']['plan']=='pro',rejected
from app import create_app
from app.extensions import db
from app.models import Station
from app.services.stations import request_delete
from app.services.station_lifecycle import process_station
app=create_app()
with app.app_context():
 for row in Station.query.filter(Station.slug.like('hosting-capacity-%'),Station.deleted_at.is_(None)).all():
  request_delete(row);process_station(row)
admin('configure','--plan','starter')
admin('configure','--plan','custom','--stations','3','--listeners','3','--bitrate','192','--storage-gb','1')
report=dict(starter_defaults=True,pro_defaults=True,concurrent_attempts=10,created=7,rejected=3,downgrade_refused_without_state_change=True,created_test_stations_retired=True,custom_plan=True)
Path('/root/freo-phase-b/plan-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
