"""Exact byte quota tests through installed writers; retains original media."""
import concurrent.futures,json,os,subprocess,time
from pathlib import Path
assert subprocess.check_output(['hostname'],text=True).strip()=='Freo-v1-Test-1'
os.chdir('/opt/freo/current')
import sys
sys.path.insert(0,str(Path.cwd()))
from freo_ops import hosting_storage as storage
E=Path('/root/freo-phase-b');fixture=Path('/srv/freo-upgrade-media/hosting-quota-fixture.bin')
assert not fixture.exists()
created=[]

def write(index):
 path=Path('/var/lib/freo/uploads')/('hosting-concurrent-'+str(index));created.append(path)
 code='''import sys
from pathlib import Path
from freo_ops.hosting_storage import write
p=Path(sys.argv[1])
try:
 with p.open('xb',buffering=0) as output:write(output,b'x'*65536)
except Exception:
 p.unlink(missing_ok=True)
 raise
'''
 return subprocess.run(['runuser','-u','freo','--','/opt/freo/current/venv/bin/python','-c',code,str(path)],cwd='/opt/freo/current',capture_output=True).returncode

try:
 used=storage.usage()['used_bytes']
 with fixture.open('xb') as output:output.truncate(1_000_000_000-used-100_000)
 fixture.chmod(0o644)
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(write,range(2)))
 assert sorted(results)==[0,1],results
 assert storage.usage()['used_bytes']<=1_000_000_000
 for p in created:p.unlink(missing_ok=True)
 # Recorder writes as the real unprivileged playout identity and receives actual MP3.
 import uuid
 key=uuid.uuid4().hex;record=Path('/srv/freo-upgrade-media/acceptance/recordings')/(key+'.mp3');created.append(record)
 audio=subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=1000:duration=10','-c:a','libmp3lame','-b:a','192k','-f','mp3','pipe:1'],check=True,capture_output=True).stdout
 result=subprocess.run(['runuser','-u','freo-playout','--','/opt/freo/current/venv/bin/python','/opt/freo/current/scripts/hosting-recording.py','acceptance',key],input=audio,capture_output=True)
 assert result.returncode==0,(result.returncode,result.stderr.decode())
 assert 0<record.stat().st_size<=100_000,record.stat().st_size
 assert (Path('/run/freo/playout/acceptance')/('recording-'+key+'.error')).read_text()=='storage_limit_exceeded'
 subprocess.run(['ffmpeg','-v','error','-i',str(record),'-f','null','-'],check=True,capture_output=True)
 assert storage.usage()['used_bytes']<=1_000_000_000
 # Reduced quota may be below usage; cleanup remains possible and audio continues.
 with fixture.open('r+b') as output:output.truncate(1_000_000_001)
 assert storage.usage()['over_quota']
 assert write(2)!=0
 from urllib.request import urlopen
 with urlopen('http://127.0.0.1:8001/acceptance',timeout=5) as response:assert response.read(8192)
 report=dict(concurrent_writers=results,recording_exit=result.returncode,recording_bytes=record.stat().st_size,partial_recording_decodes=True,over_quota_blocks_growth=True,broadcast_continues=True)
 (E/'storage-results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
finally:
 fixture.unlink(missing_ok=True)
 for path in created:path.unlink(missing_ok=True)
