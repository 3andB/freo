import json,os,time
from pathlib import Path
def pytest_runtest_logreport(report):
    if report.when == 'call' or report.outcome != 'passed':
        p=Path(os.environ['CAMPAIGN_CASES'])
        with p.open('a') as f:
            f.write(json.dumps(dict(at=time.time(),node=report.nodeid,when=report.when,
                outcome=report.outcome,duration=report.duration,
                detail=str(report.longrepr)[:6000] if report.outcome != 'passed' else ''))+'\n')
