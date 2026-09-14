#!/usr/bin/env python3
"""Reject malformed systemd instance names before Liquidsoap reads a path."""
import re
import sys
from pathlib import Path

PATTERN = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$')
RESERVED = {'admin', 'status', 'server_version', 'freo-test'}


def valid_instance(value):
    return bool(PATTERN.fullmatch(value)) and value not in RESERVED


if __name__ == '__main__':
    if len(sys.argv) != 2 or not valid_instance(sys.argv[1]):
        raise SystemExit('Invalid station instance')
    config = Path('/etc/freo/radio/stations') / (sys.argv[1] + '.liq')
    if not config.is_file():
        raise SystemExit('Station config is missing')
