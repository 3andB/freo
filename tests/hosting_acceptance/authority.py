"""Root authorization, strict JSON, and fail-closed missing-policy recovery."""
import http.client, json, os, socket, subprocess, time
from pathlib import Path
assert socket.gethostname()=='Freo-v1-Test-1'
E=Path('/root/freo-phase-b');config=Path('/etc/freo/hosting.json')
policy=json.loads(config.read_text());assert policy['status']=='active'
def admin(*args,code=0,as_user=None):
    command=['freo-admin','hosting',*args]
    if as_user:command=['runuser','-u',as_user,'--',*command]
    result=subprocess.run(command,capture_output=True,text=True)
    value=json.loads(result.stdout);assert result.returncode==code,(result.returncode,value)
    return value
assert admin('status',as_user='freo',code=3)['error']=='unauthorized'
assert admin('configure','--plan','custom',code=2)['error']=='invalid_arguments'
assert admin('suspend','--reason','x\nunsafe',code=2)['error']=='invalid_arguments'
for user in ('freo','freo-ingest','freo-automation','freo-playout'):
    check=subprocess.run(['runuser','-u',user,'--','test','-w',str(config)])
    assert check.returncode!=0,user
assert admin('status')['state']==policy
# Root-only fault injection: missing policy cannot mean unrestricted operation.
saved=E/'missing-policy-original.json';assert not saved.exists()
os.replace(config,saved)
try:
    assert admin('status',code=5)['state']=={'restricted':True}
    time.sleep(2)
    for port,path in ((80,'/stream/acceptance'),(8001,'/upgrade-two'),(80,'/admin')):
        client=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        client.request('GET',path,headers={'Host':'209.38.64.12'})
        response=client.getresponse();assert response.status!=200,(port,path)
        response.close();client.close()
    limits=policy['limits']
    repaired=admin('configure','--plan',policy['plan'],'--stations',str(limits['stations']),
        '--listeners',str(limits['listeners']),'--bitrate',str(limits['bitrate_kbps']),
        '--storage-gb',str(limits['storage_gb']))
    assert repaired['state']['status']=='maintenance'
    assert not repaired['verification']['broadcasting']
    assert admin('activate')['verification']['broadcasting']
finally:
    # Retain evidence; never silently restore/activate on a failed test.
    pass
report=dict(nonroot_exit=3,invalid_arguments_exit=2,missing_configuration_exit=5,
            policy_not_customer_writable=True,missing_policy_blocks_public_audio=True,
            repair_retains_maintenance=True,explicit_reactivation_verified=True)
(E/'authority-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
