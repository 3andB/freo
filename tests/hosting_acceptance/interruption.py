"""Kill the real suspend command after its persistent inhibit, before service stop."""
import http.client,json,subprocess,time
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
connection=http.client.HTTPConnection('127.0.0.1',8001,timeout=15)
connection.request('GET','/acceptance');response=connection.getresponse()
assert response.status==200;assert response.read(1024)
code='''import os,signal
from freo_ops import hosting_admin
hosting_admin.stop_broadcasts=lambda:os.kill(os.getpid(),signal.SIGKILL)
hosting_admin.main(['hosting','suspend','--reason','interruption-acceptance'])
'''
result=subprocess.run(['/opt/freo/current/venv/bin/python','-c',code],cwd='/opt/freo/current',capture_output=True)
assert result.returncode==-9,result.returncode
assert Path('/var/lib/freo-hosting/inhibit').exists()
size=0
while data:=response.read(65536):
 size+=len(data);assert size<4_000_000
response.close();connection.close()
for mount in ('acceptance','upgrade-two'):
 c=http.client.HTTPConnection('127.0.0.1',8001,timeout=5);c.request('GET','/'+mount)
 r=c.getresponse();assert r.status!=200;r.close();c.close()
# The native engine, not a completed systemctl stop, enforced this interruption.
assert subprocess.run(['systemctl','is-active','--quiet','icecast2'],capture_output=True).returncode==0
p=subprocess.run(['freo-admin','hosting','suspend','--reason','interruption-acceptance'],capture_output=True,text=True)
assert p.returncode==0,p.stdout
value=json.loads(p.stdout);assert not value['verification']['broadcasting']
report=dict(suspend_process_killed=True,exit_code=result.returncode,native_engine_disconnected_listeners=True,new_listeners_refused_while_engine_running=True,repeated_suspend_reconciled=True,boot_before=Path('/proc/sys/kernel/random/boot_id').read_text().strip())
Path('/root/freo-phase-b/interruption-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
