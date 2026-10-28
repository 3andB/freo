#!/usr/bin/env python3
"""Fixed entrypoint for the hosted recording subprocess."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from freo_ops.hosting_recording import main
raise SystemExit(main())
