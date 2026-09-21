# Station Control / DJ Booth validation — September 20, 2026

Scope: harden existing workflows and add repeatable integration/endurance tests.
No live station schedule, playback mode, database record, engine configuration,
or system service was used as a mutable test fixture.

## Confirmed findings and changes

1. **Station Control could stop refreshing indefinitely after a stalled HTTP
   request.** A new Chromium test failed on the existing implementation. Requests
   now have a six-second deadline; the page reports the problem and resumes
   polling. Lost write responses do not trigger automatic resubmission. Both the
   stalled-read and lost-broadcast-response/double-click regressions pass.
2. **The previous 48-hour soak did not pass.** It failed after 7:27:45. Its final
   target has START and END evidence before the failed instantaneous current-ID
   check. The engine log also reports more than forty seconds of clock lag. The
   assertion now accepts an ended target only with its real END callback. New
   endurance coverage independently checks decoded audio, fallback tone, decoder
   progress, engine clock lag and UI convergence. The old log cannot establish
   whether its actual output was uninterrupted.
3. **Two migration fixtures had become obsolete.** One reapplied later schema
   changes to an already-current schema; it now runs only its intended data
   migration. The PostgreSQL backfill test seeded an old schema using today's
   ORM columns; it now reflects that historical table. The latter error caused
   subsequent PostgreSQL cases to run against an incomplete schema. All twelve
   PostgreSQL checks passed after correcting the fixture.
4. **Two workspace browser tests expected an older Calendar UI.** They now
   verify autosave persistence after reload and grouped weekly events. The
   persistence check retains the imported legacy schedule instead of assuming
   the added song is the only calendar entry. Product behavior was retained.

The first connected endurance smoke run reached all six directed mode changes
without detected silence or clock lag, then failed because the test navigated
again before destination scripts finished loading. The test now waits for the
existing navigation completion indication. This was an automation synchronization
error, not evidence of an audio failure.

The next smoke attempt exposed WAV output buffering in the probe: decoded audio
was arriving, but file writes were buffered long enough to trip the ten-second
stall alarm. A separate real FFmpeg comparison reproduced this (buffered output:
zero visible bytes after twelve seconds; flushed output: 194,350 bytes with a
0.01-second write age). The probe now flushes each packet; the stall deadline is
unchanged. Evidence: `/tmp/freo-system-validation/decoder-flush-proof.json`.

## Completed checks

| Run | Result | Evidence |
| --- | --- | --- |
| Final frozen-source quick profile, including four-week scheduling simulations | 194 passed, zero skips | `/tmp/freo-system-validation/quick-final/results.xml` |
| PostgreSQL concurrency, station isolation and migrations | 12 passed | `/tmp/freo-system-validation/postgres2.xml` |
| Stalled status and lost broadcast response / double-click | 2 passed | `/tmp/freo-system-validation/request-recovery.xml` |
| Existing Station Control, broadcast and scheduler browser workflows plus initial recovery regression | 6 passed | `/tmp/freo-system-validation/control-browser.xml` |
| Event, control, booth state and live-assist regressions after fixture repair | 53 passed | `/tmp/freo-system-validation/regressions.xml` |
| Initial connected journeys | 2 passed; separate smoke failure described above | `/tmp/freo-system-validation/system4.xml` |
| Remaining integration checks and corrected calendar/endurance regressions | 40 passed, zero skips | `/tmp/freo-system-validation/remaining-final/results.xml` |
| Combined latest integration outcomes, including corrected reruns | 94 passed, one optional screenshot skipped; no missing cases | `/tmp/freo-system-validation/integration-coverage.json` |
| Final monitor-enabled endurance smoke, requested duration 180 seconds | Passed; twelve mode switches covering all six directions | `/tmp/freo-system-validation/monitor-smoke/results.xml` |

These totals overlap and must not be added together. The quick profile includes
the service regressions and the expanded simulations. Both spring and autumn
windows cover the Denver and London clock changes. The simulations advance time
through the resolver and selector; they do not claim real-time audio endurance.
Across the quick profile, PostgreSQL checks, and latest integration outcomes,
300 distinct pytest cases passed. This is combined coverage across runs, not a
single uninterrupted suite execution. Ten JavaScript editor tests also passed.

The connected journeys verified UI scheduling changes against real worker and
Liquidsoap events, persistent stream monitoring across navigation, deck playback,
carts, automatic return, browser disconnect recovery, worker restart and broadcast
OFF/ON. The recorded deck stream measured the expected 880 Hz tone. A second
journey verified browser cue reordering, unattended AUTO_CUE progression, a timed
event completing during the cue, and progression after a worker restart.

JavaScript editor tests, Station Control syntax, Python compilation and
`git diff --check` passed during implementation.

## Broader integration and endurance

The frozen-source broader suite is under
`/tmp/freo-system-validation/integration-final2`. The command session terminated
with signal 15 before pytest could write final JUnit results. Its captured compact
progress, matched to the frozen collection, records 54 passes, three failures
(the recording probe and the two obsolete workspace checks described above),
and one optional screenshot skip. That reconstruction is retained as
`partial-results.json`; it is not a completed suite result. The earlier
`integration-final` launch was deliberately interrupted to shorten fixture paths
before existing Unix sockets exceeded the Linux path limit.

The broader run includes the connected journeys, browser workflows, real engine
crossfades and deck controls, cue/event behavior, microphone simulation, loudness,
the 65-second scheduling soak, and a two-minute connected endurance smoke test.
The remaining checks and corrected failures completed from a new frozen copy
under `/tmp/freo-system-validation/remaining-final`: all forty passed. These include
real engine/deck controls, broadcast fallback, microphone simulation and browser
permissions, loudness normalization, autosave recovery, the corrected calendar
workflow, the legacy scheduling soak, and the connected endurance smoke test.
The grouped-event correction also passed its targeted rerun. The combined coverage
file maps all ninety-five integration cases to their latest evidence: ninety-four
passed and one optional screenshot case was skipped. The runner now writes
`case-results.jsonl` after each case, so completed outcomes survive an interrupted
session.

The final monitor-enabled smoke ran for 188.28 seconds including its last handoff.
The browser monitor advanced continuously to 188.36 seconds. Twelve transitions
covered all six directed mode pairs, with twenty-seven confirmed starts. Maximum
handoff time was 5.61 seconds and maximum displayed-mode convergence was 7.84
seconds. The decoder detected no three-second silence and the engine reported no
clock lag. Detailed metrics are at
`/tmp/freo-system-validation/monitor-smoke/runtime/test_system_endurance0/soak-result.json`.

After that pass, the **48-hour run started September 20 at 03:03:52 UTC** under
`/tmp/freo-system-validation/soak48-final`. **It failed September 20 at 10:20:23
UTC, after 7:16:28 total runtime.** This was confirmed from final JUnit, runner
status and saved telemetry at 11:45 UTC. It is no longer running and has not been
restarted. Logs, frozen source, source hashes, and per-case results remain there.

The run recorded 1,607 completed mode changes and 3,251 confirmed playback starts.
There were no detected three-second silent intervals; maximum reported engine
clock lag was 2.27 seconds. Maximum successful handoff took 8.99 seconds and UI
convergence took 12.90 seconds. These observations do not override the failure.

New findings:

1. Statistics collection raised `TypeError` in `app/services/statistics/collect.py`
   when subtracting a saved null `silence_since` from the current time. The code
   stores null during non-silent observations, then uses `dict.get(key, now)` on a
   subsequent silent observation; the default does not replace an existing null.
   The harness recorded this worker error and failed the next handoff check.
2. The browser console contains six uncaught DJ Booth errors from `autoControls`
   setting `disabled` on a missing `auto-skip` element. This is consistent with an
   asynchronous update surviving navigation; its exact lifecycle cause still
   needs a focused reproduction. Teardown correctly reported these errors.
3. Browser DOM/document/listener counts grew with repeated navigation: approximately
   1,440 to 479,139 nodes and 69 to 18,267 listeners. Sampled JS heap grew from
   about 2.9 MB to 15.7 MB. This is a retention concern requiring investigation,
   not yet a confirmed leak diagnosis or proof of its cause.

These newly exposed issues remain unfixed as of this status review. The earlier
short-test passes remain valid; the long-duration result is a failure requiring
targeted fixes, regression checks, and a fresh endurance run.

Subsequent repairs and the user-requested three-hour rerun are tracked in
[the endurance repair report](station-endurance-repair-2026-09-20.md). The failure
above remains the historical outcome of this frozen-source run.

## How to repeat

See [Station system testing](station-system-testing.md). The runner freezes the
edited source and records hashes, logs and JUnit results. Connected tests preserve
screenshots, HTML, console output, engine events and a consistent SQLite backup.
The endurance probe retains rolling audio and timing/resource samples.

The combined harness uses a restartable worker thread and SQLite WAL; it adapts
system service management to private processes. It does not exercise production
systemd, Nginx/TLS or physical microphone hardware. PostgreSQL behavior and the
microphone gateway are covered by separate tests. Passing a short run is not a
48-hour pass or a guarantee of leak-free operation.
