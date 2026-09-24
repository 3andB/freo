#!/usr/bin/env bash
# Disposable local cluster. Never sources .env or connects to the installed DB.
set -euo pipefail
cd "$(dirname "$0")/.."
pg_bin=$(pg_config --bindir)
cluster=$(mktemp -d /tmp/freo-recovery-pg.XXXXXX)
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
"${run_pg[@]}" "$pg_bin/pg_ctl" -D "$cluster/data" -l "$cluster/server.log" -o "-k $cluster -h '' -F" -w start >/dev/null
FREO_ENV_FILE=/dev/null FREO_TEST_POSTGRES_URL="postgresql://recovery_test@/postgres?host=$cluster" \
  venv/bin/pytest -q tests/test_recovery.py tests/test_installation_settings_postgres.py tests/test_primary_admin_migration.py tests/test_station_location_migration.py "$@"
