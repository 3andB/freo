#!/usr/bin/env bash
set -euo pipefail

if (( EUID != 0 )); then
  echo 'Run as root: sudo ./scripts/install.sh' >&2
  exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ! -f "$source_dir/wsgi.py" ]]; then
  echo 'Run the installer from a complete Freo checkout.' >&2
  exit 1
fi
echo 'Installing Freo web, radio engine, station runtime, and scheduling support.'
exec "$source_dir/scripts/provision.sh" "$source_dir"
