#!/usr/bin/env bash
set -euo pipefail

install_dir=${FREO_INSTALL_DIR:-/opt/freo}
test -x "$install_dir/venv/bin/python"
test -f "$install_dir/.env"
test "$(stat -c %a "$install_dir/.env")" = 640
systemctl is-active --quiet postgresql nginx freo.service icecast2.service freo-playout.service
nginx -t >/dev/null
pg_isready -q
current=$(cd "$install_dir" && runuser -u freo -- env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/flask" --app wsgi:app db current)
heads=$(cd "$install_dir" && runuser -u freo -- env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/flask" --app wsgi:app db heads)
if [[ $current != "$heads" ]]; then
  echo 'Database migrations are not current.' >&2
  exit 1
fi
curl --fail --silent --show-error http://127.0.0.1:8000/health >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8000/ready >/dev/null
for endpoint in icecast playout stream; do
  curl --fail --silent --show-error "http://127.0.0.1:8000/health/$endpoint" >/dev/null
done
test -S /run/freo/liquidsoap/control.sock
if [[ $(stat -c %a /run/freo/liquidsoap/control.sock) != 600 ]]; then
  echo 'Liquidsoap control socket is not private.' >&2
  exit 1
fi
ss -ltn | grep -q '127.0.0.1:8000 '
ss -ltn | grep -q '127.0.0.1:8001 '
python3 - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/freo-test', timeout=5) as response:
    if response.status != 200 or response.headers.get_content_type() != 'audio/mpeg' or not any(response.read(4096)):
        raise SystemExit('Icecast mount is not delivering audio.')
PY
if [[ $(systemctl show freo.service -p User --value) != freo ]]; then
  echo 'freo.service is not configured for user freo' >&2
  exit 1
fi
printf 'Freo validation passed: web, database, radio services, private listeners, health, and MP3 bytes.\n'
