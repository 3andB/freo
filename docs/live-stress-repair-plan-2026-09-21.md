# Live stress repairs and two-hour retest

Status: corrections implemented; pre-deployment validation passed. The new live test has not
started. See `live-stress-repair-results-2026-09-21.md` for evidence.
Scope: polish the existing Scheduler, Station Control and DJ Booth. Preserve
operator behavior and the owner's acceptance of late IDs. Replace the outstanding
five-hour retest with a two-hour live run after corrections pass their checks.

## Evidence

The September 21 live run observed approximately 59 minutes 46 seconds before
failing at 07:02 UTC. It recorded 94 track starts, 28 DJ returns, 18 schedule-mode
changes and 240 UI navigations across freo-demo and freo-demo-2. It did not reach
the planned worker restart or complete its intended duration.

The 17 findings are observations, not 17 independent product defects. Originals,
actions, decoder logs and incident recordings remain in
`/tmp/freo-live-stress-20260921/`. Its `run.json` reports an initial restoration
failure; `restoration.json` records successful independent cleanup at 07:02:42.
At 12:32 UTC, fresh checks confirmed both streams playing, fresh worker status,
healthy HTTP endpoints and both stations in AUTO. Evidence is in
`/tmp/freo-status-20260921/`.

| Finding | Evidence and investigation |
| --- | --- |
| Runner stopped near one hour | One signed login cookie is reused indefinitely; application session lifetime is 3,600 seconds. The terminal exception is JSON parsing, consistent with an expired-session HTML response. Reproduce that response before declaring the cause confirmed. |
| Seven silence detections | Five follow PAUSE/CLEAR; two are near natural Deck A completion. Correlate decoded audio, source-file silence, engine callbacks, commands and worker state. Action proximity alone does not establish cause or excuse a gap. |
| Backup tone longer than five seconds | freo-demo-2 at 06:32:35, near natural DJ completion. Treat as a priority continuity defect until explained. |
| One microphone UI exception | `live_mic.js` writes to a missing element during navigation. Asynchronous completion after page disposal is the leading code-level explanation. |
| One failed LOAD and one DJ timeout | LOAD command 146 failed at 06:45; a later DJ session timed out. Check whether these share a cause, including whether the expected request actually started. |
| One stale worker observation; two metadata mismatches | Correlate worker latency, engine identity and decision IDs. Distinguish a real stale display from non-atomic sampling across a track transition. |
| One HTTP 409 deck conflict | May be correct protection against an outdated deck snapshot. Verify the protected command had no unintended effect; do not remove the guard. |
| One interrupted timed event | Event 73 failed with `interrupted_by_mode_change`. Attribute to an intentional test action only if its action history proves that; independently test normal ID completion. |

## 1. Repair the runner and its evidence

Primary files: `scripts/stress-live-stations.py`,
`tests/test_live_stress_runner.py`.

- Reproduce cookie expiry using controlled time in a test. Renew the runner's
  authenticated session before expiry for both API requests and browser tabs,
  without extending the application's session policy. Verify real requests remain
  authenticated across the one-hour boundary during the eventual live run.
- Detect redirects, authentication failures and unexpected content types before
  parsing JSON. Record useful status and endpoint details without cookies or
  credentials. Avoid replaying a mutation whose outcome is unknown; reconcile
  command status and preserve its nonce where retry is appropriate.
- Keep the original failure even if recovery also fails. Report test outcome and
  cleanup outcome separately, including successful independent stop-hook cleanup.
  Test expiry during recovery, repeated cleanup and protection of operator edits.
- Confirm accepted deck commands complete and their intended request actually
  plays before counting a scenario as exercised. On a 409, capture a fresh
  snapshot and record the conflict; never silently substitute another deck item.
- Record full silence intervals, engine/worker snapshots, command/request IDs and
  scenario context. Track recurrence and duration of stale status and fallback,
  rather than suppressing all later occurrences under one deduplication key.
- Separate browser navigation delays from the cadence of audio and station
  observation. Add a heartbeat and an independent stale-run check so a stopped
  test cannot appear to be making progress. Record explicit passed, failed and
  incomplete outcomes and per-scenario coverage.

Gate: focused runner tests pass for expiry, unexpected responses, ambiguous
mutation results, scenario accounting, early exit and both restoration paths.

## 2. Fix microphone-page lifecycle handling

Primary file: `app/static/live_mic.js`; reuse
`tests/test_workspace_lifecycle_browser.py` and `tests/test_live_mic_browser.py`.

Reproduce a delayed status response completing after departure from the Booth,
including departure followed by mounting a new Booth. Guard asynchronous success,
error and finalization paths against disposed pages; keep element references
scoped to their own page. Preserve microphone disconnect, track release and
return-to-AUTO behavior. Cover delayed device enumeration and connection work as
well as polling. Update the asset version when deploying the fix.

Gate: repeated navigation and delayed success/error responses produce no uncaught
errors, stale painting, retained microphone resources or duplicate disconnects.

## 3. Resolve playback, command and metadata findings

Use existing engine/system harnesses and focused deck, queue, worker and event
tests. Reproduce before changing production behavior wherever evidence permits.

1. Natural EOF: reproduce both affected real-track endings and synthetic
   continuous-audio equivalents on both decks. Follow return preparation,
   replacement readiness, EOF, actual output and AUTO adoption. Fix the measured
   failure without bypassing carts, microphone, events or AUTO_CUE precedence.
2. PAUSE/CLEAR: distinguish documented intentional stop grace from additional
   delay, silence authored into the song and missing replacement audio. Preserve
   current operator semantics; fix excess recovery delay or stranded output.
   Record any intentional gap with the exact triggering action and measured
   duration. Do not blanket-exempt every gap around an operator action.
3. LOAD/timeout: trace command 146 and the subsequent timed-out session. Verify
   engine acknowledgments, request identities and observed start. Prevent the
   runner from waiting for EOF on a song that never loaded. Repair any product
   failure separately from scenario bookkeeping.
4. Worker/metadata: reproduce slow or missing observations and transition races.
   Compare timestamps and stable request IDs, including a confirming sample where
   necessary. Fix stale UI or worker behavior when confirmed; do not relax
   freshness thresholds to conceal it.
5. Events/conflicts: preserve concurrency rejection and event interruption policy.
   Add protected normal event windows so successful IDs are measured independently
   from deliberate interruptions. Report late IDs as advisory, as requested;
   unexplained missed, failed or duplicated IDs remain failures.

Gate: targeted engine, worker, browser and PostgreSQL concurrency regressions pass;
each original finding has a documented cause, correction or evidence-backed
expected-behavior classification. Retain the existing deterministic natural-EOF
target of at most 250 ms without backup tone; do not weaken silence detectors.

## 4. Validate and release the corrections

Run a short integrated rehearsal after focused tests, with the corrected runner,
both stations, audio decoding, navigation and restoration. Simulate expiry and
failure paths before committing to another long run. Start the release only when
the above gates pass. Record the exact passing commit, commit and push the
corrections, deploy/restart affected services, and verify health, loaded assets,
engine protocol where changed, worker freshness and actual decoded stream audio.

Keep the existing backup and rollback process. Freeze code and configuration for
the endurance measurement; a material correction during the run requires a new
run and a fresh two-hour clock. Preserve the first failed run's evidence.

## 5. Two-hour live stress run

Use both existing live stations and approved music. Snapshot programming before
temporary fixtures, preserve media and operator edits, and retain independent
restoration. Use a new timestamped output directory and managed service. Start
the 7,200-second clock only when both audio probes and browser monitoring work;
setup, deployment and cleanup are additional time.

| Elapsed time | Exercise |
| --- | --- |
| 0–20 minutes | Automatic music, actual Calendar/Block boundaries, Simple/Blocks/Calendar switches, protected timed IDs and UI navigation. |
| 20–60 minutes | Both decks: natural endings, A/B transitions, repeat, manual AUTO return, PAUSE/CLEAR, queued music and available carts. Controlled worker restart near minute 45. |
| 60–100 minutes | Repeat mixed station activity across the real session-expiry boundary; verify API and browser authentication. Second controlled worker restart near minute 90. |
| 100–120 minutes | Finish missing scenario repetitions, protected IDs and schedule boundaries, then sustained AUTO playback and recovery observation. |

Navigation, decoded audio, metadata comparison and resource sampling continue
throughout. Stagger station actions. Restart only the automation worker for the
planned recovery cases, with audio observations still active. Keep a bounded
worker-freshness recovery allowance; never suppress audio failures during it.

Before launch, budget actual track durations into the scenario schedule. Require
each station to complete both-deck natural EOF at least twice, each other listed
DJ/control case at least once, all three scheduling modes, actual Calendar and
Block boundaries, and at least one normal hard and one normal soft timed event.
Use isolated, removable event fixtures if existing events cannot supply that
coverage. Verify all temporary fixture cleanup. Exercise carts where configured;
report unavailable capabilities explicitly. Physical microphone hardware is not
certified by this run; its identified page-lifecycle defect is covered by browser
regressions. Do not report unexecuted scenarios as passing.

Stop issuing stress actions and restore programming if an audio outage exceeds
the existing 90-second cutoff, a decoder dies, control cannot be recovered, or an
operator edit conflicts with owned fixtures. A stopped run is incomplete/failed,
even if cleanup succeeds. Check durable progress and findings at 15, 30, 60, 90
and 120 minutes; monitor the service heartbeat independently between checkpoints.

Acceptance requires the complete two-hour observation period and required
coverage; no unexplained silence of three seconds or more, fallback lasting over
five seconds, stream loss, failed commands, missed DJ returns, uncaught UI errors,
persistent metadata disagreement or unexplained event failure. Any shorter
reproduced handoff defect remains tracked rather than hidden by the live detector
threshold. Intentional behavior must be evidenced and reported separately.
There must be no unplanned service restart. Review browser/service resource trends
for sustained growth; two hours cannot prove indefinite stability.

Afterward, verify restored programming, healthy services and audible output on
both stations. Publish the actual duration, commit, scenario counts, classified
findings, resource trends and restoration result. Claim a pass only after both
the run and this final verification satisfy the gates.
