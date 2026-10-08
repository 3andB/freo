#!/usr/bin/env python3
"""Isolated interpreter entrypoint for the approved local hosting commands."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from freo_ops.hosting_admin import main
raise SystemExit(main())
