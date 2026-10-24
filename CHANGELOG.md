# Changelog

## 1.0.0-rc.15 — private candidate; acceptance pending

- Expose an explicit retry when the persistent monitor reaches a clean stream EOF.
- Keep a prepared return to automation when a station-ID event is waiting for DJ control to end; retain the event's existing Auto scheduling policy.
- Preserve passwords in disposable PostgreSQL test URLs and seed historical schemas for forward migration checks. Retain provenance downgrade refusal and matched-backup recovery coverage.
- Read streaming WAV regression recordings in bounded chunks and include the corrected transport and schema-head fixtures.
- Return a controlled storage-unavailable response when hosted quota accounting cannot read customer media. Keep ordinary tests in temporary media roots.

## 1.0.0-rc.11 — private candidate; acceptance pending

- Provision recording directories, ACLs and station write access when rendering new stations. Apply the existing per-directory worker write exception when it is first added, without restarting station engines; skip redundant worker refreshes and retain original-media protection.

- Initialize new stations for worker discovery and live control without legacy rotation activation; repair missing state on older ready stations without enabling playback or resetting existing controls.

- Keep public-player live status clear of station identity on narrow screens and long station descriptions; let the header grow with its content.
- Refresh the stylesheet URL so existing listeners receive the layout repair. Add real-browser overlap and clipping coverage at phone and desktop widths.

## 1.0.0-rc.10 — private candidate; acceptance pending

- Protect playout, microphone and automation clocks with a higher-priority CPU slice under contention.
- Validate installed CPU-controller priority and service membership.
- Retain RC9 libigloo, managed-validator and cold-start readiness repairs.

## 1.0.0-rc.9 — private candidate; acceptance pending

- Allow the shared cold-start budget when verifying administrative service restarts and recovery.
- Retain RC8 dependency ownership, managed-validator and upgrade deadline repairs.

## 1.0.0-rc.8 — private candidate; acceptance pending

- Reject conflicting libigloo runtime ownership before dependency installation.
- Use the shared cold-start budget during upgrades.
- Validate managed installations using their canonical configuration file.

## 1.0.0-rc.7 — prepared candidate; exact-kit VM acceptance pending

- Retain RC6's bounded future-event scan, canonical timezone cache, retired
  control-page response handling and earlier microphone/Studio/installer fixes.
- Require matching libigloo development/runtime candidates >= 0.9.4, simulate
  the required native build transaction without removals, and check the loaded
  library before building or activating hosted Icecast.
- Return actionable dependency failures without publishing hosted policy or
  stopping healthy services. Keep repository priorities scoped to the required
  packages and permit future compatible package revisions.
- Share bounded 120-second cold-source readiness and diagnostic validation,
  preserve maintenance/inhibition on failed hosted activation, and give the
  installer acceptance supervisor time for validation followed by startup.
- Include the runtime probe, readiness module and RC7 installation guide in
  the customer archive. Schema and the 42 dependency wheels are unchanged.
- Build new publisher-signed application and installation-kit files; retain
  existing signed candidates. Publication and deployment require acceptance.


## 0.3.2 — released 30 September 2026

- Publish the exact signed stable kit after fresh Ubuntu 24.04 x86_64 acceptance;
  no rebuild or runtime change after the owner's test.
- Confirm automatic dependency installation, PostgreSQL migrations, Nginx/login,
  music upload/processing/deletion, playlist and Simple scheduling, live playback,
  persistence and automatic broadcasting after a full VM reboot.
- Installer and before/after-reboot validators exited 0, with no failed units.
- Retain the accepted RC2 application, installer, schema, customer archive
  inventory and all 42 pinned dependency wheels.
- Regression evidence: 1,273 passed, three optional skips, no unresolved failures.
  See [release notes](docs/release-0.3.2.md) and [acceptance scope](docs/0.3.2-acceptance.md).

## 0.3.2-rc.2 — fresh-install and reboot/recovery acceptance passed

- Preserve Back/Forward and link navigation received while page responses or scripts are loading.
- Retain the prepared AUTO successor when the decoder moves it during a stopped-deck return.
- Consume Cue playback completion before selecting the next entry when mixer and event-log observations straddle EOF.
- Stop timer-triggered workers that start while upgrade maintenance guards are installed, before backup or migration.
- Match event-due model index metadata to the existing PostgreSQL migration.
- Correct licensing, handoff-log, recovery and browser setup regressions without changing licensing or downgrade safeguards.
- Isolate PostgreSQL test databases and honor standalone Chrome for system browser tests.
- Wait for loaded event results and the replacement statistics page in browser regressions.
- Control the initial event scheduling instant in the restart fixture and measure soak silence from continuously decoded audio; retain deadline and playback assertions.
- Ship runtime files and operator documentation, retain both runtime requirements files in the installed application, and keep development files and acceptance fixtures in the source checkout.
- Retain the accepted driver fixes, local-vhost validation and all existing pinned runtime dependencies; explicitly bundle the updater’s previously undeclared packaging dependency.


## 0.3.2-rc.1 — signed test candidate; fresh-VM acceptance pending

- Validate the saved Freo public origin through local Nginx, preserving HTTP
  Host, HTTPS SNI/certificate checks, cookies and same-origin redirects. Retain
  CSRF, initial login, mandatory setup and existing-account safeguards.
- Report local application validation separately from a best-effort public
  reachability probe. External/hairpin failures do not reverse a local success.
  Print a clean installation-complete message and the exact admin URL.
- Add real Nginx default-vhost/Host/SNI regression tests and run the actual login
  validator after PostgreSQL migrations and bootstrap in package acceptance.

Includes all 0.3.1 work; dependency pins and schema are unchanged. The 0.3.1 tag
and signed artifacts are preserved. See [test installation](docs/0.3.2-rc.1-installation.md).

## 0.3.1 — prepared for fresh-VM acceptance

- Install pinned Psycopg 3 binary wheels automatically, while retaining Psycopg 2
  for backup/recovery. Pin SQLAlchemy to 2.0.54 so online installs cannot silently
  change the default PostgreSQL driver.
- Share Python installation and smoke checks between fresh installs, staged
  upgrades and the release builder. Fail incomplete kits without online fallback.
- Validate generated and supplied wheelhouses in empty virtual environments;
  require both drivers and the Flask migration command before database setup
  or stopping existing services.
- Gate release signing on offline package installation, real PostgreSQL
  migrations, bootstrap, readiness and Gunicorn restart checks. Add Ubuntu 24.04
  CI coverage for every requirements entry point.

No application schema change; head remains `c83d4e5f9012`. Historical release
artifacts are preserved. See [installation and repair](docs/0.3.1-installation.md).
Fresh-VM provisioning, radio, HTTPS, reboot and public publication remain pending.

## 0.3.0 — staged for publication

This production installer is prepared from tested RC9 source
`95234867b647e41ca36272e4d81d29d8bd1ba621`. The only application change
is the canonical installed version. Preparing this package does not publish
a GitHub Release or update an existing installation. See the
[0.3.0 installation guide](docs/stable-installation.md).

Changes since RC6 include:

- Revoke logged-out sessions despite delayed background responses, while
  preserving independent browser logins and active-session renewal. Existing
  installations require one fresh sign-in after upgrading.
- End LIVE MIC on booth exit and tab changes and restore the interrupted feed.
- Grant installation administration to the existing primary `admin` account
  with an idempotent migration.
- Save optional city-level station coordinates and include them in the existing
  station metadata sync, without inferring a location or requiring directory opt-in.
- Simplify playlist selection during import and improve Software page spacing.

Schema: `c83d4e5f9012`. RC9 artifacts remain unchanged. The owner reported the
new RC9 VM running; public health, readiness, player and decoded stream checks
passed. The owner also supplied a successful installed validator result covering
web, database, radio services, private listeners and login. This is not a claim
that all manual acceptance items were observed.
The separately delivered validation record records the exact stable package
checks and any outstanding acceptance items.

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
are described in [the test installation guide](docs/rc6-installation.md). A signed
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
