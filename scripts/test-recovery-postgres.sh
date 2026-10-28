#!/usr/bin/env bash
# Disposable local cluster. Never sources .env or connects to the installed DB.
set -euo pipefail
cd "$(dirname "$0")/.."
pg_bin=$(pg_config --bindir)
cluster=$(mktemp -d /tmp/freo-recovery-pg.XXXXXX)
test_pg_port=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
run_pg=()
if [[ $(id -u) == 0 ]]; then
  chown postgres:postgres "$cluster"
  run_pg=(runuser -u postgres --)
fi
cleanup() {
  "${run_pg[@]}" "$pg_bin/pg_ctl" -D "$cluster/data" -m immediate stop >/dev/null 2>&1 || true
  rm -rf -- "$cluster"
}
trap cleanup EXIT
"${run_pg[@]}" "$pg_bin/initdb" -D "$cluster/data" -A trust -U recovery_test --no-locale >/dev/null
"${run_pg[@]}" "$pg_bin/pg_ctl" -D "$cluster/data" -l "$cluster/server.log" -o "-k $cluster -h 127.0.0.1 -p $test_pg_port -F" -w start >/dev/null
FREO_ENV_FILE=/dev/null FREO_TEST_POSTGRES_URL="postgresql://recovery_test@127.0.0.1:$test_pg_port/postgres" \
  venv/bin/pytest -q tests/test_recovery.py tests/test_installation_settings_postgres.py tests/test_primary_admin_migration.py tests/test_station_location_migration.py tests/test_login_session_migration.py "$@"
