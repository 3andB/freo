#!/usr/bin/env bash
# Creates and removes only a private /tmp PostgreSQL cluster; no installation DB.
set -euo pipefail
cd "$(dirname "$0")/.."
pg_bin="$(pg_config --bindir)"
production_cluster="$(mktemp -d /tmp/freo-phase8-pg.XXXXXX)"
run_pg=()
if [[ $(id -u) == 0 ]]; then
    chown postgres:postgres "$production_cluster"
    run_pg=(runuser -u postgres --)
fi
cleanup() {
    "${run_pg[@]}" "$pg_bin/pg_ctl" -D "$production_cluster/data" -m immediate stop >/dev/null 2>&1 || true
    rm -rf -- "$production_cluster"
}
trap cleanup EXIT
"${run_pg[@]}" "$pg_bin/initdb" -D "$production_cluster/data" -A trust -U production_test --no-locale >/dev/null
"${run_pg[@]}" "$pg_bin/pg_ctl" -D "$production_cluster/data" -l "$production_cluster/server.log" -o "-k $production_cluster -h '' -F" -w start >/dev/null
PYTHONDONTWRITEBYTECODE=1 FREO_ENV_FILE=/dev/null FREO_TEST_POSTGRES_URL="postgresql://production_test@/postgres?host=$production_cluster" python -m pytest -q tests/test_production_postgres.py --basetemp=/tmp/freo-phase8-pg-tests "$@"
