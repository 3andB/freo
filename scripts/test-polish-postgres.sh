#!/usr/bin/env bash
# Only creates a private /tmp cluster. Never reads installation credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
pg_bin="$(pg_config --bindir)"
polish_cluster="$(mktemp -d /tmp/freo-phase9-pg.XXXXXX)"
run_pg=()
if [[ $(id -u) == 0 ]]; then
    chown postgres:postgres "$polish_cluster"
    run_pg=(runuser -u postgres --)
fi
cleanup() {
    "${run_pg[@]}" "$pg_bin/pg_ctl" -D "$polish_cluster/data" -m immediate stop >/dev/null 2>&1 || true
    rm -rf -- "$polish_cluster"
}
trap cleanup EXIT
"${run_pg[@]}" "$pg_bin/initdb" -D "$polish_cluster/data" -A trust -U polish_test --no-locale >/dev/null
"${run_pg[@]}" "$pg_bin/pg_ctl" -D "$polish_cluster/data" -l "$polish_cluster/server.log" -o "-k $polish_cluster -h '' -F" -w start >/dev/null
PYTHONDONTWRITEBYTECODE=1 FREO_ENV_FILE=/dev/null FREO_TEST_POSTGRES_URL="postgresql://polish_test@/postgres?host=$polish_cluster" python -m pytest -q tests/test_platform_polish_postgres.py --basetemp=/tmp/freo-phase9-pg-tests "$@"
