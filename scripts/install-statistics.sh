#!/usr/bin/env bash
# Run after dependencies and database migrations; never restarts playout.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
source_dir=${1:-/opt/freo}
if ! id freo-stats >/dev/null 2>&1; then
  useradd --system --user-group --groups freo --home-dir /var/lib/freo/statistics --shell /usr/sbin/nologin freo-stats
fi
install -d -o freo-stats -g freo -m 0700 /var/lib/freo/statistics
install -d -o freo-stats -g freo -m 0750 /var/lib/freo/geoip
python3 - <<'PY'
import json, os
from pathlib import Path
source = json.loads(Path('/etc/freo/secrets/engine.json').read_text())
target = Path('/etc/freo/secrets/statistics.json')
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as output:
    json.dump({'admin': source['admin']}, output)
target.chmod(0o600)
PY
for unit in freo-stats.service freo-stats-inventory.service freo-stats-inventory.timer freo-geoip.service freo-geoip.timer; do
  install -m 0644 "$source_dir/deploy/systemd/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now freo-stats.service freo-stats-inventory.timer freo-geoip.timer
systemctl restart freo-stats.service
systemctl start freo-stats-inventory.service
if [[ ! -s /var/lib/freo/geoip/City.mmdb ]]; then
  systemctl start --no-block freo-geoip.service
fi
