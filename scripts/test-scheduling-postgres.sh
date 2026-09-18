#!/usr/bin/env bash
# Isolated cluster; never reads installation database credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
pg_bin="$(pg_config --bindir)"
cluster="$(mktemp -d /tmp/freo-scheduling-pg.XXXXXX)"
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
"${run_pg[@]}" "$pg_bin/initdb" -D "$cluster/data" -A trust -U schedule_test --no-locale >/dev/null
"${run_pg[@]}" "$pg_bin/pg_ctl" -D "$cluster/data" -l "$cluster/server.log" -o "-k $cluster -h '' -F" -w start >/dev/null
FREO_TEST_POSTGRES_URL="postgresql://schedule_test@/postgres?host=$cluster" venv/bin/pytest -q tests/test_schedule_postgres.py "$@"
