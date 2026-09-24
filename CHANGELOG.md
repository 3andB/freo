# Changelog

## 0.3.0-rc.6 — signed test candidate; VM acceptance pending

- Report the actual running development version through the existing reporter;
  display server-provided Current, Update Available, Ahead, or Unknown status,
  cached release details, and stale contact information. See the
  [version-awareness handoff](docs/version-awareness-client.md).

- Refine installation, feedback, tags, and category administration; present
  categories as an informative list and keep controls aligned on smaller screens.
- Combine station settings into one save operation, preserve validation edits,
  and make pending changes and applied audio settings clearer.
- Add playlist destinations to music import, reset completed imports for the next
  song, and reduce repeated work when loading music-library summaries.
- Prevent song details from saving a stale selection while a new artist or album
  is still being created.
- Keep cart controls locked while the authoritative status after a command loads,
  so background polls cannot briefly restore stale button states.
- Restore textured vinyl in the public player with a circular animated center,
  brighter outer colors, and separate stationary artwork; respect reduced motion.
- Keep statistics maps within a single world and verify live listener counts,
  located pins, and historical chart updates.
- Wait for station audio after upgrade restarts, return controlled responses when
  installation settings are unavailable, and preserve migration diagnostics.
- Run repeatable backend, browser, recovery, and real-engine acceptance on
  disposable CI hosts. See the [RC6 readiness audit](docs/rc6-release-readiness-2026-09-23.md)
  for evidence, limitations, and remaining VM acceptance gates.

RC5 remains an immutable historical candidate. RC6 packaging and verification
are described in [the test installation guide](rc6-installation.md). A signed
test package is not VM acceptance or approval for a stable public release. The current schema remains
`f39c8210b7de`; these RC6 changes introduce no additional migration.

## 0.3.0-rc.3 — first-login candidate

- Fix session cookies for explicitly configured HTTP installations while retaining
  Secure cookies for HTTPS, including public/static responses that refresh sessions.
- Create one-time `admin` / `IAmOnTheAir` setup on fresh installs, require a private
  password before administration, and invalidate other initial-password sessions.
- Preserve existing accounts on upgrade. Store a durable bootstrap marker so the
  initial account cannot be recreated by rerunning bootstrap.
- Validate the public first-login flow during installation and add real Chromium
  HTTP/HTTPS setup, logout and application-restart acceptance tests.

Migration: `e83b9204c6af` → `f39c8210b7de`, additive. Prior candidates are retained.
Fresh VM installation, host reboot, public certificate issuance/renewal and radio
acceptance remain required before release approval.

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
