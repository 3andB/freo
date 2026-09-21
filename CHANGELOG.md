# Changelog

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
