# Station Control and DJ Booth release — September 21, 2026

Scope: release the current Station Control, scheduling/Blocks, DJ Booth,
statistics recovery, and test-harness work, with the owner's explicit approval
to commit, push, and restart live services. Preserve existing programming and
the accepted soft ID timing policy.

The completed three-hour programme test observed 63 starts, all six IDs and all
three DJ returns, programme changes and midnight, with no detected silence of
three seconds or longer, no backup tone, and no browser or worker errors. Its
original failed result remains preserved: three legacy hard-ID timing failures
were accepted by the owner; one temporary request-status failure prompted the
bounded confirmation-window repair. See the detailed DJ-to-Auto repair report.

The follow-up repair leaves a queued request pending for up to ten seconds of
confirmed absence on the same engine, allowing the real rendered START callback
to arrive. Engine restarts still fail immediately; missing inventory cannot
prove request failure. Reappearance and confirmation clear the tracker. This
does not generate synthetic starts or change event timing on live stations.

## Pre-release validation

- Focused automation/event/scheduling interaction: 62 passed.
- Disposable PostgreSQL scheduling and event tests: 7 passed.
- JavaScript editor test: passed; four changed JavaScript files passed syntax checks.
- Broader service/simulation suite: 242 passed, including month-scale schedule
  simulations and a 370-day legacy-calendar comparison. This preceded the final
  calendar cadence adjustment described below.
- Integration: 40 passed, one optional navigation-retention diagnostic skipped,
  and the calendar gap recorded below failed. All other browser/control checks
  passed, including stream stop/start, offline browser, worker restart and Cue.
- Final worker/event/return/refresh suite after the calendar adjustment: 80 passed.
- Corrected calendar/event audio and six natural DJ-ending cases: 11 passed.
  Calendar offsets of 12, 14 and 16 seconds measured 0.00, 0.00 and 0.25 seconds
  without programme music, within the unchanged 250 ms limit.
- Live stress runner restoration/ownership guards: 4 passed; read-only live
  preflight found eight eligible music tracks on freo-demo and four on freo-demo-2.
- Final programme rehearsal passed all 301.0 seconds: 13 starts, both IDs, the DJ
  return, and 95 matching title checks; no recorded issues, silence or fallback
  tone. Maximum clock lag was 0.48 seconds. It finished at 05:51:57 UTC.
  Evidence is under `/tmp/freo-release-20260921/`.
- Release page/runner checks: 8 passed. Cache versions were advanced for the
  changed browser assets; this was the only application-file change after the
  passing final audio regressions and rehearsal source snapshots.

The first integration invocation selected a nonexistent test name and ran no
tests. Its corrected run is `integration-verified-selection`; the failed
selection log is retained separately under `integration`.

The integration suite exposed a 0.50-second calendar-boundary gap, despite all
six natural DJ-return cases passing at 0–50 ms. The normal two-second worker
cadence allowed the changed calendar queue to be refreshed after the current
short track ended. Calendar transitions now use a 250 ms polling interval during
the final five seconds before the transition and the five seconds after it.
The retained post-boundary window matters because the resolver then points to
the next future transition. Production and the isolated worker share the same
cadence function. The normal interval remains two seconds. Added verification
covers three calendar boundary alignments and expiry of the faster interval.

## Deployment preparation

The verified database/configuration backup is
`/var/backups/freo/station-release-20260921T051452Z`. PostgreSQL's custom-format
dump was successfully listed with `pg_restore`; station and Nginx configuration
copies and the previous commit are included. Media files are not modified by
this release. The installed database and repository both report migration head
`a71d25b609ef`; this repair requires no schema migration.

Before release, `main` and `origin/main` matched. Both managed stations were
running in AUTO. The enabled live station ID already uses SOFT timing.

Live preflight additionally found freo-demo broadcasting backup tone: its active
Calendar had nothing scheduled at that time, with no default playlist. Through
the existing authenticated default-playlist API, the already playable Playlist 1
was configured as fallback on both stations (playlist IDs 3 and 1 respectively).
Existing calendar entries and Simple selections were preserved. The API changes
and prior null defaults are recorded in `fallback-config.json`.
Both stations were subsequently observed playing managed music with backup tone
off before the engine deployment.

## Authorized five-hour live run

After deployment, commit, and push, the owner requested five hours of stress on
both actual live stations, explicitly noting that no listeners were present.
`scripts/stress-live-stations.py` uses authenticated application endpoints and
real browser mode controls, installed music and streams. It temporarily installs
quarter-hour Calendar sections and a reusable Block, then exercises mode changes,
DJ A/B natural returns, crossfades, REPEAT, PAUSE, CLEAR, manual Auto return,
queueing and configured carts. It navigates all scheduler/booth pages at mobile,
tablet and desktop widths and restarts the actual automation worker hourly.

Each stream is continuously decoded with a rolling audio buffer and silence
detection. Results include rendered-output/status agreement, browser title
matches, JavaScript failures, worker freshness, fallback tone, event completion,
browser resource trends, service memory and restart counts. Real station history
and audit records are retained. Original documents and mode are saved before
mutation; completion or failure restores owned documents and archives the test
Block. Operator edits detected during cleanup are preserved and reported.
`--restore` supports recovery after process interruption, and a separate systemd
stop hook will invoke it. Original empty-period Calendar behavior now has the
configured music fallback after restoration.

## Deployment result

Application/test release commit `f992699` was pushed to `origin/main`. Both
managed engine configurations were validated and installed. Web, automation,
ingest, microphone, statistics and central API services restarted, followed by
the managed engines one at a time. Both exposed the new return protocol and
resumed managed music.

The subsequent HTTP checks caught an Icecast runtime hang after its 05:53:24
configuration reload: the listener backlog filled and both status and new stream
requests timed out. The renderer had added explicit `public=0` fields to the two
existing mounts. This is an observed reload incident, not a proven upstream root
cause. Icecast was restarted, including recovery of the existing diagnostic and
managed engines. No application workaround or timing tolerance was added to hide
the incident.

The repeated live verification at 06:00 UTC passed all four health/readiness
checks, authenticated Booth/Calendar/Station Control/Events pages for both
stations, and exact delivery of all five changed static assets. Both engines
reported the new return protocol, fresh worker observations, and backup tone off.
Ten seconds of each actual MP3 stream decoded successfully; RMS was 0.06559 and
0.10729. The eight application/managed-engine units were active with zero automatic
restart loops before the Icecast recovery; recovery and final streaming checks
are recorded in the same release evidence directory.

The five-hour live stress run is the next action after this deployment record is
committed and pushed. Its evidence directory is `/tmp/freo-live-stress-20260921`
and its managed unit is `freo-live-stress-20260921.service`. The actual start and
expected finish will be written to that directory's `run.json` after setup.
