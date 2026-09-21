# Live stress corrections — September 21, 2026

Status: corrections and pre-deployment validation completed. The two-hour live
test has not started. Plan: `live-stress-repair-plan-2026-09-21.md`.

## Findings and corrections

- The original live run stopped at approximately one hour. A controlled-time
  regression confirms that its original signed cookie becomes invalid under the
  application's existing 3,600-second session policy. The runner now renews its
  API/browser credentials before expiry, rejects redirects/non-JSON responses and
  never blindly retries an uncertain mutation. Application login policy is unchanged.
- Delayed microphone status replies could paint after workspace disposal. The
  microphone UI now uses page-scoped elements and disposal checks across polling,
  device enumeration, connection and error paths. Four delayed success/error
  navigation regressions passed, including departure followed by a new Booth.
- The live engine logs showed clock lag of 1–2.84 seconds near the first natural
  ending and repeated 404 decoding attempts from the disconnected microphone
  input. The input now starts only for a prepared session, runs on a dedicated
  clock, and stops after its lease expires. The real WebRTC/audio integration
  passed. This removes demonstrated idle work; it does not prove the sole cause
  of every historical clock stall.
- A new real-engine regression reproduces loss of the prepared EOF handoff during
  a four-second worker delay. The original two-second lease fails that test.
  Its replacement is five seconds, still scoped to the exact deck, outgoing
  request and prepared replacement. Manual actions revoke it, and a longer
  worker absence must still expire it. The corrected delay and worker-restart
  cases each measured a 50 ms audio gap; the long-absence expiry case passed.
  This is a handoff permission window, not
  an increase to the silence or fallback acceptance thresholds.
- After PAUSE/CLEAR or an empty deck, switching to AUTO no longer adds a
  three-second fade from an inaudible source. The existing two-second worker
  stop grace remains. Isolated measured gaps were 2.30 seconds for CLEAR and
  2.15 seconds for PAUSE. Audible manual DJ-to-AUTO transitions retain their fade.
- Command 146 was rejected because its expected deck changed before execution.
  The runner nevertheless waited for that failed LOAD to finish playing, producing
  a misleading later DJ timeout. It now waits for a fresh empty Booth after mode
  entry, reconciles the accepted command by its nonce, and verifies the intended
  request appears before starting the scenario. Repeat playback is verified too.
  Concurrency guards are preserved.
- Event 73 was interrupted by a mode change; the audit contains the runner's
  scheduling transition at 07:00:23. The new run protects due events and installs
  owned hard/soft event fixtures. Late IDs remain advisory. Where a station lacks
  approved short ID audio, existing approved music exercises the event path and
  is explicitly reported as such.
- The old run did not retain enough synchronized state to attribute both metadata
  discrepancies conclusively. The runner now records observation snapshots and
  confirms a mismatch against a still-stable rendered request, separately from
  a stale worker observation. Recurrent outages have distinct episodes and
  recovery durations. These cases remain subject to the live retest.

Original evidence: `/tmp/freo-live-stress-20260921/`. New evidence:
`/tmp/freo-live-repair-20260921/`. Source scans found no silence above 200 ms in
one affected song and approximately 1.08 seconds at the other song's tail; neither
explains the observed extended fallback by itself.

## Retest protections and coverage

The corrected runner preserves the original failure even if recovery also fails.
An independent restoration hook updates cleanup status without erasing the test
outcome; an interrupted run cannot be reported as still running. A systemd
watchdog will supervise durable progress. Both streams must produce decoded audio
before the observation clock starts, and fresh AUTO playback plus newly decoded
stream audio are checked after restoration.

The full run uses 7,200 seconds. It begins with protected timed events and a Block
boundary, then dwells across a Calendar boundary before mixed station activity.
DJ exercises use the two shortest eligible normal music tracks to fit repeated
both-deck EOF coverage into two hours. The automation worker restarts near
minutes 45 and 90. New stress actions stop during the final ten minutes while
existing sessions finish and AUTO playback is observed. Actual completed coverage
is required, not just elapsed time.

Temporary events are disabled, the temporary Block archived and owned programming
restored afterward. Existing media and operator edits are preserved. Normal
airplay/event history is retained. No successful two-hour result is claimed here.


## Additional race found during validation

The ordinary Deck A rerun preserved audio (END to next START approximately 40 ms)
while the database stayed in DJ mode and the automatic playlist continued. The
worker read DJ mode immediately before rendered EOF, then unconditionally wrote
that stale mode back after the engine had returned to AUTO. This erased the
handoff completion identity and left the station in DJ standby. The mode adapter
now sends a mode change only when its observation differs from current operator
intent. The next observation can adopt an engine-owned return normally.

A deterministic regression exercises EOF between the snapshot and the would-be
mode write, verifies the completion identity survives, and requires one persisted
AUTO return. Seventy worker/deck/return unit checks passed after this correction.
Five final-source real-engine regressions also passed: both ordinary deck endings,
worker restart, and both Cue/event/restart variants. The integrated rehearsal is
recorded below.

## Validation record

- Broader service/simulation suite: 254 passed, including month-scale scheduling
  simulations. This preceded the final mode adapter correction.
- Workspace/microphone browser and runner suite: 23 passed, one optional retained
  resource diagnostic skipped. Final rendered-request runner checks: 13 passed.
- Disposable PostgreSQL scheduling concurrency: four passed.
- Final microphone lifecycle/real audio suite: nine passed, including off-air
  expiry preserving DJ and live disconnection returning to AUTO.
- Initial audio/engine batch: 18 passed, one Cue/event case failed. A diagnostic
  rerun passed. Its fixture now verifies setup finishes while the initial song is
  on air, uses a ten-second initial song instead of five, and retains the event
  ordering and replay assertions. Both variants subsequently passed in closure.
- Later engine/microphone batch: 48 passed, one setup error. Private Icecast exited
  before the first ordinary Deck A case reached playback. Captured stdout did not
  establish why. The harness now preserves native Icecast error logs and exit
  codes. This is not presented as a clean first-pass batch.
- Final-source mode adapter regressions: 70 passed. Final-source audio confirmation:
  five passed in 177 seconds (`mode-race-audio/`).
- Closure rerun: three passed; ordinary Deck A exposed the mode race above.
  The failed evidence is preserved, and the correction has a dedicated regression.

Evidence is under `/tmp/freo-live-repair-20260921/`. The verified pre-deployment
backup is `/var/backups/freo/live-repair-20260921T125852Z`. Final-source audio,
rehearsal, deployment and live test outcomes will be recorded when completed.

Final integrated programme rehearsal passed on the corrected source: 300 seconds
of observation, two completed timed events, one DJ takeover and three programme
rotations. No findings, detected silence, fallback or engine clock lag. Evidence:
`programme/run.json` and `programme/runtime/test_three_hour_programme0/soak-result.json`.
Deployment and the separate two-hour live run remain pending.
