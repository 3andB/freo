# Station endurance findings: targeted repair plan

Scope: fix the defects exposed by the September 20 endurance run, preserve the
existing Station Control and DJ Booth workflows, and validate a fresh 48-hour
run. This is the original plan. The user subsequently requested a three-hour run
for this repair cycle; implementation and validation progress is recorded in
[the repair report](station-endurance-repair-2026-09-20.md).

## Evidence to preserve

Keep `/tmp/freo-system-validation/soak48-final` unchanged. It failed after
7:16:28 with 1,607 completed mode changes and 3,251 confirmed playback starts.
The failure was a statistics timestamp exception; teardown also reported six
uncaught Booth JavaScript errors. Browser resource counts grew with navigation.
Use separate directories and frozen source manifests for all new runs.

## 1. Repair silence-state transitions

Files: `app/services/statistics/collect.py`, `tests/test_statistics.py`.

Confirmed cause: normal observations save `silence_since: null`. On the first
silent observation, `old.get('silence_since', now)` returns the existing null,
which cannot be subtracted from `now`.

- First reproduce normal audio followed by silence against the real collector.
- Initialize the timestamp when missing or null, retain it during consecutive
  valid silent observations, and reset it when silence ends. Preserve the current
  RMS threshold and thirty-second incident delay.
- Test first-ever silence, sound-to-silence, 29/30-second boundaries, sustained
  silence, sound returning, a second silent episode, stale/missing observations,
  session reload, and station isolation. Verify incident opening/closing and
  continued collection, not just absence of exceptions.
- Include statistics regressions in the repeatable quick profile. Add a small
  isolated real-engine scenario that enters and leaves silence and confirms
  statistics continues. Deliberate silence belongs in that scenario, separately
  from the uninterrupted-audio endurance test.

Acceptance: the regression fails before the fix, passes afterward, and collection
continues across repeated sound/silence transitions without duplicate incidents.

## 2. Make Booth asynchronous work respect navigation

Files: `app/static/live.js`; related cue/microphone helpers and
`app/static/workspace.js` only where reproduction proves changes are necessary.
Regression coverage belongs with the browser/workspace tests.

Observed failure: `autoControls()` writes to a missing `auto-skip` button. The
refresh code checks request versions but not page disposal after JSON decoding;
its error handler can also try to update controls on a departed page.

- Create deterministic browser regressions: navigate away while status headers
  are pending, while the body is pending, and immediately before a delayed result
  or error is delivered. Also test leaving and returning to the Booth so an old
  response cannot update the new instance.
- Guard success, error, and action continuations using the originating page's
  lifecycle. Invalidate outstanding refresh versions on disposal and cancel
  page-owned delayed work. Scope DOM access to the originating Booth where useful.
- Audit the same post-await pattern in cue, picker, and microphone callbacks.
  Make evidence-backed local fixes; do not indiscriminately rewrite all handlers.
- Preserve actionable errors while the page is active. Abandoning the page must
  not retry an accepted mutation, stop the persistent monitor, or report a false
  connection failure on the destination page.

Acceptance: delayed success, failure and cancellation produce no uncaught error,
no update to the destination/new Booth instance, no duplicate command, and normal
controls after return. Existing disconnect/recovery and monitor tests still pass.

## 3. Reproduce and fix browser retention

The resource trend is evidence of a problem to investigate, not a proved cause.
Investigate after the navigation fix, since the same lifecycle defect may be
responsible for both symptoms.

- Use repeated Control/Booth navigation in one Chromium session with monitoring
  active. Compare warm-up, 100 round trips, and 300 round trips at the same page
  and idle state. Include an idle browser control to distinguish navigation growth.
- Capture heap snapshots, detached DOM retainers, active page work and listener
  counts. Use garbage collection only at diagnostic checkpoints in this focused
  test, not to keep the endurance run artificially healthy. Release test/CDP
  handles so instrumentation does not retain the objects being measured.
- Inspect retained parsed documents, closures, requests, timers, animation frames,
  observers, listeners and media resources. In particular, inspect the shared
  scope's never-settling aborted-fetch behavior and cleanup ownership; neither is
  yet established as the retaining cause.
- Fix the identified retaining references. If shared request cancellation must
  change, audit its callers and rerun their cancellation/recovery tests before
  accepting that broader fix. Preserve the single persistent monitor/audio graph.

Acceptance: departed page instances become collectable and retained DOM/listener
counts plateau after warm-up. Define and record a repeatable tolerance from the
focused reproduction before the long run; do not invent a permissive heap ceiling
or require noisy raw heap samples to stay numerically identical.

## 4. Improve failure detection in the endurance test

Files: `tests/soak_probe.py`, `tests/test_system_playout.py`, and evidence helpers
as needed.

- Read and persist browser errors during the run so uncaught JavaScript fails
  promptly instead of waiting for teardown. Preserve every drained console entry
  and retain the existing distinction between intentional network faults and
  uncaught JavaScript errors.
- Keep a bounded resource-growth check using the validated reproduction criteria;
  save diagnostic evidence at the first breach. Retain natural memory samples
  throughout the long run.
- Keep worker, browser, and audio failure sources distinct in the report. The
  harness calls statistics from its automation thread, so this failure alone
  does not prove production audio stopped.
- Verify failed runs preserve the original failure, final status and evidence,
  and stop their private processes. Keep all current audio and timing limits.

## 5. Validate in stages

1. Run each new failing reproduction before its fix, then rerun the targeted
   regression and relevant existing statistics/browser tests after the fix.
2. Run the expanded quick profile and complete integration profile, including
   engine, cues/events, microphone, broadcast, recovery and persistent monitoring.
   Run PostgreSQL collector checks if changes touch transactional behavior.
3. Run the focused 300-round-trip navigation stress test and a 30-minute real-audio
   endurance smoke. Require no unexpected errors, continued monitoring, bounded
   retained page resources, and the existing timing/audio limits.
4. Start one fresh 48-hour isolated run from the validated frozen source. Review
   saved evidence around one hour, eight hours (past the previous failure),
   twenty-four hours, and completion. A checkpoint is not a completed pass.
5. Update the validation report with before/after regressions, resource evidence,
   and the actual endurance outcome. Keep completed short-test results separate
   from pending or failed endurance results.

Done means the two confirmed errors have regression coverage, the retention
finding has a demonstrated resolution, the integration checks pass, and the new
48-hour run finishes within the existing limits. Deployment is separate from
this isolated repair and validation work.
