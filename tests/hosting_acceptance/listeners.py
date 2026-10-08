"""Run on the authorized disposable installation with real Icecast sources."""
import concurrent.futures
import http.client
import json
from pathlib import Path
import subprocess
import time

assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
E=Path('/root/freo-phase-b');E.mkdir(exist_ok=True)

def admin(*args):
 p=subprocess.run(['freo-admin','hosting',*args],capture_output=True,text=True)
 value=json.loads(p.stdout)
 assert p.returncode==0,value
 return value

def connect(index):
 # Exercise both Nginx public routes and direct Icecast listener mounts.
 public=index%2==0
 slug=('acceptance','upgrade-two')[index%2]
 connection=http.client.HTTPConnection('127.0.0.1',80 if public else 8001,timeout=10)
 connection.request('GET',('/stream/' if public else '/')+slug,headers={'Host':'209.38.64.12'})
 response=connection.getresponse()
 if response.status==200:
  assert response.read(1024)
 return connection,response

admin('configure','--plan','custom','--stations','3','--listeners','5','--bitrate','192','--storage-gb','1')
time.sleep(2)
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
 rows=list(pool.map(connect,range(16)))
accepted=[(c,r) for c,r in rows if r.status==200]
rejected=[(c,r) for c,r in rows if r.status!=200]
assert len(accepted)==5,[r.status for c,r in rows]
assert len(rejected)==11
for c,r in rejected:r.close();c.close()
# Full capacity must not block administrative verification/statistics.
full=admin('verify');assert full['verification']['listeners']==5,full
reduced=admin('configure','--plan','custom','--stations','3','--listeners','3','--bitrate','192','--storage-gb','1')
assert reduced['verification']['draining'],reduced
assert reduced['verification']['listeners']==5
for c,r in accepted:assert r.read(1024)
c,r=connect(0);assert r.status!=200;r.close();c.close()
for c,r in accepted[:3]:r.close();c.close()
time.sleep(2)
c,r=connect(0);assert r.status==200;assert r.read(1024)
r.close();c.close()
for c,r in accepted[3:]:r.close();c.close()
time.sleep(2)
result=dict(simultaneous_attempts=16,accepted=5,rejected=11,across_two_mounts=True,public_and_direct=True,stats_at_capacity=True,reduction_preserved_five_sessions=True,reconnect_after_drain=True)
(E/'listener-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
