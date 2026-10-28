# Endurance repair and three-hour rerun — September 20, 2026

The requested rerun duration is three hours (10,800 seconds), replacing the
planned 48-hour validation for this round. It remains an isolated test with
generated audio, disposable databases, private Icecast/Liquidsoap and Chromium.
No installation service was restarted or live station data used as a fixture.

## Repairs

- Statistics silence detection now initializes an existing null timestamp when
  silence begins. The RMS threshold and thirty-second incident delay are unchanged.
  Three new regression variants reproduced the crash before the fix. The full
  statistics suite then passed all fifteen cases, including incident opening,
  closing, repeated silence, stale observations and persisted state.
- Booth refreshes now discard responses and errors after their page is disposed.
  The same lifecycle checks protect late action and picker results, and the cue
  editor abandons departed-page updates. Search timers/versions are invalidated
  on disposal. The shared workspace and persistent monitor architecture are
  unchanged. Static asset versions were updated for the affected page scripts.
- The endurance probe now persists browser console entries and checks uncaught
  JavaScript errors every five seconds, instead of discovering them only during
  teardown. It also samples Chromium process-tree RSS in addition to JS heap,
  DOM/listener counts, engine and worker memory. Summed RSS may include shared
  pages; it is a trend metric, not unique physical-memory accounting.

## Reproduction and memory investigation

Both delayed successful and failed response bodies reproduced the exact missing
`auto-skip` error against the old Booth code. A thirty-navigation diagnostic also
reproduced it without injected responses. Evidence:
`/tmp/freo-repair-browser-before.xml` and `/tmp/freo-repair-nav-before`.

The initial memory diagnostic changed the interpretation of the earlier resource
growth: after explicit diagnostic garbage collection, retained resources plateaued
at about three documents, eighty-six listeners and 1,910 DOM nodes. A subsequent
hundred-navigation run remained at three documents, eighty-six listeners and
1,913 nodes. Raw pre-collection counts were higher. JS heap grew from about 1.3 MB
to 1.8 MB over those hundred cycles; these observations do not establish that all
memory is bounded indefinitely.

This has not reproduced a retained-page/listener leak, so no speculative shared
workspace rewrite was made. The longer diagnostic checks collection after warm-up
with tolerances of two documents, twenty listeners and one thousand DOM nodes
above its warm-up baseline. Diagnostic collection is limited to that test; the
three-hour endurance test does not force garbage collection or periodically reload
the browser to hide resource growth.

## Validation and rerun status

- Completed statistics suite: `/tmp/freo-repair-statistics.xml` (15 passed).
- Browser regressions and initial hundred-navigation diagnostic:
  `/tmp/freo-repair-browser-after.xml` and `/tmp/freo-repair-nav-after`:
  22 passed, one optional screenshot skipped, completed in 8:18.
- Final frozen-source preflight and three-hour run:
  `/tmp/freo-repair-20260920`.

The frozen preflight completed with 29 passes and the one navigation-selector
failure described below. Both connected real-audio journeys and the short
endurance test passed. All four delayed-body cases (success/error, with/without
returning to the Booth) and accepted cue-write recovery passed.

The first Chromium RSS sample incorrectly read zero because the driver launches
its browser from a secondary thread. The sampler now enumerates children of all
driver/browser threads. It was verified against the running private diagnostic
browser; `/tmp/freo-repair-20260920/browser-rss-proof.json` contains the nonzero
measurement. The test now rejects an unavailable browser-memory observation.

The original gated launcher records `pipeline.json`. Its successor records
`pipeline2.json` after correcting the navigation diagnostic's monitor selector:
the first attempt targeted a hidden player button and failed before any cycles.
The visible station monitor button is the established UI control used by the
existing monitoring tests. This was a test setup failure, not a playback failure.

The launcher waits for the existing browser
checks, then runs the latest delayed-response regressions (including leaving and
returning to a new Booth instance), accepted cue-write recovery, 300 navigation
round trips with monitoring, cue/microphone/statistics browser checks, and the
real-engine connected journeys and short endurance test. The three-hour run starts
only if those checks pass. The successor requires all other preflight cases to
pass and reruns the corrected navigation diagnostic in `navigation/`; an unexpected
failure stops the launch. It also checks the application source has not changed
since the preflight snapshot.

The first corrected 300-cycle attempt (`navigation/`) ended with Python signal 11
while emitting pytest's four-minute faulthandler stack dump. It recorded 150 cycles
but no completed test result; this is not a pass. The exact interpreter-crash cause
has not been established. Its private Chromium tree was stopped. The runner's
diagnostic timer now allows for the requested navigation workload; application,
audio and per-operation deadlines are unchanged. `pipeline3.json` tracks the
retry in `navigation-retry/` and gates the three-hour launch on its success.

## Final preflight outcome and launch

The corrected navigation diagnostic **passed all 300 round trips**, including
continuous monitor playback and retained-resource assertions. It finished at
13:10:49 UTC; evidence is `navigation-retry/results.xml`. Final retained counts
were two documents, seventy-four listeners and 1,804 DOM nodes, versus approximately
three documents, eighty-six listeners and 1,900 nodes after warm-up. The final
sampled JS heap was 2.57 MB. No uncaught browser errors were recorded. This resolves
the retained-page/listener concern in the focused reproduction; it does not prove
all browser memory remains bounded under every workload.

Together, the preflight and corrected diagnostic have passing outcomes for all
thirty selected cases. This is combined coverage across reruns, not a claim that
the initial preflight session passed. The unrelated optional screenshot skip was
in the earlier twenty-two-pass browser run.

The requested **three-hour endurance run launched September 20 at 13:10:49 UTC**
under `/tmp/freo-repair-20260920/soak3h`. It **passed**, completing at 16:11:38 UTC.
Runner PID at launch: 1600656; pytest PID: 1600658. The test uses natural browser
garbage collection and retains continuous audio/error/timing/resource evidence.
The application code matches the validated preflight snapshot; the corrected
memory sampler and diagnostic timer are included in the new frozen source.
At 13:12 UTC both test processes were confirmed alive. Fresh samples showed three
mode switches, eight confirmed playback starts, advancing browser audio, valid
Chromium RSS observations, no detected three-second silence and no engine clock
lag. These are initial observations, not a three-hour pass.

## Completed three-hour result

Reviewed at 16:24 UTC. Runner exit code was zero and JUnit reports one passed test,
zero failures, zero errors and zero skips. Total session time was 3:00:46; the
measured endurance interval was 10,800.61 seconds.

- 667 completed scheduling-mode changes, covering all six directed mode pairs.
- 1,343 confirmed playback starts; 9,521 probe samples.
- No detected three-second silent intervals and no browser monitor stall exceeding
  the ten-second limit. The monitor remained playing throughout the sampled run.
- No uncaught browser JavaScript errors or recorded worker errors. The previously
  observed statistics and departed-Booth exceptions did not recur.
- Maximum engine clock lag: 0.32 seconds.
- Maximum mode handoff: 8.33 seconds (ten-second limit); displayed-mode convergence:
  11.82 seconds (fifteen-second limit).

Memory remains an observation to follow up, not an unconditional stability claim.
Natural browser JS heap samples grew from 2.93 MB to 9.95 MB; raw DOM counts grew
from 1,437 to 197,757 nodes, and listener counts from 69 to 7,621. The separate
300-cycle diagnostic demonstrated that departed page/listener resources were
collectable, but this run did not force GC or establish a long-term plateau.
Summed Chromium RSS started around 1.09 GiB, peaked around 1.43 GiB and ended around
1.22 GiB; this sum can double-count shared memory. Engine RSS stayed around
151–155 MiB, while the combined test worker/web process grew from about 125 MiB
to 153 MiB. Longer operation would be needed to establish bounded memory usage.

Final artifacts: `soak3h/results.xml`, `soak3h/run.json`, and
`soak3h/runtime/test_system_endurance0/` (metrics, full resource history, browser
console, worker errors, screenshots and rolling audio). The three-hour test is
finished; no replacement endurance run was launched during this review.

Check `preflight/run.json` and `soak3h/run.json` for actual outcomes. While running,
the endurance measurements are under
`soak3h/runtime/test_system_endurance0/soak-result.json`. Logs, screenshots, database
backups and frozen source hashes remain in the evidence directories. A launched
or running job is not a pass. All existing audio, freshness and transition timing
limits remain in effect. The earlier failed run remains preserved at
`/tmp/freo-system-validation/soak48-final`.
