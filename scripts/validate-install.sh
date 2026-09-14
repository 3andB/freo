#!/usr/bin/env bash
set -euo pipefail

install_dir=${FREO_INSTALL_DIR:-/opt/freo}
test -x "$install_dir/venv/bin/python"
test -f "$install_dir/.env"
test "$(stat -c %a "$install_dir/.env")" = 640
systemctl is-active --quiet postgresql nginx freo.service
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
if [[ $(systemctl show freo.service -p User --value) != freo ]]; then
  echo 'freo.service is not configured for user freo' >&2
  exit 1
fi
printf 'Freo validation passed: Python, database, services, Nginx, /health and /ready.\n'
