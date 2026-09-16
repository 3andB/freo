#!/usr/bin/env bash
set -euo pipefail

install_dir=${FREO_INSTALL_DIR:-/opt/freo}
test -x "$install_dir/venv/bin/python"
"$install_dir/venv/bin/python" -c 'from zoneinfo import ZoneInfo; ZoneInfo("UTC"); ZoneInfo("America/Denver"); import app.services.schedule, app.services.clocks' >/dev/null
"$install_dir/venv/bin/python" -c 'import app.services.admin_media, app.ingest_worker' >/dev/null
test -x /usr/bin/ffprobe
test -d /var/lib/freo/media
test -d /var/lib/freo/uploads
test -d /var/lib/freo/playlists
if [[ $(stat -c %a /var/lib/freo/media) != 751 || $(stat -c %a /var/lib/freo/playlists) != 750 ]]; then
  echo 'Media or playlist root permissions are too broad.' >&2
  exit 1
fi
test -f "$install_dir/.env"
test -f /etc/systemd/system/freo-playout@.service
test -f /etc/systemd/system/freo-automation.service
test -f /etc/systemd/system/freo-ingest.service
test -f /etc/systemd/system/freo-public-schedules.service
systemctl is-active --quiet freo-public-schedules.timer
id freo-automation >/dev/null
id freo-ingest >/dev/null
if id -nG freo-ingest | tr ' ' '\n' | grep -qx freo-playout; then
  echo 'Ingest worker must not belong to the Liquidsoap control group.' >&2
  exit 1
fi
test -x "$install_dir/scripts/validate-station-instance.py"
test "$(stat -c %a "$install_dir/.env")" = 640
systemctl is-active --quiet postgresql nginx freo.service icecast2.service freo-automation.service freo-ingest.service
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
for attempt in {1..10}; do
  if curl --fail --silent --max-time 3 http://127.0.0.1:8000/health/automation >/dev/null; then
    break
  fi
  if (( attempt == 10 )); then
    echo 'Automation worker heartbeat is not current.' >&2
    exit 1
  fi
  sleep 2
done
curl --fail --silent --show-error http://127.0.0.1:8000/api/stations >/dev/null
curl --fail --silent --show-error http://127.0.0.1:8000/health/icecast >/dev/null
systemctl is-active --quiet freo-provision.timer
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 ]]; then
for endpoint in icecast playout stream; do
  curl --fail --silent --show-error "http://127.0.0.1:8000/health/$endpoint" >/dev/null
done
test -S /run/freo/liquidsoap/control.sock
if [[ $(stat -c %a /run/freo/liquidsoap/control.sock) != 600 ]]; then
  echo 'Liquidsoap control socket is not private.' >&2
  exit 1
fi
fi
for station_socket in /run/freo/playout/*/control.sock; do
  if [[ -S $station_socket && $(stat -c %a "$station_socket") != 660 ]]; then
    echo 'Managed station control socket is not restricted to its group.' >&2
    exit 1
  fi
done
ss -ltn | grep -q '127.0.0.1:8000 '
ss -ltn | grep -q '127.0.0.1:8001 '
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 ]]; then
python3 - <<'PY'
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8001/freo-test', timeout=5) as response:
    if response.status != 200 or response.headers.get_content_type() != 'audio/mpeg' or not any(response.read(4096)):
        raise SystemExit('Icecast mount is not delivering audio.')
PY
fi
if [[ $(systemctl show freo.service -p User --value) != freo ]]; then
  echo 'freo.service is not configured for user freo' >&2
  exit 1
fi
if [[ $(systemctl show freo-automation.service -p User --value) != freo-automation ]]; then
  echo 'Automation worker is not configured for freo-automation.' >&2
  exit 1
fi
if [[ $(systemctl show freo-ingest.service -p User --value) != freo-ingest ]]; then
  echo 'Media ingest worker is not configured for freo-ingest.' >&2
  exit 1
fi
if [[ $(stat -c %U:%G:%a /var/lib/freo/uploads) != freo:freo-ingest:2770 ]]; then
  echo 'Web upload staging permissions are not restricted.' >&2
  exit 1
fi
printf 'Freo validation passed: web, database, scheduling imports, radio services, private listeners, health, and MP3 bytes.\n'
