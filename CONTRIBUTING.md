# Contributing

Freo is an early-stage public project. Use Python 3.12, create a local venv, install `requirements-dev.txt`, and run `pytest` before proposing a change. Keep credentials, media, database dumps, and server-specific configuration out of commits. Changes to migrations, installation, service privileges, and public routes need explicit review and a fresh-VM validation plan. The project license is not yet selected; confirm contribution terms with the owner before substantial contributions.

For recovery/settings/release changes, run `bash scripts/test-recovery-postgres.sh`
and the suites in `.github/workflows/recovery.yml`. The script starts its own
temporary PostgreSQL cluster and never reads the installed `.env`. Never point
test database variables at a production database. Released migration files must
remain immutable; add a new migration and preservation fixture for schema changes.
See `docs/recovery-and-upgrades.md` for supported-source and release requirements.
