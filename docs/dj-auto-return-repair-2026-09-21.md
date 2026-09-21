# DJ-to-Auto repair — September 21, 2026

The repair prepares one eligible scheduled request during the last eight seconds
of an aired DJ track. The worker renews a two-second engine lease identifying the
outgoing deck/request and the replacement. Liquidsoap performs the handoff at
rendered EOF, checks the actual replacement identity, and reports completion for
the worker to adopt. The finished source does not receive an unnecessary fade;
an audible outgoing source retains the normal manual AUTO crossfade.

An estimated duration reaching zero does not revoke a prepared return while the
same deck is still audible. A brief loss of request identity at rendered EOF
also leaves the last lease intact to complete or expire, without renewing it.
This prevents a worker observation from cancelling the handoff on its final frame.

Deck mutations revoke the lease. Repeat, AUTO_CUE, other audible decks, carts,
microphone activity and due events retain their existing precedence. A worker
outage expires the lease. Completion adoption checks station, engine and DJ
session identity and is idempotent. Older running engines retain the previous
behavior until their configuration is refreshed and they are restarted.
Repeated requests for the current mode do not create a new mode-change audit
entry, so a duplicate DJ click cannot invalidate the current session's return.

The worker treats an already loaded but inaudible Auto request as prepared audio,
not as an empty queue. A schedule edit discards stale prepared audio through an
engine operation that refuses to remove it after it becomes audible. The existing
programming-refresh checkpoint logic restores the unconsumed selection cursor.

Near calendar/event boundaries, lookahead suppression now allows one successor
when automatic output is empty or its current track is within five seconds of
ending. Event handling still runs first. The silence detector and backup thresholds
were not relaxed.

## Evidence so far

- Original short natural-EOF regression: 2.78 seconds without programme music.
  First repaired result: 0.08 seconds. Both decks and calendar-window variants
  passed the 250 ms audio acceptance threshold.
- Original calendar starvation regression: 8.25 seconds without programme audio.
  Repaired calendar/hard-ID/soft-ID results: 0.00 / 0.15 / 0.00 seconds.
- Initial logic/compatibility suite: 98 passed. Additional eligibility and
  identity checks: 25 passed; standby preservation separately checked.
- UI, cue/worker recovery and microphone suite: 36 passed.
- A restart regression exposed redundant preparation of an already loaded
  request. The corrected restart and schedule-edit cases, natural handoff and
  existing programming-refresh checks subsequently passed all 15 checks.

These are intermediate results, not a completed endurance pass. Exact frozen
source, logs, recordings and results are retained under `/tmp/freo-dj-return/`:
`baseline`, `repair1`, `boundary-baseline`, `boundary-checks`, `unit-checks`,
`unit-final`, `engine-checks`, `workspace-checks`, `prepared-checks`,
`final-regressions`, and `programme-smoke`. `guard-checks` retains the earlier
restart failure as well as seven passing cases; it is not a final clean run.

Final regressions cover both deck EOFs, calendar boundaries, CLEAR, REPEAT,
lease expiry, worker restart, schedule edits, hard/soft event windows, session
replay protection and queue refresh. Test audio distinguishes the 400 Hz backup
tone from scheduled music; backup audio cannot count as continuity.

The live installation has not been restarted or deployed. After the final
regressions and five-minute rehearsal pass, repeat the isolated three-hour
programme scenario and retain its separate result.

## Additional regression findings and resolution

The early broad engine run had 28 passes and one cue-to-schedule transition
failure. Both variants of that transition passed in `switch-checks` after the
prepared-current cleanup correction. That rerun then exposed a separate 4-second
natural-return gap: preparation was cancelled when duration metadata reached
zero just before rendered EOF. The repair now keeps the lease governed by the
actual engine boundary. `eof-timing-checks` adds deliberately underestimated
durations on both decks and repeats the handoff/recovery audio checks.

`final-regressions` completed 50 checks successfully before the final-frame
hardening above. `cue-prepared-check` separately confirmed that enabling AUTO_CUE
discards an already loaded automatic replacement and leaves the cue sequence in
control. The final-frame observation guard also passed its focused unit check.

The first repaired music rehearsal completed all 300 seconds, both IDs, its DJ
takeover and 85 matching now-playing checks, with no silence or fallback tone.
It recorded 7.9 seconds of maximum engine clock lag while several independent
test engines were running. This passed the existing ten-second ceiling, but the
rehearsal will be repeated alone before starting the new endurance run.

The timing suite passed both ordinary decks, both calendar-window decks, both
underestimated-duration decks and worker recovery at 0–50 ms of measured audio
interruption. Its remaining schedule-edit failure was a fixture timing error:
waiting for the replacement to appear as Auto's current request could delay the
edit until after it had started. The corrected test requires the DJ to still be
on air with at least two seconds remaining and records the edit time/current ID.
It tests prepared requests whether they are waiting or already loaded.

The repair also ignores already played Auto requests when finding a replacement;
Liquidsoap can retain a skipped outgoing request until its inactive source is
pulled again. The engine accepts the worker-validated replacement in either the
current prepared slot or the first waiting slot. `verification` contains the
complete corrected regression run. A separate 27-check run passed the duplicate
mode-session regression and the existing booth-state/live-assist tests.

## Completed short validation and endurance repeat

`verification` passed all **54 checks**, including six natural-EOF cases, six
operation/recovery cases, three calendar/event-window cases, return/session
logic and programming refresh. The corrected schedule edit and AUTO_CUE tests
both passed before the actual DJ EOF. Audio gaps in the ordinary, calendar and
underestimated-duration cases were 0–50 ms with the 50 ms measurement windows.

`quiet-smoke` passed its complete **300.01 seconds** on the final application and
engine source: 14 starts, both IDs, the DJ takeover, all three programme sections,
and 94 matching now-playing checks. It recorded no silence or fallback tone and
no recorded test issues. Maximum clock lag was 2.18 seconds, below the unchanged
ten-second limit; this is not a zero-lag result. A host process check confirmed
that this was the only private test engine (three existing live engines remained
running). The runner finished September 21 at 01:33:46 UTC.

The new three-hour repeat is `/tmp/freo-dj-return/shift3h`. Source hashes for all
application and Liquidsoap files were checked against the passing quiet rehearsal
before launch. Its `run.json` and `runtime/test_three_hour_programme0/soak-result.json`
are the authoritative live status. Starting this run is not an endurance pass.

Continuous observation began September 21 at **01:35:06 UTC**, with expected
completion at **04:35:07 UTC**. Runner PID 1724914 and test PID 1724953 were
verified alive after detachment. The private station uses UTC-3 and crosses
local midnight at 03:00 UTC. Initial samples confirmed advancing monitor and
decoder audio, matching titles, and no recorded issues or clock lag.

## Completed three-hour repeat and release follow-up

The run finished at 04:35:18 UTC, completing 10,800.25 seconds of observation:
63 starts, all six IDs, all three DJ takeover/returns, all programme sections,
local midnight, and 8,485 matching UI metadata checks. No silence of at least
three seconds or backup tone was detected; browser and worker error lists were
empty. Maximum clock lag was 4.24 seconds, below the ten-second ceiling.

The original test result remains **failed**, with three legacy HARD IDs late by
113.48, 157.33, and 149.18 seconds, plus one temporary `request_not_started`.
The owner explicitly accepted these ID delays. Future programme rehearsals use
SOFT IDs while still requiring every event to start and complete. Focused hard
event regressions remain in place. The enabled live ID already uses SOFT timing.

The temporary failure affected decision 38: it started at 03:02:37.330 and
completed at 03:02:46.120. Its missing-request observation appeared at 03:02:37.909
and was corrected by the later collected START. This also affected one ordinary
music decision, showing that the race is in request reconciliation rather than
the ID content itself.

Reconciliation now requires ten seconds of confirmed absence from a complete
engine inventory before failing a queued request on the same engine. Requests
remain queued while awaiting the real START; no playback is inferred. A request
reappearing, a collected START, or an incomplete inventory clears that absence
window. A changed engine identity still fails immediately. The small tracker is
scoped to the application, keyed by station/request/engine, and pruned each pass.
Regressions cover confirmation, genuine loss, reappearance, unavailable inventory,
and engine restart. No database migration is required for this repair.

Release evidence is collected separately under `/tmp/freo-release-20260921/`.
The owner authorized committing, pushing, and restarting the live deployment.

The release integration suite then exposed a 0.50-second gap when a calendar
change coincided with the end of an eight-second fixture. The replacement was
selected after EOF because normal calendar changes still used a two-second
worker cadence. The worker now polls at 250 ms for the final five seconds before
and five seconds after a calendar transition. The system harness uses that same
cadence function. Three different boundary alignments are tested; the 250 ms
audio acceptance target remains unchanged. Final results are recorded in the
September 21 station release report.
