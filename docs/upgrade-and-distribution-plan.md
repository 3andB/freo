# Safe upgrades and public distribution

Implementation follow-up: the [0.2.0 candidate runbook](recovery-and-upgrades.md)
documents the implemented tools and remaining launch gates. The assessment below
is the original baseline and design, not a statement that every proposed phase
has been completed or that independent VM acceptance has passed.

Planning assessment, 2026-09-21. Repository reviewed at `35f4265`; application version `0.1.0`. This document proposes work; it does not implement an updater or certify the current installer. No production database, credentials, media, service, or deployment was changed for this assessment.

**Recommendation.** Keep PostgreSQL as the authoritative store for operator settings and station records, keep original audio in permanent media storage, and deploy each application version into a separate release directory. An upgrade must explicitly attach to the existing installation, verify a recoverable backup, migrate its schema, activate the release, and validate preserved data and playback. Start with the existing Ubuntu/systemd deployment; build one reliable distribution path before adding containers or other operating systems.

The preservation contract covers saved music, imaging, metadata, settings, accounts, identities, artwork, schedules, playlists, website content, history, accepted uploads and resumable jobs. It does not promise that active microphone connections or an in-memory playback position can survive a service restart. Plan a maintenance window for the first supported updater; uninterrupted broadcasting requires separate engineering and evidence.

**What the repository already provides.**

| Area | Observed implementation | Consequence |
| --- | --- | --- |
| Durable application state | [Models](../app/models/__init__.py), [scheduling models](../app/models/scheduling.py), [cue models](../app/models/cue.py), and [import models](../app/models/imports.py) persist station settings, stream/audio configuration, catalogs, schedules, carts, cues, users and jobs. | Preserve these tables and relationships; a replacement settings system should not duplicate them. |
| Website and images | `WebsiteSettings`, `WebsitePublication`, `WebsiteAsset`, `StationLogo`, `MusicArtwork` and `StationPlayerAsset` store settings and image bytes in PostgreSQL. | A complete database backup already includes these images. Do not assume every image exists only on disk. |
| Music and imaging | [LocalMediaStorage](../app/services/media_storage.py) resolves station directories and UUID storage keys, normally under `/var/lib/freo/media`. | Database records and filesystem bytes must be preserved together. |
| Database migrations | [Migrations](../migrations/versions) contain 44 revisions with one head, `a71d25b609ef`, and no missing parent revision in a static graph check. | Retain Alembic; the graph check does not prove every upgrade executes successfully. |
| Existing-data protection | [Provisioner](../scripts/provision.sh) retains an existing `.env`, avoids resetting an existing role password, and invokes `flask db upgrade`. | Useful safeguards already exist; this is not a deliberate database-reset installer. |
| Tests | [Station PostgreSQL tests](../tests/test_station_postgres.py), [event PostgreSQL tests](../tests/test_events_postgres.py), [import migrations](../tests/test_import_migrations.py), and other feature tests cover some migration preservation cases. | Extend these into release-to-release acceptance tests; they are not proof of installation, backup and rollback as a complete workflow. |
| Update awareness | [Release discovery](../app/services/central_api/releases.py) checks published versions; [app/version.py](../app/version.py) holds the client version. | Retain version discovery, but do not confuse it with artifact verification or an installer. |
| Installation acceptance | [Fresh VM checklist](clean-install-test.md) explicitly requires independent validation; README says this remains unverified. | Public support must wait for recorded acceptance evidence. |

**Gaps that currently prevent a safe-upgrade guarantee.**

1. `scripts/provision.sh` merges application and migration directories into `/opt/freo` and runs pip against the active virtual environment. A failed update can leave mixed code/dependencies; copying over directories can retain files deleted in the new release.
2. The provisioner applies migrations without first coordinating all database writers and timers. It restarts the web process, but `enable --now` does not restart an already-running automation or ingest service. Processes can therefore run different releases after a rerun.
3. Package changes, code replacement, radio rendering, schema changes and service activation share one script, with no installation-wide upgrade journal, backup gate or complete rollback protocol. The station-operation lock does not cover the entire upgrade.
4. Some central settings still come from `.env`, `app/config.py`, or direct environment reads. Live microphone enablement is read independently by multiple components. Keeping two authoritative copies would create configuration drift.
5. Essential secrets are outside PostgreSQL: `/opt/freo/.env`, `/etc/freo/secrets`, and central API `identity.json`. A database-only restore cannot reconstruct the same installation credentials.
6. Browser local storage holds schedule draft recovery/favorites, deck fade preference, layout/theme choices and upload recovery hints. Saved schedules and imported files have server-side persistence, but these local values are outside server backups.
7. `/ready` currently checks `SELECT 1`; it cannot detect a schema incompatible with the running release. Installer validation adds migration and service checks, but does not prove that all formerly running stations or all original files survived an upgrade.
8. Runtime code and units contain `/opt/freo` and virtual-environment paths. Moving releases requires updating these references together, including subprocess calls in `station_runtime.py` and optional microphone deployment.
9. No `.github` release workflow, project `LICENSE`, `SECURITY.md`, or `CHANGELOG` is present in this checkout. Direct Python dependencies are pinned, but the complete transitive environment is not locked with hashes. The README and contributor guide explicitly say the project license is undecided.
10. Installation documentation has accumulated feature-phase instructions and some older descriptions. The public guide needs one tested sequence matching the shipped artifact, including HTTPS/admin login, optional features and recovery.

**Where permanent state should live.**

All operator-editable system settings should be database-backed. There are necessary exceptions: the application must obtain database connection information before it can query settings, and distributing infrastructure secrets to every database client would widen access. Permanent protected files are part of the installation, even though they are not database rows.

| State | Target authority | Upgrade / backup behavior |
| --- | --- | --- |
| Existing station, audio, website, player, programming and directory settings | Existing typed tables | Migrate in place, preserve values and explicit opt-ins. |
| Installation public URL, domain aliases and verification targets, local station cap, upload limits, live-mic policy, non-secret ICE configuration, operator log preference | New typed `installation_settings` record with revision and update audit | Import existing effective values once; later application defaults never overwrite saved values. Treat license entitlements separately from local station policy. |
| Operator preferences and server-acknowledged drafts | `admin_preferences` and versioned draft records, scoped by user/station | Persist meaningful workflow preferences and acknowledged drafts; use browser storage only as a cache or unsent recovery aid. Anonymous listener volume/theme can remain device-local. Browser file handles and bytes never uploaded cannot be recovered by a server backup. |
| Database connection, Flask secret, environment mode, storage roots, secret-file locations and trusted deployment limits | `/etc/freo/freo.env` and protected credential files | Preserve across releases, restrict readers, include in encrypted recovery material. Optional emergency overrides must be explicit and visible to administrators. |
| Icecast/station credentials and TURN credentials | Protected secret files, with references where appropriate | Retain existing values; never rotate implicitly during upgrade. Keep privilege separation between web, ingest, automation, statistics and playout. |
| Central API identity/access token | Existing `/var/lib/freo/central-api/identity.json` | Preserve directory ownership/modes and identity; a normal upgrade must never register a new installation. |
| Music, imaging, originals, filesystem artwork and accepted pending uploads | Permanent `/var/lib/freo` paths or a configured external media root | Preserve bytes, keys, station slugs, ownership and ACLs. Record every external root in the backup inventory. |
| Generated Liquidsoap/Nginx configuration and playlists | Generated from database settings plus protected host configuration/secrets | Validate and regenerate when required. Preserve manual host overrides separately and report unmanaged edits before replacement. |
| GeoIP downloads, previews and caches | Rebuildable storage | Classify individually; never delete originals while rebuilding. Preserve if regeneration would make recovery unacceptably slow. |
| Sockets, PIDs, live mic sessions and process leases | `/run/freo` or process memory | Recreate safely; do not restore stale commands, leases or live sessions. Reconcile persistent queue/cue state against the restarted engine. |

The settings migration needs a single shared settings service used by routes, CLIs, renderers and workers. Register types, validation, defaults, permission requirements, secret references, and whether a change is immediate or requires rendering/restart. Maintain a revision so long-running processes invalidate their cache after changes. A database outage must not silently reset settings to defaults.

Migrate environment values through an explicit adoption/import command after the settings schema exists. Insert only missing settings, record source and revision, and retain unknown legacy keys in the protected legacy configuration until reviewed. Already saved database values win over re-imports. A second import must produce no changes. Avoid reading a machine's `.env` inside Alembic migrations: the same database migration should have deterministic behavior on every host.

Keep bootstrap, diagnostics and migration commands usable before the settings table exists. Load database settings lazily through the shared service; normal production requests/workers should fail readiness until the required schema and adoption step are complete. This prevents a circular dependency in which the new application cannot start the migration needed to load its own settings.

Keep `FREO_MEDIA_ROOT`, API identity paths and other bootstrap paths available before database access. Model live-mic preference separately from gateway availability; moving its flag into PostgreSQL must not enable an uninstalled service. Secret-bearing ICE values need a credential mechanism, not an ordinary JSON settings value exposed to clients.

**Release layout and attachment rules.**

Proposed layout:

```text
/opt/freo/releases/<version>/     complete application, migrations, templates, venv
/opt/freo/current -> releases/<version>
/etc/freo/freo.env               stable bootstrap configuration
/etc/freo/secrets/               stable restricted credentials
/etc/freo/overrides/             documented administrator customizations
/var/lib/freo/media/             permanent originals and imaging
/var/lib/freo/uploads/           pending/resumable imports
/var/lib/freo/central-api/       permanent installation identity
/var/lib/freo/updates/           upgrade journal and release/backup references
/var/backups/freo/              local backup staging; configure off-host storage too
/run/freo/                     temporary runtime state
```

Install each release into its final versioned directory before creating its virtual environment; virtual-environment executable paths must remain stable. Make releases root-owned and read-only to service accounts. Units should use `/opt/freo/current` and `/etc/freo/freo.env`. Finish switching every affected process before accepting writes; changing a symlink alone does not replace already-running Python processes. Retain the previous release and its verified artifact.

Release cleanup may remove only inactive, managed release directories after retention checks. Uninstall should remove application/services while retaining databases, media, configuration and backups by default. A separate, explicit data-purge operation must never be part of installation or upgrade.

Provide separate commands for fresh installation, adopting an existing installation, attaching a replacement host to existing state, and upgrading. The upgrade command must never fall back to fresh installation on authentication failure, connection failure, missing secrets, or an unexpected schema. Fresh installation must refuse an existing database/state directory unless explicitly using an adoption workflow. An attachment preflight must verify database identity, Alembic revision, installation identity and referenced media. An existing `.env` alone is not sufficient evidence of a healthy installation.

For this deployment, adoption must inventory the actual effective configuration and all storage paths without printing secrets, create and restore-test a backup, import settings, stage the current release, update units and subprocess paths, and validate a maintenance-window cutover. Keep the legacy tree and original config as a protected recovery copy until acceptance. Preserve UUIDs, track identifiers, station slugs, account hashes and license acceptance audit records. A restore of the same installation retains identity; an intentionally independent clone needs a separate identity workflow and must not reuse production reporting/stream destinations.

**Upgrade protocol.** These commands are proposed interfaces, not commands available today:

```text
freo doctor
freo upgrade --version <release> --check
freo backup create --verify
freo upgrade --version <release>
freo upgrade status
freo rollback --check
freo restore --backup <id> --target <new-location>
```

The updater should persist a restartable sequence:

1. Acquire an installation lock plus a database migration lock; coordinate with existing provisioning locks. Record current release, database revision, installation identity, enabled services/timers, station desired states and actual service states. Reject concurrent upgrades or an unfinished operation requiring recovery.
2. Fetch an explicit supported release and verify its authenticity and digest. Check OS/architecture, PostgreSQL and radio dependency compatibility, schema range, free space/inodes, writable backup destination, external storage availability and prior unresolved jobs. Produce the expected migration/restart/downtime plan before mutation. Normal application updates must not silently upgrade PostgreSQL, the operating system or the radio engine.
3. Stage the complete release, locked dependencies, optional installed features and manifest. Run import/static checks in an isolated environment. No staging process may register with the central API, provision stations, run production jobs or migrate production automatically.
4. Enter maintenance mode and stop every write path: web mutations, automation, ingestion/analysis, statistics, central reporting, public schedule publishing, provisioning and related timers/CLI operations. Let active work settle to a recoverable boundary. For the initial supported workflow, stop affected playout too and announce the measured interruption. Later continuity work may retain playout only with a tested event spool and queue-reconciliation design.
5. Create a consistent recovery point containing database, durable filesystem state and secrets. Validate the manifest and restore into isolation before schema mutation. A missing or failed backup stops the update. Pre-copy large media while live if useful, then finish a checked delta under the write freeze; never assume a database snapshot also snapshots media.
6. Run one migration process using the staged release and a dedicated migrator credential. Record the starting/ending revision and each nontransactional step. Use timeouts and capacity checks; do not blindly retry a partially completed destructive operation.
7. Render affected runtime configuration from saved settings, validate Liquidsoap and Nginx, and retain the prior working configs. Stage replacements and journal activation because database transactions do not cover filesystem changes, package scripts or systemd.
8. Atomically switch the release pointer. Restart required processes in a documented dependency order, still gated from normal writes. Require release/schema compatibility, settings/media integrity and service startup checks. Keep the public maintenance gate until basic acceptance passes.
9. Restore saved station intent and worker/timer state; validate bounded audio reads and confirmed playback for previously running stations, and ensure stopped stations remain stopped. Run advanced playback acceptance after restart, while recognizing that playback/history writes end the simple automatic-rollback window.
10. Mark success, clear maintenance, retain backup/previous release, and show version, backup ID and verification results. Interruption at any phase must leave enough journaled state for `status` and a deliberate recovery action after reboot.

Do not implement privileged updates by giving Flask arbitrary shell/sudo access. A future Admin → Updates page can show preflight results and submit a narrow, authenticated, audited request to a root-managed updater. Start with the CLI so recovery remains available when the web process cannot boot.

**Schema policy and rollback.**

Keep one reviewed Alembic head and immutable published migration files. Test actual historical release schemas, not just `create_all()` followed by stamping a revision. Use additive changes, backfill existing values, and remove old fields only after the compatibility window. Treat renames, constraints, default changes and meaning changes as data migrations requiring preservation assertions. Alembic explicitly requires manual review of autogenerated migrations; its cookbook treats substantial data migration as a separate design problem. [Alembic autogenerate guidance](https://alembic.sqlalchemy.org/en/latest/autogenerate.html), [data migration guidance](https://alembic.sqlalchemy.org/en/latest/cookbook.html#data-migrations-general-techniques).

Large backfills must be resumable, bounded and observable rather than holding a long schema transaction. Each release manifest should declare version, commit, artifact digest, migration head, supported source releases/schema revisions, compatible runtime/dependency versions, optional components, required restarts and downgrade compatibility. Unknown/newer schemas fail closed with recovery guidance. PostgreSQL major upgrades are a separately tested procedure.

Use a runtime database role without schema-creation/drop privileges and a separate migration role. This limits accidental application damage, although it does not replace backup and migration review. Readiness must verify the declared schema range and installation state; it should not mutate schema or apply migrations at startup.

Rollback depends on the point of failure:

| Failure point | Recovery |
| --- | --- |
| Download/staging before maintenance | Leave running release and data untouched. |
| Backup or transactional migration failure | Confirm the recorded schema/config state before resuming the old release; account for separately committed work. |
| Activation failure with an explicitly backward-compatible schema | Restore prior release/config pointers and restart the prior processes; preserve current data. |
| Incompatible migration, before new writes | Restore the matched pre-upgrade database and filesystem snapshot to replacement locations, validate, then switch connections/paths. Retain the failed installation for diagnosis. |
| Failure after new writes/playback resumes | Block automatic database rewind: it would discard new uploads, edits and history. Prefer a forward fix or an operator-reviewed recovery/reconciliation plan. |

Do not present `flask db downgrade` as a universal rollback mechanism. Some existing downgrades intentionally refuse populated states, and a reverse schema operation cannot reconstruct discarded information.

**Backup and restore must ship before the updater.**

Inventory PostgreSQL, every configured media/upload root, `/etc/freo`, the legacy/new environment file, central API state, necessary local state, Nginx customizations, systemd overrides and TLS recovery material. Include pending imports whose database rows reference staged files. Preserve file ACLs, ownership mapping and restricted modes on restore; user IDs can differ on a replacement server. Record filesystem keys, file sizes and SHA-256 digests, release/schema versions, PostgreSQL version, installation UUID and backup completion status in a private manifest.

For an initial single-server upgrade backup, use a complete custom-format database dump and coordinated filesystem backup under the write freeze. `pg_dump` provides a consistent database export and custom archives support `pg_restore`, but a single-database dump does not include cluster-global roles/tablespaces. Preserve required roles separately or recreate narrowly scoped roles from the deployment manifest; use a compatible dump client. [PostgreSQL pg_dump documentation](https://www.postgresql.org/docs/current/app-pgdump.html), [cluster-global objects](https://www.postgresql.org/docs/current/backup-dump.html#BACKUP-DUMP-ALL).

Verify by restoring to a new disposable database and isolated filesystem, checking identities/settings/media references, then booting the matching application with outbound reporting and public broadcasts disabled. Listing a dump archive or checking its checksum alone does not establish recoverability. Restore tooling must fail on errors and never default to overwriting the live database. [PostgreSQL pg_restore documentation](https://www.postgresql.org/docs/current/app-pgrestore.html).

Encrypt backups containing database records and secrets; keep recovery keys separately accessible. Support an off-host destination and retention covering multiple releases, with explicit free-space and backup-freshness checks. Local snapshots on the same disk protect against some update mistakes but not disk loss. For large/active installations, add physical backups and WAL archiving with a tested PostgreSQL backup tool and a matching media recovery strategy; periodic logical exports alone do not meet a near-zero disaster-recovery data-loss target. [PostgreSQL continuous archiving](https://www.postgresql.org/docs/current/continuous-archiving.html).

The upgrade target is zero loss of durable state acknowledged before maintenance. Hardware/disaster recovery targets depend on backup frequency and off-host replication. Measure downtime, backup/restore duration and storage overhead on representative libraries before publishing capacity or recovery-time claims.

**Distribution through GitHub and the website.**

| Approach | Fit | Recommendation |
| --- | --- | --- |
| Signed/versioned Ubuntu release bundle plus systemd installer | Closest to current accounts, sockets, host audio/networking, Nginx and PostgreSQL | First supported route; bundle complete application resources and dependency locks, with a versioned management CLI. |
| Native Debian package/repository | Useful later for managed fleets and dependency integration | Follow once updater semantics are proven. Package removal must retain data; package hooks must not run surprise destructive schema upgrades. |
| Containers/Compose | Can isolate dependencies, but introduces volume, permission, host networking and WebRTC design work | Later alternative using the same state/backup/migration contract. Containers alone do not solve data preservation. |

For the first release, support Ubuntu 24.04 on one explicitly tested architecture, Python 3.12 and a documented tested PostgreSQL/radio package set. Select architecture and resource minimums from VM measurements; do not imply ARM or generic Linux support without testing. Remote databases and external storage require explicit test coverage before being listed as supported configurations.

GitHub should be the canonical source/tag/release record. Publish a complete release archive, release manifest, checksums, verifiable signature/attestation, dependency inventory/SBOM, third-party notices and release notes containing upgrade sources, downtime and recovery limitations. Generate all assets in CI from the release tag; do not upload a developer's working directory or runtime `.env`. Lock and hash all Python dependencies, including enabled optional components, and record the tested OS package versions. [pip secure installation guidance](https://pip.pypa.io/en/stable/topics/secure-installs/).

Use protected release workflows with minimal credentials and pinned action revisions. Enable GitHub immutable releases and verify the associated artifact provenance in the downloader; checksums fetched alongside a compromised archive are not sufficient proof of origin. GitHub immutable releases lock associated tags/assets and generate release attestations. [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases), [artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations).

The Freo website should display the same approved release version, platform requirements, installation/upgrade guides, changelog, recovery guide and download link. It may mirror the exact artifact bytes; verify identical digests in CI. Generate website/API update metadata from the same release manifest instead of maintaining three independent version numbers. Extend the existing release-discovery API only through a reviewed contract change; keep manual verified downloads available when that service is unreachable.

The public installation journey should be: check prerequisites → download/verify a specific release → initialize a new installation or explicitly attach existing state → configure domain/HTTPS → create the first administrator privately → create a station → confirm real audio → configure backups. Existing accounts, passwords, secrets and stations must not be reset on rerun. Production sets secure session cookies, so test the documented IP-only/HTTP behavior and provide a supported HTTPS admin setup rather than promising login on an unverified path.

Before promotion, select a project distribution license and publish the corresponding `LICENSE`; document how application licensing differs from music/broadcast rights. Review bundled assets and dependency notices, document the existing outbound reporting and opt-ins, and provide `SECURITY.md`, support channels, supported-version policy, contributor guidance and a concise changelog. License choice is an owner decision; this plan does not select or grant a license. The distribution website/API may live in another repository; no external website implementation or publishing was performed here.

**Implementation order and acceptance gates.**

| Phase | Concrete deliverables | Exit condition |
| --- | --- | --- |
| 1. Preservation and recovery | State inventory, backup/verify/restore tooling, isolated recovery harness, fixture with representative settings and legal audio | Restore the existing installation format to a separate location with matching durable settings, identities, original hashes and functioning login/playback. |
| 2. Settings and adoption | Typed installation settings, shared settings access, one-time legacy importer, operator preference/draft persistence, bootstrap/secret separation | Repeated imports are no-ops; all consumers use the same saved values; disabled options remain disabled; credentials and external paths survive. |
| 3. Versioned deployment and updater | Complete release packaging, units/path conversion, explicit install/adopt/attach/upgrade commands, locks, journal, migration role, readiness and rollback | Repeated upgrade succeeds; deliberate failures at each phase recover without resetting data; all processes report the intended release. |
| 4. Automated release verification | GitHub CI, locked dependencies, upgrade matrix, VM tests, attestations, manifests and release artifacts | Every supported source release upgrades to the candidate with state assertions and a verified recovery path; release assets contain no deployment state. |
| 5. Distribution launch | Owner-approved license, support/security docs, website/API metadata integration, final install/upgrade/recovery documentation | Independent clean-VM, upgrade, reboot and replacement-host restore pass using the exact public artifact. Publish recorded results before marking supported. |
| 6. Broader deployment | Optional Admin Updates UI, large-library backup optimizations, additional platforms or container packaging | Each new route passes the same preservation and recovery gates. |

Stages 1–3 are the critical path. CI scaffolding and documentation can progress alongside them, but broad promotion should wait for stage 5. Estimate delivery only after the recovery prototype measures actual library size, restore speed and migration behavior.

The release fixture must exercise multiple stations with distinct running/stopped intent; music in every supported format; imaging; shared tracks; metadata/tags/artwork; account hashes and agreement acceptance; stream processing settings; custom domains and directory opt-ins; website drafts/publications; player settings; playlists/carts/cues; schedules/timezones; events/traffic; history/statistics; central identity; and pending imports. Compare values and relationships, not row counts alone. Allow only documented migration transformations, such as newly introduced system rows.

Required automated and VM scenarios:

| Scenario | Required result |
| --- | --- |
| Empty install from the public bundle | Empty customer library/stations, no demo credentials, all required services work, supported HTTPS onboarding succeeds. |
| Upgrade from each supported released version and the current legacy installation | Existing UUIDs, settings, hashes and relationships survive; new defaults populate missing settings only. |
| Rerun, concurrent invocation, reboot/interruption at each phase | One updater proceeds; completed work is not repeated destructively; journaled recovery is clear. |
| Database offline/wrong/newer schema, missing config/identity/media, invalid release signature | Abort before mutation; never create replacement state to hide the problem. |
| Disk full, failed pip download, migration lock timeout, failed render or service start | Recover to a known state using the phase-specific rollback policy; preserve the backup and old release. |
| Restore to a replacement machine | Recreate permissions, reconnect saved database/media, preserve identity, regenerate configs, resume desired station states without duplicate jobs/commands. |
| Long-running workers, pending uploads, active mic, cached browser tabs | Drain/recover jobs, end ephemeral mic safely, reconcile queues, load matching frontend assets and protect server-acknowledged drafts. |
| Large library and offline central API | Measured storage/downtime; local upgrade/recovery remains possible without successful enrollment or telemetry. |

Run database migration suites against disposable PostgreSQL instances, with explicit test credentials and no inherited production `.env`. Existing opt-in PostgreSQL tests are useful starting points but must run as release gates. Test full migrations and resulting schema against model metadata, preserve old-release fixtures, and use isolated VMs for apt/systemd/Nginx/Liquidsoap behavior. Add cache-busted frontend asset URLs so the one-hour static cache cannot combine old JavaScript with a new backend.

**Assessment limits and owner decisions.** This was source/configuration/documentation inspection and primary-source research, plus a static migration-graph check. No installer, live upgrade, migration, production query, backup, restore or integration test was run. The plan establishes requirements, not a claim that the existing installation is recoverable. Remaining product decisions are the distribution license, confirmed GitHub/website ownership and release location, acceptable maintenance downtime, backup destination/retention and supported scale. Use the single-host Ubuntu path and explicit maintenance window as the initial engineering assumptions.
