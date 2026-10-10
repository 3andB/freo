#!/usr/bin/env python3
"""Internal fixed recovery reconciliation; never a remote execution interface."""
import os
from pathlib import Path
import re
import sys


def recording_configuration(existing, rendered):
    """Replace only the managed recording sink; preserve all other audio settings."""
    end='\nserver.register(namespace="freo_show", "state"'
    def block(text):
        start=text.index('record_output = output.')
        return start,text.index(end,start),text[start:text.index(end,start)]
    def normalized(text):
        lines=text.splitlines()
        if not re.fullmatch(r'  %mp3\(bitrate=192\), \{.*\}, record_source\)',lines[-1]):
            raise ValueError('Customized recording encoder requires administrator review')
        lines[-1]='MANAGED_RECORDING_DESTINATION'
        return '\n'.join(lines).replace('output.file(', 'output.external(').replace('  perm=0o640, dir_perm=0o750,\n','')
    start,stop,old=block(existing)
    _,_,new=block(rendered)
    if normalized(old)!=normalized(new):
        raise ValueError('Customized recording configuration requires administrator review')
    return existing[:start]+new+existing[stop:]


def main():
    if os.geteuid()!=0 or sys.argv[1:]!=['storage']:
        raise SystemExit(3)
    source=Path('/opt/freo/current').resolve() if Path('/opt/freo/current').is_symlink() else Path('/opt/freo')
    sys.path.insert(0,str(source))
    from dotenv import dotenv_values
    for name in list(os.environ):
        if name.startswith(('FREO_','FLASK_','PG','PYTHON')) or name in ('DATABASE_URL','SECRET_KEY'):
            os.environ.pop(name,None)
    path=Path('/etc/freo/freo.env')
    if not path.exists():path=Path('/opt/freo/.env')
    os.environ.update({k:v for k,v in dotenv_values(path,interpolate=False).items() if v is not None})
    os.environ.update(FREO_ENV_FILE=str(path),FLASK_ENV='production',PATH='/usr/sbin:/usr/bin:/sbin:/bin')
    from app import create_app
    from freo_ops.hosting_admin import provision_storage,radio_policy
    from freo_ops.hosting import read
    from app.models import Station
    from app.services import station_runtime as runtime
    with create_app().app_context():
        policy=read()
        if policy['hosted']:provision_storage()
        radio_policy(policy)
        for station in Station.query.filter_by(deleted_at=None,enabled=True).all():
            if not station.stream or not station.stream.enabled:continue
            password=runtime.credential(station.slug)
            target=runtime.CONFIGS/(station.slug+'.liq')
            # Pending stations are rendered by the existing provisioner on resume.
            if not target.exists():continue
            desired=recording_configuration(target.read_text(),runtime.render_liquidsoap(station,password))
            staged=runtime.atomic_install(target,desired,0o640,'root','freo-playout')
            try:
                runtime.run_checked(['/usr/sbin/runuser','-u','freo-playout','--','/usr/bin/liquidsoap','--check',str(staged)])
                runtime.install_staged(target,staged)
            finally:staged.unlink(missing_ok=True)


if __name__=='__main__':main()
