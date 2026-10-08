"""Installed suspension and reactivation; run on the disposable acceptance host."""
import http.client,json,subprocess,time
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'

def command(*args):
 p=subprocess.run(['freo-admin','hosting',*args],capture_output=True,text=True)
 value=json.loads(p.stdout);assert p.returncode==0,value
 return value

def stream():
 c=http.client.HTTPConnection('127.0.0.1',80,timeout=5)
 c.request('GET','/stream/acceptance',headers={'Host':'209.38.64.12'})
 r=c.getresponse();assert r.status==200,r.status;assert r.read(512)
 return c,r

def stopped():
 for port in (80,8001):
  c=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
  try:
   c.request('GET','/stream/acceptance' if port==80 else '/acceptance',headers={'Host':'209.38.64.12'})
   r=c.getresponse();assert r.status!=200,r.status
  except ConnectionError:pass
  finally:c.close()

results=[]
command('past-due');c,r=stream();r.close();c.close();results.append('past_due_broadcasts')
c,r=stream();command('suspend','--reason','acceptance-test')
# Consume already-buffered bytes and require closure, not just a hidden UI.
size=0
while data:=r.read(65536):
 size+=len(data);assert size<4_000_000
r.close();c.close();stopped();results.append('suspend_disconnects_listeners')
command('suspend','--reason','acceptance-test');results.append('suspend_idempotent')
subprocess.run(['systemctl','start','icecast2.service','freo-playout@acceptance.service','freo-mic.service'],capture_output=True)
stopped();results.append('direct_service_restart_refused')
command('activate');c,r=stream();r.close();c.close();results.append('reactivation_audio')
command('maintenance');stopped();results.append('maintenance_stops_audio')
command('activate');c,r=stream();r.close();c.close();results.append('maintenance_reactivation_audio')
Path('/root/freo-phase-b/status-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
