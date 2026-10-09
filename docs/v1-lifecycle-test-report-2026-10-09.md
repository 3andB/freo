# Freo V1 Phase C installed lifecycle acceptance — 2026-10-09

Acceptance is in progress; the final installed checks below must finish before
this report is marked accepted.

## Source and environment

- Official 0.3.2 source: `83200e6508654bea13f404e9d5699a8ad3eae19d`.
- Accepted Phase B branch checkpoint: `af7bedbb6f3725c651dc211a53c68abf80e8c0a5`.
- Initial Phase C candidate: `d9cfcf4982933cf11ae8066d8a6eaba9955f9bf6`, private `1.0.0-dev.3`.
- Corrected complete lifecycle run: `4546609f` (full hash recorded in Git), private `1.0.0-dev.4`.
- Final runtime: private `1.0.0-dev.11`, commit `9d12917bdf037688512d816812458b85dd894d8f`; artifact SHA-256 `d02891bdb0535049f97d2333e961f920ed1cbcb5a5515228a0073d6b6e9bba92`.
- Disposable server: `Freo-v1-Test-1`, `209.38.64.12`, Ubuntu 24.04.5 x86_64,
  Python 3.12, systemd, local PostgreSQL, actual patched Icecast and Liquidsoap.
- Development: `/opt/freo-v1`, `develop/v1`. Production `/opt/freo` on the
  development host was not modified. No release, tag, or main merge was made.

## Commands and execution

Private candidates were built from clean pushed commits, with the existing
verified wheelhouse and test signing key. No private signing material or backup
key is included in this report or Git.

```sh
python scripts/build-release.py --candidate \
  --wheelhouse /root/freo-032-kit/source/wheels \
  --output /root/freo-phase-c/candidate-dev11.tar.gz

gpg --homedir /root/freo-upgrade-signing --batch --yes --detach-sign \
  /root/freo-phase-c/candidate-dev11.tar.gz

freo-admin upgrade check
freo-admin upgrade apply --version 1.0.0-dev.11
freo-admin status
freo-admin health
freo-admin resources
freo-admin services status
freo-admin services restart --service application
freo-admin services restart --service icecast
freo-admin services recover
freo-admin backup create
freo-admin backup list
freo-admin backup verify --id BACKUP_ID
freo-admin backup restore --id BACKUP_ID --confirm-installation INSTALLATION_ID
```

Artifacts and detached signatures were staged under the root-owned version
folders documented in the integration contract. Publisher trust was provisioned
independently. Candidate admission was enabled only on the disposable server.

`tests/lifecycle_acceptance/check.py` exercised the complete installed sequence.
Its invalid-argument and unprivileged-user checks require nonzero exit codes and
parse actual JSON. It deliberately stopped the ingest worker, verified degraded
health, and recovered it. Application and Icecast restarts were followed by real
readiness and stream checks.

## Verified findings and corrections

- Signed upgrade from accepted Phase B to the initial Phase C installation passed,
  including the existing updater's real encrypted recovery point and isolated
  database restore.
- The initial live restore correctly stopped rather than claiming success when
  its database-attachment preflight left a PostgreSQL connection open. Connection
  context managers commit/rollback but do not close psycopg2 connections. The fix
  closes that session explicitly; a focused regression verifies closure.
- The failed restore remained inhibited and resumed through the corrected
  `services recover` implementation. No database rows or schemas were repaired.
- The corrected `1.0.0-dev.4` installation completed the entire lifecycle sequence:
  actual worker failure/recovery, service restarts, encrypted backup, integrity
  verification, live restore into a suspended destination, and explicit
  reactivation with actual audio verified.
- A real updater process was killed at the recorded migration boundary. Generic
  recovery returned `recovery_required`; an explicitly confirmed CLI backup
  restore recovered the prior installation and preserved suspension. No automatic
  overwrite of a possibly migrated database occurred.
- Destination hosting policy, publisher trust, candidate policy, installation
  identity, and encryption key are preserved independently of customer restore
  roots, including self-hosted policy.
- Direct installer layouts reuse Phase A's canonical service-path conversion
  during recovery. Retained displaced files are excluded from future inventories.
- Cached older upgrade versions are reported as incompatible rather than causing
  every upgrade check to fail. Disposable successful preflight copies are removed;
  installed releases and recovery backups are retained.
- Explicit interruption recovery reconciles missing required workers, while
  continuing to respect station desired state and commercial suspension.

- Restoration now reconciles the destination's actual native Icecast listener
  limit and managed quota-aware DJ recorder before starting audio. A test that
  dropped HTTP response objects was corrected to hold all listener sessions.
- Clean 0.3.2 inventory tolerates V1-only storage directories that do not yet
  exist. Actual legacy testing caught this before any upgrade mutation.
- Verified administrative tooling is installed before the first migration.
  Independent `/usr/local` systemd guards survive restoration of older `/etc`
  service files; newer workers absent from old code are disabled and retained.
- A staging directory with incorrect permissions is refused. Recovery before the
  updater creates its journal now verifies the unchanged installation and reports
  `aborted_before_changes`. Documentation specifies private parent directories.
- Backups record their verified uncompressed size for expansion preflight.
  Restored code/schema, database mapping, stations, and bitrate capacity are
  validated before stopping services. Older preview catalogs without expansion
  metadata require the existing reviewed offline recovery procedure.

- A complete CLI recovery to self-hosted 0.3.2 exposed the older preflight's
  blanket refusal of Icecast overrides. Re-adoption now accepts only the exact
  root-owned managed inhibition guards; changed or symlinked guards still fail.
  The final candidate repeats interruption/recovery and the subsequent upgrade.
- The legacy Icecast process reached systemd's 90-second stop timeout during
  an interrupted upgrade recovery. The CLI correctly reported timeout and retained
  inhibition; `services recover` resumed to healthy 0.3.2 without repairs.
  Service operations now allow 240 seconds so systemd's stop/start deadlines can
  finish. A focused regression checks this bound; final-code repetition follows.

- The subsequent real upgrade caught an assumption that the application user
  could reread `/etc/freo/freo.env`. Recovery intentionally retained root-only
  credentials. The updater now supplies its already-parsed explicit values and
  sets `FREO_ENV_FILE=/dev/null` for child commands, preserving file permissions.
  The failed migration was recovered through its CLI backup without repairs.
  The final-code interruption/recovery test passed before the final upgrade.

## Remaining verification

Final-code repeat, interrupted restore with real reboot, self-hosted checks,
PostgreSQL opt-in tests, and original audio-feature regression evidence will be
recorded here before acceptance.

## Operational limits

Backups are full encrypted copies and require a maintenance window and staging
space. The administrator must escrow the generated key separately and manage
retention/off-server backup copies. There is no incremental backup or automatic
retention deletion. Integrity verification is distinguished from an actual restore.

Automatic live attachment supports the existing local PostgreSQL deployment and
approved same-installation backup IDs. Cross-host identity/ownership mapping and
external PostgreSQL recovery remain separate reviewed procedures. Destination
PostgreSQL and TLS configuration are not blindly replaced.

Studio must stage independently signed artifacts and enforce remote authorization.
Freo does not fetch arbitrary URLs, publish releases, implement billing, provide a
remote management daemon, or infer permission to restore after an SSH timeout.
