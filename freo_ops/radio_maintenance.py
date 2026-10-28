"""Stage and validate existing managed station engines during an explicit upgrade.

Only the station template may change. Credentials, proxy configuration, hosting
policy and station activation are retained by the normal backed-up updater.
"""
import json
import os
from pathlib import Path

from . import recovery

TEMPLATE = 'deploy/liquidsoap/station.liq.template'


def stage(release, env):
    """Render all existing engines, and validate as the broadcasting account.

    Run after writers stop and the matched backup is restored, before migration
    or activation. Temporary files share the destination's accessible directory;
    private output and compiler diagnostics never reach the public CLI.
    """
    program = r'''
import json
from pathlib import Path
from app import create_app
from app.models import Station
from app.services.station_runtime import CONFIGS, SECRETS, atomic_install, render_liquidsoap, run_checked
from app.services.stations import validate_slug
from freo_ops.recovery import digest
app=create_app()
pending={}
try:
    with app.app_context():
        known=set()
        for station in Station.query.filter_by(deleted_at=None).order_by(Station.id):
            slug=validate_slug(station.slug)
            path=CONFIGS/(slug+'.liq')
            if not path.exists():
                continue
            known.add(path)
            secret=SECRETS/(slug+'.json')
            if path.is_symlink() or secret.is_symlink() or not station.stream:
                raise RuntimeError('Station runtime requires manual review: '+slug)
            before=digest(path)
            body=render_liquidsoap(station,json.loads(secret.read_text())['source'])
            temporary=atomic_install(path,body,0o640,'root','freo-playout')
            pending[str(path)]={'temporary':str(temporary),'before_sha256':before}
            run_checked(['/usr/sbin/runuser','-u','freo-playout','--','/usr/bin/liquidsoap','--check',str(temporary)])
        if set(CONFIGS.glob('*.liq')) != known:
            raise RuntimeError('Unmanaged station runtime requires manual review')
    print(json.dumps(pending))
except BaseException:
    for row in pending.values():
        Path(row['temporary']).unlink(missing_ok=True)
    raise
'''
    output = recovery.run([str(release / 'venv/bin/python'), '-c', program], cwd=release, env=env)
    return json.loads(output)


def discard(changes):
    for row in changes.values():
        Path(row['temporary']).unlink(missing_ok=True)


def apply(changes):
    # Check every source before replacing any; all writers remain guarded.
    for name, row in changes.items():
        path = Path(name)
        if path.is_symlink() or recovery.digest(path) != row['before_sha256']:
            raise recovery.RecoveryError('Station runtime changed during maintenance')
    for name, row in changes.items():
        path = Path(name)
        temporary = Path(row['temporary'])
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
