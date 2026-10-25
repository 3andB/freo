"""Run the production Gunicorn arguments against bounded slow requests."""
import concurrent.futures
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def test_production_web_keeps_health_available_while_two_requests_wait(tmp_path):
    unit=Path(__file__).resolve().parents[1]/'deploy/systemd/freo.service'
    command=shlex.split(next(line.split('=',1)[1] for line in unit.read_text().splitlines() if line.startswith('ExecStart=')))
    with socket.socket() as available:
        available.bind(('127.0.0.1',0));port=available.getsockname()[1]
    command=[sys.executable,'-m','gunicorn',*command[1:]]
    command[command.index('--bind')+1]='127.0.0.1:'+str(port)
    command[-1]='probe:app'
    (tmp_path/'probe.py').write_text('''import time\nfrom pathlib import Path\ndef app(environ,start_response):\n path=environ['PATH_INFO']\n if path.startswith('/hold/'):\n  Path(path.rsplit('/',1)[1]+'.entered').touch()\n  time.sleep(6)\n start_response('200 OK',[('Content-Type','text/plain')])\n return [b'ok']\n''')
    env=dict(os.environ);env.pop('GUNICORN_CMD_ARGS',None)
    base='http://127.0.0.1:'+str(port)
    with (tmp_path/'gunicorn.log').open('w') as log:
        process=subprocess.Popen(command,cwd=tmp_path,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+20
            while True:
                try:
                    with urlopen(base+'/health',timeout=1) as response:assert response.read()==b'ok'
                    break
                except OSError:
                    assert process.poll() is None,(tmp_path/'gunicorn.log').read_text()
                    assert time.monotonic()<deadline
                    time.sleep(.05)
            def hold(name):
                with urlopen(base+'/hold/'+name,timeout=15) as response:return response.status
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                pending=[pool.submit(hold,name) for name in ['first','second']]
                deadline=time.monotonic()+10
                while not all((tmp_path/(name+'.entered')).exists() for name in ['first','second']):
                    assert time.monotonic()<deadline
                    time.sleep(.01)
                began=time.monotonic()
                with urlopen(base+'/health',timeout=2) as response:assert response.read()==b'ok'
                assert time.monotonic()-began<2
                assert [future.result() for future in pending]==[200,200]
        finally:
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
