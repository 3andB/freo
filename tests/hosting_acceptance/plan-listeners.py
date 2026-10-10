"""Verify full advertised Starter/Pro listener capacities across real mounts."""
import concurrent.futures,http.client,json,subprocess,time
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
results=[]
for plan,limit in [('starter',100),('pro',250)]:
 p=subprocess.run(['freo-admin','hosting','configure','--plan',plan],capture_output=True,text=True)
 assert p.returncode==0,p.stdout
 time.sleep(2)
 def connect(index):
  connection=http.client.HTTPConnection('127.0.0.1',8001,timeout=15)
  connection.request('GET','/'+('acceptance' if index%2==0 else 'upgrade-two'))
  response=connection.getresponse()
  if response.status==200:assert response.read(256)
  return connection,response
 with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:rows=list(pool.map(connect,range(limit+16)))
 accepted=sum(r.status==200 for c,r in rows)
 try:assert accepted==limit,(plan,accepted)
 finally:
  for c,r in rows:r.close();c.close()
 results.append(dict(plan=plan,attempts=limit+16,accepted=accepted,rejected=16));time.sleep(3)
Path('/root/freo-phase-b/full-listener-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
p=subprocess.run(['freo-admin','hosting','configure','--plan','custom','--stations','3','--listeners','3','--bitrate','192','--storage-gb','1'],capture_output=True,text=True)
assert p.returncode==0,p.stdout
