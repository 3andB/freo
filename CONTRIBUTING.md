# Contributing

Freo has a production installation with real users. Use Python 3.12, create a local venv, install `requirements-dev.txt`, and run `pytest` before proposing a change. Keep credentials, media, database dumps, and server-specific configuration out of commits. Changes to migrations, installation, service privileges, and public routes need explicit review and a fresh-VM validation plan. Contributions are distributed under the bundled Freo Source-Available License; retain its notices and payment requirements.

## Stable and next-version development

`main` is the stable V1 release line following promotion of the accepted RC17 source. Create fixes on `fix/*` branches from main and validate before merging. Future major development uses a separate development branch. The October 2026 0.3.2 freeze is a historical recovery baseline; its tags and artifacts remain immutable.

Use a separate development checkout and isolated configuration, database,
storage, and service ports. Never run development or tests against production
credentials or data. Keep `/opt/freo` on main and preserve ignored runtime files.
Production release tags are immutable; fixes need new patch versions and tags.
Pushing source changes does not authorize a production deployment.

See the [verified 0.3.2 production baseline](docs/production-baseline-2026-10-04.md)
for exact source, schema, configuration fingerprints, artifacts, and recovery
references.

## Validation

For recovery/settings/release changes, run `bash scripts/test-recovery-postgres.sh`
and the suites in `.github/workflows/recovery.yml`. The script starts its own
temporary PostgreSQL cluster and never reads the installed `.env`. Never point
test database variables at a production database. Released migration files must
remain immutable; add a new migration and preservation fixture for schema changes.
See `docs/recovery-and-upgrades.md` for supported-source and release requirements.
