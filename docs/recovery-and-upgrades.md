# Recovery and upgrades

The management tools are implemented and tested with disposable PostgreSQL
databases, real encrypted bundles and signatures, plus simulated service failures.
The full Ubuntu/systemd installation and upgrade still require the independent
[VM acceptance test](clean-install-test.md) before public support or deployment.
This document describes the implemented commands, not the proposed interfaces in
the original [design plan](upgrade-and-distribution-plan.md).

**Permanent state and settings.** Station, music, scheduling, website and account
records remain in the existing PostgreSQL database. Music originals and imaging
remain in their configured media directories. The new `installation_settings`
record stores public URL/domain routing, domain verification targets, station
limits, upload limits and live microphone enablement. Credentials, connection
details, storage roots, infrastructure logging and secret-bearing ICE/TURN
configuration remain in protected host configuration. Existing per-station
settings retain their existing tables.

Apply migration `d02f9a41c830` only through a backed-up maintenance procedure.
After migration, use the release's Flask executable from its release directory:

```bash
flask --app wsgi:app settings import-environment
flask --app wsgi:app settings show
flask --app wsgi:app settings set FREO_MAX_STATIONS 6 --revision 1
```

The importer reads the effective legacy configuration once. A rerun retains
existing saved values. Updates require the current revision and create an audit
event. A changed environment default does not replace a saved setting. Secrets
such as `DATABASE_URL` are rejected by the settings API. Public URL/domain
changes also require corresponding proxy/DNS configuration; live-mic changes
require the installed gateway, station rendering and an affected-station restart.
The gateway's availability remains distinct from its saved enablement preference.

Production readiness requires the release's exact Alembic head and adopted
settings. Startup does not automatically migrate or import settings; bootstrap,
migration and diagnostic commands remain usable before adoption. Tests without
an adopted record retain their isolated fixture configuration. Infrastructure
configuration is deliberately not moved into ordinary database settings.

**Backup and restore.** Run these commands with the release's Python, from that
release's directory. They never initialize Flask or automatically load `.env`.
Supply configuration files explicitly. The initial legacy path is
`/opt/freo/.env`; after versioned adoption it is `/etc/freo/freo.env`.

```bash
python -m freo_ops inventory --env-file /opt/freo/.env
python -m freo_ops backup --env-file /opt/freo/.env --output /BACKUP_VOLUME/freo-before-upgrade.gpg
python -m freo_ops verify /BACKUP_VOLUME/freo-before-upgrade.gpg
python -m freo_ops restore /BACKUP_VOLUME/freo-before-upgrade.gpg --target-env-file /PRIVATE/verification.env --directory /RESTORE_VOLUME/freo-check
```

Uppercase paths are operator-supplied paths on appropriately sized storage.
Create their parent directories first. Interactive commands prompt privately for
the backup passphrase. For unattended use, `--passphrase-file /PRIVATE/key` reads
a regular file with mode `0600` or stricter; it rejects symlinks. Keep a separate
recoverable copy of the passphrase, outside the installation and backup bundle.
Do not put it in command arguments, Git or the installation's public settings.

The standalone backup command refuses while any Freo service/timer is active or
another database client remains connected. Arrange a maintenance window, record
active units and stop the web application, workers, timers, provisioning and
playout, including `freo-updater.timer` and any active updater, before running it.
Never stop an updater mid-migration just to take another backup; wait for its
operation to finish or follow interruption recovery. It does not stop services itself. The upgrade command
coordinates those actions automatically. Keep other administrators, cron tasks
and external database writers out of the maintenance window.

Backups include a complete custom-format PostgreSQL dump, configured permanent
roots, private environment/configuration, central identity, Nginx/TLS and
PostgreSQL configuration when present, plus installed Freo/managed Icecast units.
`--include /additional/permanent/path` adds a custom root to a standalone backup.
Custom roots referenced by media/API/statistics configuration are inventoried
automatically. Media and accepted pending-upload references must match the
captured files and their recorded checksums where available. Symlinks are
recorded without reading their targets; special files in durable roots cause a
refusal requiring inventory review.

File bytes, sizes, SHA-256 hashes, permission modes, numeric owner/group IDs,
timestamps and extended attributes/ACLs are recorded in an encrypted manifest.
Database row-value signatures and sequence values are also recorded. The tool
uses an exported PostgreSQL snapshot, then rechecks database and filesystem state
for concurrent changes before completing the backup. The encrypted output is
published without replacing an existing file and has mode `0600`.

`verify` means encrypted-bundle integrity only. `restore` actually restores into
a uniquely named `freo_restore_<id>` database and a new filesystem directory,
then compares database contents, sequences, migration revision and file hashes.
It never drops a database, runs `pg_restore --clean`, overwrites a restore
directory or rewrites the live application's connection. The verification
connection must be explicit and have permission to create a database. Use a
dedicated disposable PostgreSQL server for routine acceptance work.

Recovered files live in `root-0`, `root-1`, etc. inside the restore directory.
`restore-report.json` maps those roots to their original paths. Internal symlinks
are remapped within the recovered tree; external links are left unresolved in
the report instead of pointing into the current host. Resolve them deliberately
when attaching a replacement host. The restore does not boot workers, enroll a
central identity, contact the central API or start any stream.

By default restored files belong to the restoring account. The manifest retains
the original IDs; `--preserve-ownership` applies them only when those numeric
IDs are correct on the destination host. For a replacement server, recreate the
service accounts and map both ownership and ACL entries before activation.
PostgreSQL global roles are not recreated from a cluster-wide dump; restore uses
the explicit destination role and skips original owner/privilege assignments.
The original full database dump retains that metadata for reviewed recovery.
Restore explicitly uses the source database's character encoding, including
when the destination cluster has a different default. Older format-1 bundles
recover the encoding from their verified database dump.

The initial implementation makes full private temporary copies under the system
temporary directory. Budget several times the full dataset size for staging,
encryption, decrypt/verify and restore; use an encrypted, adequately sized
`TMPDIR` for sensitive/large installations. It has no incremental media backup
or automatic retention pruning. Copy completed encrypted bundles off-host and
test their restore regularly. Retained verification databases and directories
require deliberate cleanup; the tool never guesses which databases to delete.

**Release preparation and upgrade.** Public release bundles include complete
application resources, migrations, management tools and a wheelhouse with hashes
for every resolved Python dependency. Files excluded by Git are not collected;
the release builder also rejects private key/database material and symlinks in
source. A public build requires an owner-selected `LICENSE`, a clean checkout,
an exact `v<app/version.py>` tag, and Ubuntu 24.04 x86_64/Python 3.12.

The publisher signs the complete archive. Provision its public keyring through a
trusted channel and verify its fingerprint independently. Do not trust a new
key merely because it arrived beside a download. On a legacy installation that
lacks `freo_ops`, first verify the candidate signature with `gpgv`, extract the
trusted tools to a separate directory, and run them with the existing virtual
environment's Python from that directory. Never copy candidate code over the
active application to obtain an updater.

Begin from a matching installed code/schema pair. A checkout already replaced
in place with candidate code but still using the old schema is not a verified
previous release; the updater refuses that mismatch. Preserve/recover the old
release from its recorded commit or artifact before a managed upgrade.

```bash
python -m freo_ops upgrade /DOWNLOADS/freo-v0.2.0.tar.gz --signature /DOWNLOADS/freo-v0.2.0.tar.gz.asc --keyring /PRIVATE/publisher.gpg --env-file /opt/freo/.env --backup /BACKUP_VOLUME/pre-0.2.0.gpg --verification-env-file /PRIVATE/verification.env --verification-directory /RESTORE_VOLUME/pre-0.2.0-check --check
```

The check stages and verifies code and writes a private journal; it does not stop
services or migrate the database. Repeat the command without `--check` in the
maintenance window to execute the upgrade. A new verification directory and a
new backup filename are required. On subsequent upgrades use
`--env-file /etc/freo/freo.env` and the current release's Python.

The updater locks the operation, verifies the publisher signature and every
release file, checks the source schema and platform, installs hashed wheels
offline into a separate virtual environment, records/stops active Freo units,
creates the encrypted backup and verifies it through an actual restore. Only
then does it run migrations and import missing settings. It compares every
pre-existing row's original columns against the restored recovery point, allowing
new columns, tables and seed/audit rows. There is one narrowly scoped exception:
the transition from `f39c8210b7de` to `a64f09e2b731` must set
`admin_users.installation_admin=true` for the unique `username='admin'` row.
The checker derives that expected value from the restored backup and compares
every other original field unchanged. It does not ignore the permission column,
allow changes to other accounts, or apply the exception to same-schema restores.
The migration revision is also checked separately.

For the RC5/RC6 transition, run the next candidate's verified tools from a separate
staging directory using the existing supported Python environment. Verify the
publisher signature before executing extracted code and verify the complete
release through its normal preflight. The frozen RC5/RC6 updater does not know
this data-migration exception; using it would stop activation after migration
when the primary account needs the grant. Do not submit this transition to its
old web runner. Preparing and rehearsing the updated tools is an operator release
step; the customer does not run a Flask permission command.

It preserves the legacy tree, installs code under `/opt/freo/releases/<id>`, and
switches `/opt/freo/current`. Managed service definitions are updated to that
pointer and `/etc/freo/freo.env`; original definitions are retained in the
private journal. Customized service files or execution overrides cause an early
refusal rather than being overwritten. Other systemd drop-ins remain in place.
The runtime renderer uses its current Python executable, avoiding accidental
calls into the previous virtual environment.

Previously active units are restarted; stopped stations are not started by the
updater. Readiness, running services and bounded audio reads from previously
active managed stations are checked before success is recorded. Reapplying the
same verified release is a no-op. A different artifact cannot replace an
already-installed version number. Frontend static URLs carry the release version
to avoid combining cached assets from different releases.

The updater supports the recorded 0.1.0, 0.2.0 and 0.3.0 candidate schemas. It
refuses radio/proxy template changes, operating-system/platform changes and
application downgrades. Radio engine and PostgreSQL major-version upgrades need
separate tested procedures. Browser approval of root-prepared plans is described in [candidate installation](install-candidate.md).
There is no unattended upgrade, arbitrary web-triggered root shell, automatic
data deletion or claim of uninterrupted broadcasting.

**Failure and interruption recovery.**

```bash
python -m freo_ops upgrade-status
```

The journal is under root-owned `/var/lib/freo-updates`, outside the web account's
writable state directory. A failure before migration resumes the recorded old
units when possible. Failure or interruption during migration/activation requires
operator recovery; the next upgrade refuses to overwrite an unfinished journal.
Before stopping units, the updater installs systemd maintenance conditions and a
persistent root-owned marker. This prevents enabled services from starting on a
reboot in the middle of migration. After a detected post-migration failure,
affected units are stopped and the marker remains. The marker is removed only
after preservation checks and release activation, just before starting services.
A power loss during that final startup can therefore leave the validated new
release running with an unfinished journal; inspect observed state before recovery.
The journal records the failing phase. When a subprocess supplies error output,
it is retained in a private diagnostic file beside the journal; do not publish
that file because database error messages can include private record values.

Never automatically restore an old dump over a database that may contain new
writes. Keep the failed database, release, journal and recovery bundle. Restore
the matched backup into new locations, validate it, map permissions and host
paths, restore the prior managed units from the journal, and deliberately attach
the matching previous release to the recovered database/media/configuration.
If writes occurred after activation, reconcile those changes or apply a forward
fix. No generic `flask db downgrade` can promise preservation.

After an operator has completed and validated recovery, remove
`/var/lib/freo-updates/maintenance` before deliberately restarting the recovered
units, and archive the private journal outside `journal.json` before attempting
a new upgrade. Do not edit its
phase to pretend an incomplete migration succeeded. Preserve old releases and
backup bundles until their retention period and restore checks permit cleanup.

**Distribution workflow.** [Recovery CI](../.github/workflows/recovery.yml) runs
the settings/release/failure tests and real PostgreSQL restore tests. The
[candidate workflow](../.github/workflows/release.yml) runs those checks before
building a tagged artifact, signing it and generating `latest.json` from that
exact artifact. Configure the `release` environment's
`FREO_RELEASE_SIGNING_KEY` (armored private key),
`FREO_RELEASE_SIGNING_PASSPHRASE` and `FREO_RELEASE_SIGNING_FINGERPRINT` before use.
Keep publisher keys outside this repository. GitHub Actions are pinned to
specific commits.

The workflow uploads a reviewable signed candidate to Actions artifacts; it does
not publish GitHub Releases or modify the external Freo website/API. After the
VM gate passes, publish the exact archive, detached signature, checksums and
release notes in a GitHub release. Publish the same `latest.json` and matching
download link on the website/API; mirrors must retain the identical archive
digest. The existing version-check response can consume its `latest_version`.

Before launch, configure protected release publishing and private security
reporting, validate fresh installation and real systemd upgrade/restore on the
separate VM, and complete the [website/API handoff](freo-live-distribution-handoff.md).
The project license and offline paid licensing are bundled in the 0.3 candidate.
Browser-local drafts/layout preferences, a dedicated restricted migration
database role, incremental backup and automatic retention are not implemented.
Saved schedules, server-side import drafts, paid licenses, account permissions
and database settings are included in the complete database backup.
