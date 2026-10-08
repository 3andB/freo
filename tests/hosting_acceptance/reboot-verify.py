"""Run after rebooting the suspended disposable installation."""
import http.client,json,subprocess
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
path=Path('/root/freo-phase-b/interruption-results.json');report=json.loads(path.read_text())
assert report['boot_before']!=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
p=subprocess.run(['freo-admin','hosting','verify'],capture_output=True,text=True);assert p.returncode==0,p.stdout
value=json.loads(p.stdout);assert value['state']['status']=='suspended' and not value['verification']['broadcasting']
c=http.client.HTTPConnection('127.0.0.1',80,timeout=5);c.request('GET','/admin',headers={'Host':'209.38.64.12'});r=c.getresponse();body=r.read().decode();assert r.status==503 and 'Service suspended' in body;c.close()
report.update(reboot_preserved_suspension=True,customer_notice=True)
p=subprocess.run(['freo-admin','hosting','activate'],capture_output=True,text=True);assert p.returncode==0,p.stdout
c=http.client.HTTPConnection('127.0.0.1',8001,timeout=5);c.request('GET','/acceptance');r=c.getresponse();assert r.status==200 and r.read(8192);r.close();c.close()
report['reactivated_after_reboot']=True
path.write_text(json.dumps(report,indent=2));print(json.dumps(report))
