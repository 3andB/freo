#!/usr/bin/env python3
"""Service startup guard. Fixed paths, no environment/customer override."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from freo_ops.hosting import require_service, HostingError
try:
    require_service()
except HostingError:
    print('Freo broadcasting is restricted by the server hosting policy.', file=sys.stderr)
    raise SystemExit(1)
