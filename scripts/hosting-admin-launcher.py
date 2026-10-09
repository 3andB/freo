#!/usr/bin/python3 -I
"""Stable dispatcher: older restored application code cannot disable authority."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from freo_ops import hosting


def main():
    if os.geteuid()!=0:
        print(json.dumps(dict(schema_version=1,success=False,error='unauthorized',message='Root authorization is required.')))
        return 3
    source=Path('/opt/freo/current') if Path('/opt/freo/current').is_dir() else Path('/opt/freo')
    if not (source/'scripts/hosting-admin.py').is_file() or not (source/'app/services/hosting_web.py').is_file():
        try:state=hosting.read()
        except hosting.HostingError:state={'restricted':True}
        if sys.argv[1:]==['hosting','status']:
            print(json.dumps(dict(schema_version=1,success=True,state=state,inhibited=(hosting.STATE/'inhibit').exists(),compatible_release=False)))
            return 0
        print(json.dumps(dict(schema_version=1,success=False,error='incompatible_release',message='Restore a hosted-capable Freo release before managing this installation.',state=state)))
        return 6
    if sys.argv[1:2] != ['hosting'] and not (source/'freo_ops/admin.py').is_file():
        runtime=Path('/var/lib/freo-admin/runtime')
        if runtime.is_symlink() and (runtime.resolve()/'freo_ops/admin.py').is_file():
            source=runtime.resolve()
        else:
            print(json.dumps(dict(schema_version=1,success=False,error='incompatible_release',state=hosting.read())))
            return 6
    os.chdir(source)
    os.environ['PATH']='/usr/sbin:/usr/bin:/sbin:/bin'
    executable=str(source/'venv/bin/python')
    os.execv(executable,[executable,'-I',str(source/'scripts/hosting-admin.py'),*sys.argv[1:]])

if __name__=='__main__':
    raise SystemExit(main())
