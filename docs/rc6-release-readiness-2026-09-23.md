# RC6 release-readiness audit — 2026-09-23

## Status and scope

The requested one-hour production observation is complete. This is a development
readiness audit, not acceptance or publication of a signed RC6 release. Fresh-host
installation, populated upgrade, reboot, and public TLS acceptance still require
a separate disposable Ubuntu 24.04 VM. The accepted RC5 VM is excluded.

Final code checks passed: **1,059 passed, 12 skipped** across the backend,
browser, and real-engine audio matrix. The recovery workflow also passed.

Production and `main` were observed at
`92484ce413a05ce3db8f80082a3c502849bc0e67`. Findings and regression fixes are on
`feature/rc6-release-readiness`, descended from that baseline. No audit fixes have
been deployed. No production service restart was performed for this audit.

Production checks used read-only application requests and database transactions,
plus two public stream connections. Import, editing, scheduling, failure injection,
and audio controls were exercised against disposable fixtures. This distinction
matters: production's normal AUTO programming was observed, not deliberately
interrupted to exercise failure cases.

## One-hour production evidence

Observation: **18:27:07–19:27:07 UTC**, exactly 3,600 seconds, 720 samples at a
five-second cadence, with six successful test-session renewals.

| Measurement | freo-demo | freo-demo-2 |
|---|---:|---:|
| Continuously decoded audio | 3,605.863 s | 3,608.449 s |
| Consecutive recording segments | 61 | 61 |
| Observed playback decisions | 16 | 19 |
| Stable metadata matches | 634 | 631 |
| Stale worker observations (>10 s) | 34 | 30 |
| Maximum observed stale age | 17.202 s | 16.326 s |

Both decoders ran continuously without reconnection, decoder failure, or a detected
three-second silence interval at the configured -55 dB threshold. No fallback tone,
stable engine/player identity mismatch, health failure, or monitored service
restart was observed. Eight service PIDs remained unchanged and active.
Recordings include small startup buffers beyond the observation interval.

The full hour was **not a clean metadata-freshness pass**. Sixty-four stale-worker
samples occurred while heavy local regression tests shared the two-CPU production
host; one-minute load reached 16.742. The heavy suites were moved to disposable
GitHub runners at 19:05:59 UTC. The remaining **21 minutes 7.94 seconds** had 253
samples, 506 station status probes, zero issues, and median status latency 0.128 s.
This supports isolating test workloads from production; it does not establish
capacity limits or prove the precise cause of every delay. A future clean-host
soak should precede final RC6 acceptance.

Five-second polling and this silence threshold cannot certify subsecond transitions
or exclude shorter unobserved fallback intervals. DJ return timing is checked
separately with generated audio and real isolated engines.

## Whole-site and latest-change coverage

- Installation, listener feedback, station settings, tags, categories, media, and
  website screens: authenticated live GET checks at 390, 820, and 1,440 pixels,
  no horizontal page overflow; screenshots retained. Confirmed the combined
  station Save bar, contained Playback controls, and aligned feedback filters.
- Player: inspected fresh screenshots, bright outer colors, clipped circular
  center effect, textured-record motion, stationary artwork, pause/resume, and
  reduced-motion behavior. A muted browser connection tested actual playback.
- Installation and station statistics: map bounds, pan/zoom/reset/fullscreen,
  pinch and hidden-to-visible resize checked at 390, 820, and 1,600 pixels;
  the map remained a single bounded world.
- Live statistics: both test listeners appeared, with a visible located map pin
  and fresh chart data. After disconnect, both station counts and map counts
  returned to zero; historical chart activity remained. Two listeners sharing
  one location legitimately produced one map marker.
- Imports, playlist assignment, reset-after-import, save persistence, expired
  sessions, delayed polls, calendar/programming, and shared form appearance are
  covered by isolated browser suites. No production music or settings were edited.

Browser coverage uses Chromium/Chrome; this is not Safari/Firefox or physical
mobile-device certification. The two synthetic listener connections are not a
large-audience load test. The opt-in 48-hour scheduling soak, 100,000-track scale
benchmark, and long programme-shift rehearsal were not run in this audit.

## Findings and fixes

1. **Upgrade startup timing:** a single immediate stream request could fail while
   a restarted Icecast mount was still connecting. Upgrades now retry for up to
   60 seconds, requiring HTTP 200, an audio content type, and nonempty audio bytes.
   Persistent unavailability still enters the existing guarded recovery state.
   Four new cases failed before the fix; all 16 upgrade checks passed afterward.
2. **Missing settings schema:** startup requests could escape the controlled 503
   handler, including during response-cookie finalization. Database errors are
   translated into `SettingsUnavailable`, the failed transaction is rolled back,
   and the error response uses the established cookie policy. Public and admin
   requests with and without existing sessions now return controlled responses.
3. **Migration diagnostics:** Alembic logging configuration disabled existing
   application loggers. It now preserves them, including deletion diagnostics.
4. **Browser regressions:** updated assertions for category lists, the combined
   station Save control, calendar autosave, import reset, and current-version
   reporting. Assertions still verify persisted values and delayed-response safety.
   Controls use native clicks after scrolling clear of the sticky Save bar.
5. **Catalog save race:** song details could be saved with the previous artist
   while creation of a new artist was still in flight. Save is disabled during
   artist/album creation, and the artwork action cannot implicitly save stale
   details through that path. A held-response browser regression verifies the
   restriction and subsequent persistence of the new artist. The shared test
   picker also waits for completed selection, not just the already-typed text.
6. **Cart command refresh ordering:** a background status poll could supersede
   the authoritative refresh after a cart command, briefly re-enabling browser
   cart buttons before the next status arrived. Server-side locking remained
   enforced. Background polls now wait for the command refresh to finish; a
   deliberately delayed status response tests the visible lock through completion.
7. **Portable CI fixtures:** renderer tests mock OS identity lookup already outside
   their scope. Audio fixtures use short temporary paths to fit Linux Unix-socket
   limits. CI audio setup uses the existing provisioner's Icecast package guard.
8. **Repeatable acceptance:** a read-only candidate workflow runs backend, two
   browser groups, and real audio checks on disposable Ubuntu runners. It retains
   logs, JUnit reports, and fixture evidence for 14 days. Failures are exposed in
   job summaries and annotations; recordings from production are not uploaded.

## Validation results

The final code/test commit is
`c1e5a18d5bb3b5c080214af0ed543a4d375b47ad`. The
[full candidate run](https://github.com/3andB/freo/actions/runs/35916233769)
reports:

| Suite | Passed | Skipped |
|---|---:|---:|
| Backend | 911 | 10 |
| Primary browser | 56 | 0 |
| Programming browser | 60 | 2 |
| Real-engine audio | 32 | 0 |

The report, changelog, and historical-checklist clarification are documentation
changes after that tested commit. No application or test changes are included in
the final documentation commit.

Initial baseline backend run: 901 passed, four failed, nine skipped. The failures
were the old category layout assertion, missing-settings error handling, a stale
hard-coded release version, and logging disabled by migration setup. These were
investigated and corrected; the original failures remain in the audit evidence.

- Focused final backend regressions: **84 passed, one skipped**.
- Upgrade failure/recovery tests: **16 passed**.
- Real private PostgreSQL migrations and encrypted recovery: **14 passed**.
- HTTP/HTTPS setup validation: **three passed**.
- Installed read-only validator, dependency consistency, Python parsing,
  JavaScript syntax, and shell syntax checks passed.
- Live responsive-page, map, player-motion, and player-color checks passed.
- Targeted native-click station-save checks: **two passed**; redirected-page
  responsive form audit: **one passed** after adding an explicit rendering wait.
- Delayed artist-creation regression: **one passed locally**. Its companion local
  import test stopped at a Chromium/Snap temporary-file mapping mismatch before
  exercising import; the disposable CI rerun provides the full import result.
- Cart-state browser checks: **three passed**. The deterministic delayed-status
  case was also run against the prior source and failed at the visible lock
  assertion; restoring the correction made that exact case pass.
- Editor/booth startup readiness checks: **three passed**. Browser actions now
  wait for the editor to leave its intentional inert state and for the booth's
  first actual playback status, rather than relying on initial server HTML.
- [Recovery and release checks, run 35916233819](https://github.com/3andB/freo/actions/runs/35916233819):
  **passed** at the final code/test commit. Its settings/artifact/
  failure-injection stage reported **324 passed, four skipped**; the separate
  first-use browser, PostgreSQL recovery, and development-artifact stages passed.
- [Candidate acceptance, run 35910772660](https://github.com/3andB/freo/actions/runs/35910772660)
  tested prior commit `1d16e9e`: backend **911 passed, ten skipped**;
  programming browser **59 passed, two skipped**; real-engine audio **32 passed**.
  Primary browser had **54 passed, one failed** and exposed the catalog creation/
  save race described above. The complete run remains failed, not accepted.
- [Candidate acceptance after the catalog correction, run 35912705996](https://github.com/3andB/freo/actions/runs/35912705996):
  primary browser **56 passed** and backend **911 passed, ten skipped**. The
  programming-browser group had **58 passed, one failed, two skipped**, exposing
  the intermittent cart-lock rendering issue above. This run also remains failed.

The following run, `35914668597`, passed both cart-lock cases but exposed two
fixture startup races (typing into an inert editor and clicking an empty deck
before its first status arrived). Those test preconditions were corrected in
`c1e5a18`; the application code did not change for that correction.

The first broad local browser run was intentionally interrupted when work moved
to CI; it is not counted as a completed pass. Initial CI runs exposed outdated
browser assumptions and runner setup problems. A green successor is required;
intermediate failures must not be presented as passing evidence.

## Past deployment issues and remaining acceptance gates

The [earlier main deployment](main-deployment-2026-09-23.md) hit unreadable Git
checkout files under a private umask and an overly early stream probe. The signed
bundle extraction path normalizes source permissions, dependency creation uses
umask 022, the provisioner establishes readable source modes, and the installed
validator passes. The new upgrade readiness retry addresses delayed mount startup.
The actual signed RC6 installation/upgrade path still needs VM acceptance.

The September 21 stress reports included silence, stale metadata, fallback, and
calendar coverage failures; those runs were not clean acceptance runs. Subsequent
DJ/AUTO return fixes introduced prepare-before-clear behavior, a bounded engine
grace period, identity-based cancellation, and natural-EOF lease handling. Current
audio acceptance retains the existing strict timing criteria rather than relaxing
them to obtain green results. Historical passes alone do not certify RC6.

The later [September 21 station release](station-release-2026-09-21.md) also
records a request-reconciliation race and a 0.50-second calendar-boundary gap.
The implemented repairs require confirmed request absence before declaring loss
and increase worker cadence around calendar transitions. Its corrected boundary
tests measured 0.00, 0.00, and 0.25 seconds; a separate 301-second programme
rehearsal passed. The earlier three-hour run retains its failed result and the
owner's explicit acceptance of legacy hard-ID delays. This audit does not
reinterpret that decision as a general hard-ID timing guarantee.

Before freezing RC6:

1. Supply a **separate disposable Ubuntu 24.04 VM and test domain**. Do not reuse
   the populated accepted RC5 VM. No suitable VM was supplied during this audit.
2. Build the eventual exact candidate through the existing signed-bundle process;
   verify wheel hashes, manifest, signature, and source commit. The development
   source-review archive is deliberately unsigned and uninstallable.
3. Rehearse fresh installation, first-owner HTTP/HTTPS setup, real public TLS
   issuance/renewal, station creation, music import, playback, and host reboot.
4. Create a separately populated installation from the unchanged signed RC5
   package on a disposable host, then rehearse its upgrade; compare settings,
   users, media hashes, schedules, database rows/sequences, and playable streams.
   This must not rebuild RC5 or use its preserved accepted VM.
5. Rehearse encrypted off-host recovery onto a replacement disposable host and
   upgrade failure/recovery procedures. Retain evidence against the exact artifact.
6. Complete an isolated-load soak and review all final candidate CI results.

Fresh installation must reject existing installation state; populated systems use
the authenticated upgrade path. A source checkout test is not a substitute for
testing the distributed package.

## Automation and frozen RC5

Branch pushes triggered **Recovery and release checks** and **Full candidate
acceptance**. These have read-only repository permissions and run tests/upload
review artifacts. The signing workflow remains limited to version-tag pushes or
explicit manual dispatch. This audit created no version tag, signing invocation,
GitHub Release, deployment, or stable/latest pointer update. The installed upgrade
timer requires an explicit administrator-approved plan; it does not follow Git.
The final documentation-only push triggers recovery checks, while the full
candidate workflow's path filter excludes documentation-only changes.

RC5 source `739a0ed0b4bc9160ce4139cf641d3bd9f67ed9dc` and acceptance documentation
`2144f36d2e7a71f4da19b5c934c93058175366e5` remain reachable with their original IDs.
The RC5 tag and all 15 preserved artifact hashes were checked against the baseline.
The signed package, signatures, test kit, preserved hashes, deep-save directory,
and known-good populated RC5 VM were not modified. The RC5 VM was not accessed.

An environment probe before observation unexpectedly invoked Ubuntu's LXD snap
installer stub. Only the newly installed LXD snap was removed and its introduced
failed installer unit reset; no VM was created or accessed. This is recorded to
distinguish host tooling cleanup from changes to Freo or RC5.

## Private evidence

Root-only evidence is preserved at
`/var/backups/freo/rc6-acceptance-20260923T182501Z`, separate from RC5. It includes
the observation JSONL, continuous audio segments, screenshots, statistics before
and after departure, test logs/JUnit, CI API snapshots, and helper scripts.
`observation-timeline.png` and `.svg` plot measured host load, response times,
and all 64 flagged freshness samples against the CI handoff. Public
CI links identify the tested commits; production recordings and credentials are
not included in repository content.
