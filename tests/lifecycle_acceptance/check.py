"""Destructive lifecycle checks: designated disposable fixture only."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
assert socket.gethostname()=='Freo-v1-Test-1'
E=Path('/root/freo-phase-c');E.mkdir(exist_ok=True)
label=sys.argv[1]
results=[]
def cli(*args,code=0):
    print('Running '+' '.join(args),flush=True)
    p=subprocess.run(['freo-admin',*args],capture_output=True,text=True)
    result=json.loads(p.stdout)
    results.append(dict(args=list(args),exit_code=p.returncode,result=result))
    (E/(label+'.json')).write_text(json.dumps(results,indent=2))
    assert p.returncode==code,(args,p.returncode,result)
    assert result['schema_version']==1 and result['success']==(code==0),result
    return result
status=cli('status');identity=status['installation_id']
assert status['application_ready']
assert cli('health')['health']=='healthy'
resources=cli('resources');assert resources['ram']['available_bytes']>0 and resources['media']['used_bytes']>0
cli('services','restart','--service','postgresql',code=2)
cli('backup','restore','--id','a'*32,'--confirm-installation','wrong',code=4)
cli('upgrade','apply','--version','../../etc/passwd',code=2)
p=subprocess.run(['runuser','-u','freo','--','freo-admin','status'],capture_output=True,text=True)
assert p.returncode==3 and json.loads(p.stdout)['error']=='unauthorized'
subprocess.run(['systemctl','stop','freo-ingest.service'],check=True)
assert cli('health',code=6)['health']=='degraded'
cli('services','recover')
cli('services','restart','--service','application')
cli('services','restart','--service','icecast')
backup=cli('backup','create')['backup']['id']
cli('backup','verify','--id',backup)
assert backup in [b['id'] for b in cli('backup','list')['backups']]
# An older backup must never replace current listener/storage authority.
cli('hosting','configure','--plan','custom','--stations','3','--listeners','5','--bitrate','128','--storage-gb','1')
policy=cli('hosting','suspend','--reason','lifecycle-test')['state']
assert cli('health')['health']=='intentionally_suspended'
cli('services','restart','--service','icecast',code=4)
cli('services','recover')
assert cli('health')['health']=='intentionally_suspended'
result=cli('backup','restore','--id',backup,'--confirm-installation',identity)
assert result['state']==policy
assert cli('health')['health']=='intentionally_suspended'
cli('hosting','activate')
assert cli('health')['health']=='healthy'
verified=cli('hosting','verify');assert verified['state']['limits']['listeners']==5
import http.client
connections=[]
try:
    for index in range(8):
        connection=http.client.HTTPConnection('127.0.0.1',8001,timeout=5)
        connection.request('GET','/'+('acceptance' if index%2 else 'upgrade-two'))
        response=connection.getresponse()
        if response.status==200:
            assert response.read(512);connections.append((connection,response))
        else:connection.close()
    assert len(connections)==5,len(connections)
finally:
    for connection,response in connections:
        response.close();connection.close()
cli('hosting','configure','--plan','starter')
print('Lifecycle sequence passed',flush=True)
