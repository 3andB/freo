# Changelog

## 0.3.0-rc.2 — installation candidate

- Correct HTTPS installation to save an HTTPS public URL before importing
  database settings, reject incomplete HTTPS inputs before provisioning, and
  explicitly enable the certificate renewal timer. Supersedes test candidate rc.1.

- Apply the 3andB source-available terms: three stations per owner for free;
  US$99 once for unlimited stations across all owned installations and future updates.
- Store signed perpetual licenses in PostgreSQL and verify them offline.
- Separate installation administration from station administration; add explicit
  browser approval of root-prepared signed upgrades with mandatory recovery checks.
- Complete installer source layout, x86_64 guard and private-file permissions;
  include signed dependency bundles and detailed operator/website handoff guides.

Migration: `d02f9a41c830` → `e83b9204c6af`, additive. Existing accounts do not
automatically gain installation privileges. Separate VM acceptance and owner
approval are required before publication.

## 0.2.0 — unreleased

- Persist installation URL/domain settings, station limits, upload limits and
  live microphone enablement in PostgreSQL. Import effective legacy settings
  once; preserve saved values on rerun and audit changes with revisions.
- Add encrypted database/filesystem backup, integrity verification and restore
  into a new database and filesystem tree, with data and file-hash comparisons.
- Add signed release bundles, complete dependency wheel locks, versioned staging,
  upgrade journaling and a mandatory restore check before database migration.
- Refuse fresh installation over an existing installation. Readiness now checks
  schema compatibility and installation settings initialization.
- Add PostgreSQL recovery tests, upgrade failure injection and GitHub CI.

Migration: `a71d25b609ef` → `d02f9a41c830`. A maintenance window is required.
Independent VM acceptance, the project license, publisher signing identity and
website release integration remain launch requirements. This is not a declaration
that the public installer/updater has passed end-to-end VM acceptance.
