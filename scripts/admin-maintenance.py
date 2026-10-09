#!/usr/bin/env python3
"""Internal fixed operation used after verified recovery; not a remote interface."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.geteuid()!=0 or sys.argv[1:]!=['storage']:
    raise SystemExit(3)
from dotenv import dotenv_values
for key in list(os.environ):
    if key.startswith(('FREO_','FLASK_','PG','PYTHON')) or key in ('DATABASE_URL','SECRET_KEY'):
        os.environ.pop(key,None)
path=Path('/etc/freo/freo.env')
if not path.exists():path=Path('/opt/freo/.env')
os.environ.update({k:v for k,v in dotenv_values(path,interpolate=False).items() if v is not None})
os.environ.update(FREO_ENV_FILE=str(path),FLASK_ENV='production',PATH='/usr/sbin:/usr/bin:/sbin:/bin')
from app import create_app
from freo_ops.hosting_admin import provision_storage
with create_app().app_context():provision_storage()
