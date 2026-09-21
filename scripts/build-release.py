#!/usr/bin/env python3
"""Build from the tagged clean checkout; no host credentials or media are included."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from freo_ops.releases import build
from freo_ops.recovery import RecoveryError

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
parser.add_argument('--wheelhouse')
parser.add_argument('--development', action='store_true', help='Uninstallable source-only review artifact; may use a dirty/unlicensed checkout')
args = parser.parse_args()
try:
    print(json.dumps(build(Path(__file__).resolve().parents[1], args.output,
                           development=args.development, wheelhouse=args.wheelhouse), indent=2))
except RecoveryError as error:
    parser.exit(1, str(error) + '\n')
