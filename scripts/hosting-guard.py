#!/usr/bin/env python3
"""Service startup guard. Fixed paths, no environment/customer override."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from freo_ops.hosting import require_service, HostingError
try:
    if '--web' in sys.argv:
        from freo_ops.hosting import read, STATE
        policy=read()
        source=Path('/opt/freo/current') if Path('/opt/freo/current').is_dir() else Path('/opt/freo')
        if policy['hosted'] and not (source/'app/services/hosting_web.py').is_file():
            raise HostingError('incompatible_release','Hosted enforcement is absent.')
    else:
        require_service()
except HostingError:
    print('Freo broadcasting is restricted by the server hosting policy.', file=sys.stderr)
    raise SystemExit(1)
