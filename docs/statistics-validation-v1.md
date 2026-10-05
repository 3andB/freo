# V1 statistics validation — 2026-10-05

Application work is confined to `/opt/freo-v1`, branch `develop/v1`. Production
checkout files under `/opt/freo`, its services, database, main branch, tags and
releases were not changed. This is a linked worktree: its Git metadata is shared
under `/opt/freo/.git`, where the authorized development commits update objects
and the `develop/v1` reference. Test services use private loopback ports and
temporary storage. No deployment was performed.

## Reporting fixes

- Unmeasured transfer intervals display as gaps and export as blank cells.
  The existing numeric JSON field remains compatible; nullable transfer values
  and observed seconds are additive.
- A stale instantaneous peak outside the requested window is excluded.
- Incident summaries count the complete matching set. The latest-100 detail
  limit is explicit in the screen and CSV.
- CSV includes audience, transfer, storage, music, feedback and reliability
  summaries as well as device/session information.
- Table sorting and heading focus survive automatic refresh. Duration bands and
  date columns sort by their underlying values. Unapplied form
  edits do not silently change the report or export.
- Charts use readable labels at their actual width. Session cards, share bars,
  mobile tables and day/night maps received visual checks in Chromium.

## Focused checks

| Area | Evidence |
| --- | --- |
| Audience/current/history, simultaneous peaks, weighted averages, listener-hours, bytes/reset/gaps, timezone boundaries | Existing statistics tests and the independent soak ledger |
| Geography/maps, expiring presence, local data, website visitor separation | Statistics tests, browser suite and soak fixture geography |
| Music/rotation, feedback/moderation, station scope | Existing statistics tests, reporting edge cases and confirmed-play reconciliation |
| Storage/recordings, reliability/incidents and existing outcomes | Statistics, Phase 3 regression and reporting edge cases |
| Device families, sessions, weighted duration, duration bands/retention, gaps/restarts, privacy | Session suite, browser suite and soak ledger |
| Access and station isolation | Route/session tests, existing DJ tests and PostgreSQL tests |
| Migration preservation and concurrent collection | SQLite round trips and disposable PostgreSQL upgrade/downgrade/re-upgrade and concurrency tests |
| Filters, sorting, CSV, desktop/mobile and day/night visuals | Chromium browser suite and final visual checks |

The completed focused backend runs passed 21 statistics/reporting cases and 37
session cases. Six PostgreSQL cases passed (two analytics and four Phase 3), and
31 Phase 3 DJ/recording regression cases passed. The four-case Chromium suite
passed, and the additional final visual run passed after mobile/night styling
polish and numeric duration sorting (20 desktop/mobile, day/night screenshots).
These suites are focused validation, not
a whole-repository pass claim. Existing Flask-SQLAlchemy migration deprecation
warnings remain.

One combined backend process ended with signal 15 before completion. Smaller
complete reruns produced the results above. Earlier browser runs exposed a
replaced sort heading, which was fixed, and test-only freshness/polling races,
which were corrected to model a running collector and read one DOM snapshot.
A short soak preflight exposed stale cached sample totals in the test harness;
the full run reads final ledger totals before asserting duration/count thresholds.
The snapshot reconciliation also bounds confirmed plays to the snapshot's report
period: the worker can record a later play between the latest collector tick and
the database backup. This corrected a test assumption, not application data.

## Two-hour wall-clock soak

The actual 7,200-second run started at 04:38:40 UTC on 2026-10-05. It uses real
private Icecast and Liquidsoap processes, generated audio, the automation worker,
SQLite persistence and Chromium. Listener connections rotate desktop, phone,
tablet and VLC user agents. A separate long desktop connection exercises the
60+ minute band; supplementary 35-second, 10-minute, 20-minute and 35-minute
connections cover shorter bands. These timed connections are also included in
the repeatable harness. The collector polls on approximately the production cadence.

An independent ledger accumulates the observed inputs and checks all four
audience rollup resolutions for all stations and each station, session starts,
completed/interrupted counts, duration sums/bands, device counts, dashboard means,
listener-hours, peaks and confirmed plays. Browser tabs change each minute,
exports and window sizes are exercised every five minutes, and screenshots are
saved every ten minutes. A deliberate collection pause tests interrupted sessions
and coverage gaps.

The recording run completed **7,200.175 seconds**, from 04:38:40.473 to
06:38:40.648 UTC. All 388 collection observations completed their per-poll
accounting checks; 120 browser cycles and 24 CSV checks completed without a
JavaScript error. The final saved database reconciled against every journal
observation using the corrected harness and final reporting code:

| Saved result | Value |
| --- | --- |
| Persisted station/overall listener samples verified | 1,164 |
| Session starts | 70 |
| Completed / interrupted sessions | 66 / 4 |
| Listener-hours | 6.543889 |
| Completed bands: under 1, 1–5, 5–15, 15–30, 30–60, 60+ minutes | 1, 60, 1, 2, 1, 1 |
| Longest observed completed duration | 4,180 seconds |
| Worker errors / JavaScript errors | 0 / 0 |

**The original two-hour pytest invocation ended with a test-harness assertion
failure**, not a clean pytest pass. Its final check compared 750 confirmed plays
inside the report window with 751 all-time plays, including a play recorded after
the last listener sample. This is the same snapshot-cutoff assumption described
above; the running process retained its original code. The corrected assertion
passed against the complete saved database, and a focused regression verifies
both sides of that cutoff. A fresh 90.3-second real-stack run of the corrected
harness passed (six observations, two completed sessions). No application recording
change was needed for this test failure.

The original failed metrics/logs are preserved. Their elapsed/count fields show
the last minute-level progress update because the final assertion happened before
that cache was refreshed; the final metrics file's write timestamp records the
full elapsed wall time. The harness now also records elapsed time and live counters
in its finalizer on failure. The machine-readable
[evidence summary](statistics-soak-2026-10-05.json) contains both original status
and corrected reconciliation, with hashes for the saved database, journal and
scoped CSV files. These results establish data reconciliation for the full run;
they do not relabel the original pytest result as passed.

The collector/session recording implementation stayed fixed during the run.
Reporting and styling fixes made while it ran were checked separately with the
final browser tests and a fresh-process journal/database reconciliation. The
long-running browser retained its initially loaded assets. A naturally occurring
private source reset early in the run exercised interruption handling; it did
not produce an accounting mismatch. This is not an uninterrupted-audio claim.

Evidence remains under `/tmp/freo-phase4-soak-2h/`; logs and temporary databases
are not application assets. The opt-in repeatable harness is
`tests/test_statistics_soak.py`, enabled with
`FREO_STATISTICS_SOAK_SECONDS=7200`.

## Measurement limits and rollout

These are sampled connections, not identified people. Sessions entirely between
polls can be missed, durations are observed lower-bound estimates, and device
classification is conservative. Interrupted/ongoing sessions stay outside
completed-duration averages. Historical session buckets use UTC hours. No
identity profiles, fingerprinting or third-party tracking were introduced.

Phase 4 requires migration `f406a1b2c3d4` after `f316a1b2c3d4`. It adds temporary
JSON session state and hourly anonymous aggregates; the reporting fixes require
no further schema, service, configuration or permission changes. Deployment and
production restarts remain outside this development task. No separate deployed
V1 service was available to restart.
