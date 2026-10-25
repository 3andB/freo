"""Cold-process admission checks; no database connection or real service needed."""
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def run_startup(body):
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,FREO_ENV_FILE='/dev/null',FLASK_ENV='testing',
             DATABASE_URL='sqlite://',PYTHONPATH=str(root))
    result=subprocess.run([sys.executable,'-c',textwrap.dedent(body)],cwd=root,
                          env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    return json.loads(result.stdout.splitlines()[-1])


def test_wsgi_admits_requests_with_readonly_metadata_and_timezone_caches_ready():
    result=run_startup('''
        import concurrent.futures,json,threading,time
        from sqlalchemy.engine import Engine
        from app.services import schedule,timezones
        def database_forbidden(*args,**kwargs):
            raise AssertionError('Worker metadata warmup must not connect to a database')
        Engine.connect=database_forbidden
        lock=threading.Lock();calls=[]
        def cold_timezone_scan():
            with lock:calls.append(threading.get_ident())
            time.sleep(.2)
            return {'UTC','America/New_York'}
        schedule.available_timezones=cold_timezone_scan
        timezones.available_timezones=cold_timezone_scan
        import wsgi
        from app.extensions import db
        at_admission=len(calls)
        mapper_ready=all(m.configured for m in db.Model.registry.mappers)
        barrier=threading.Barrier(24)
        def request(index):
            barrier.wait(timeout=10)
            assert schedule.validate_timezone('UTC')=='UTC'
            assert schedule.validate_timezone('America/New_York')=='America/New_York'
            assert timezones.choices()[0][0]=='UTC'
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            list(pool.map(request,range(24)))
        print(json.dumps(dict(at_admission=at_admission,after_requests=len(calls),
                              mapper_ready=mapper_ready,requests=24)))
    ''')
    assert result==dict(at_admission=2,after_requests=2,mapper_ready=True,requests=24),result


def test_wsgi_refuses_to_admit_requests_when_timezone_metadata_cannot_load():
    result=run_startup('''
        import json
        from app.services import schedule
        def unavailable():
            raise OSError('Injected timezone metadata read failure')
        schedule.available_timezones=unavailable
        try:
            import wsgi
        except OSError as error:
            assert str(error)=='Injected timezone metadata read failure'
            print(json.dumps(dict(startup_refused=True)))
        else:
            print(json.dumps(dict(startup_refused=False)))
    ''')
    assert result==dict(startup_refused=True)
