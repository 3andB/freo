#!/usr/bin/env bash
set -euo pipefail

install_dir=${FREO_INSTALL_DIR:-/opt/freo}
# Resolve the active release after an upgrade as well as the fresh layout.
if [[ -d "$install_dir/current" ]]; then install_dir="$install_dir/current"; fi
cd "$install_dir"
export FREO_ENV_FILE="$install_dir/.env"
# Policy errors must fail verification, never be interpreted as self-hosted.
restricted=$("$install_dir/venv/bin/python" - <<'PYTHON'
from freo_ops import hosting
state = hosting.read()
if state.get('restricted'):
    raise SystemExit('Invalid authoritative hosting policy')
print(int(state['hosted'] and (state['status'] in ('suspended', 'maintenance') or (hosting.STATE / 'inhibit').exists())))
PYTHON
)
test -x "$install_dir/venv/bin/python"
(cd "$install_dir" && "$install_dir/venv/bin/python" -m pip check && "$install_dir/venv/bin/python" -m freo_ops.dependencies)
"$install_dir/venv/bin/python" -c 'from zoneinfo import ZoneInfo; ZoneInfo("UTC"); ZoneInfo("America/Denver"); import app.services.schedule, app.services.clocks' >/dev/null
"$install_dir/venv/bin/python" -c 'import app.services.admin_media, app.ingest_worker, app.production_worker' >/dev/null
test -x /usr/bin/ffprobe
test -d /var/lib/freo/media
test -d /var/lib/freo/uploads
test "$(stat -c %a:%U:%G /var/lib/freo/uploads/production)" = 2770:freo:freo
test -d /var/lib/freo/playlists
if [[ $(stat -c %a /var/lib/freo/media) != 751 || $(stat -c %a /var/lib/freo/playlists) != 750 ]]; then
  echo 'Media or playlist root permissions are too broad.' >&2
  exit 1
fi
test -f "$install_dir/.env"
test -f /etc/systemd/system/freo-playout@.service
test -f /etc/systemd/system/freo-automation.service
test -f /etc/systemd/system/freo-ingest.service
test -f /etc/systemd/system/freo-production.service
test -f /etc/systemd/system/freo-mic.service
test -f "$install_dir/scripts/recording-storage.py"
test -f /etc/systemd/system/freo-public-schedules.service
systemctl is-active --quiet freo-public-schedules.timer
id freo-automation >/dev/null
id freo-ingest >/dev/null
id freo-stats >/dev/null
systemctl is-active --quiet freo-stats.service freo-stats-inventory.timer freo-geoip.timer
if id -nG freo-stats | tr ' ' '\n' | grep -qx freo-playout; then
  echo 'Statistics worker must not belong to the Liquidsoap control group.' >&2
  exit 1
fi
if id -nG freo-ingest | tr ' ' '\n' | grep -qx freo-playout; then
  echo 'Ingest worker must not belong to the Liquidsoap control group.' >&2
  exit 1
fi
test -x "$install_dir/scripts/validate-station-instance.py"
test "$(stat -c %a "$install_dir/.env")" = 640
systemctl is-active --quiet postgresql nginx freo.service freo-automation.service freo-ingest.service freo-production.service
if [[ $restricted == 0 ]]; then systemctl is-active --quiet icecast2.service; fi
# Read the persisted choice; re-running validation need not export installer flags.
if grep -qx 'FREO_LIVE_MIC=1' "$install_dir/.env"; then
  (cd "$install_dir" && "$install_dir/venv/bin/python" -m freo_ops.dependencies --live-mic)
  if [[ $restricted == 0 ]]; then systemctl is-active --quiet freo-mic.service; fi
fi
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
if [[ $restricted == 0 ]]; then
curl --fail --silent --show-error http://127.0.0.1:8000/health/icecast >/dev/null
python3 - <<'PY'
import json
from urllib.request import build_opener, ProxyHandler
with build_opener(ProxyHandler({})).open('http://127.0.0.1:8001/status-json.xsl', timeout=3) as response:
    version = json.load(response).get('icestats', {}).get('server_id', '')
if not version.startswith('Icecast 2.5.'):
    raise SystemExit('The running Icecast service must use the supported 2.5 series.')
PY
fi
systemctl is-active --quiet freo-provision.timer
for station_config in /etc/freo/radio/stations/*.liq; do
  if [[ -f $station_config ]]; then
    if ! runuser -u freo-playout -- test -r "$station_config"; then
      echo 'A station configuration is not readable by the playout service.' >&2
      exit 1
    fi
  fi
done
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 && $restricted == 0 ]]; then
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
if [[ $restricted == 0 ]]; then ss -ltn | grep -q '127.0.0.1:8001 '; fi
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 && $restricted == 0 ]]; then
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
(cd "$install_dir" && env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/python" "$install_dir/scripts/validate-admin-login.py" --external)
# Enabled units and timers survive boot; station instances are reconciled by
# freo-provision.timer from their persisted desired state.
for unit in postgresql nginx freo.service icecast2.service freo-automation.service freo-ingest.service freo-production.service freo-central-api.service freo-stats.service freo-provision.timer freo-public-schedules.timer freo-updater.timer freo-stats-inventory.timer freo-geoip.timer; do
  systemctl is-enabled --quiet "$unit"
done
if grep -qx 'FREO_LIVE_MIC=1' "$install_dir/.env"; then systemctl is-enabled --quiet freo-mic.service; fi
freo-admin health
freo-admin hosting verify
printf 'Freo installation verification passed. Station creation and first-use password replacement require the explicit fresh acceptance test.\n'
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 && $restricted == 0 ]]; then
  printf 'Diagnostic MP3 stream bytes also verified.\n'
fi
