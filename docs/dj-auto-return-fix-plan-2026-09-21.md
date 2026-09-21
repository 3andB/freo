# DJ-to-Auto interruption repair plan

Status: deployed September 21 after corrected regressions and rehearsal passed.
The three-hour repeat completed at 04:35 UTC on September 21 with continuous
playback and all DJ returns. Its recorded failures were three late IDs and one
temporary missing-request observation. The owner accepts the ID delays; a bounded
confirmation window now addresses the observation race. Release validation and
post-restart HTTP/audio checks passed; see `docs/station-release-2026-09-21.md`.
The owner subsequently authorized a five-hour stress run on the live stations.
Results are recorded in
`docs/dj-auto-return-repair-2026-09-21.md`.

## Evidence and scope

The completed three-hour programme run recorded silence at all three natural DJ
track endings: 3.04227, 3.04168 and 3.04308 seconds. Engine END-to-next-START
intervals were 4.14, 3.42 and 3.75 seconds. The engine enables backup tone after
three seconds of blank audio, so silence duration alone understates the time
without programme music. The five-minute rehearsal also exposed about 23 seconds
of fallback near a calendar change. Source-file silence scans were clear.

Repair these interruptions within the existing worker, schedule and engine
structure. Preserve manual DJ operation, AUTO_CUE precedence, live microphone
and cart behavior, scheduled event policies, and the existing three-second
crossfade when the outgoing source is still audible.

## 1. Establish a short, repeatable audio regression

Extend the existing isolated engine/system harness with distinct, continuous
test tones for the outgoing DJ track, scheduled replacement and backup. Exercise
natural EOF on Deck A and Deck B using the real automation worker. Record rendered
audio plus EOF, worker observation, return intent, queue readiness, engine mode
and replacement START timestamps. Use these to attribute delay; a three-second
fade setting is not itself proof of three seconds of silence.

Reproduce the calendar-window case separately, ending the DJ song shortly before
a programme change. Add the corresponding timed-event-window case. These checks
must demonstrate the current failures before application changes.

## 2. Remove avoidable delay at confirmed natural EOF

Primary code: `app/automation_worker.py`, `app/services/live_assist.py`,
`app/services/playout_queue.py`, and `deploy/liquidsoap/station.liq.template`.

Distinguish confirmed natural completion of the aired request from PAUSE,
CLEAR/SKIP callbacks, an empty prepared deck, and an unavailable engine response.
Scope completion evidence to the request, engine instance and current DJ session;
old or replayed EOF must not trigger another return. Keep the existing stop grace
for manual operations and temporary observations; bypass it for validated EOF
when no higher-priority source or pending operation owns the output.

Prepare and confirm the correct scheduled replacement before enabling its
output. Avoid fading up from zero merely to crossfade with a finished source.
Retain the normal crossfade for an explicit AUTO return while DJ audio is audible.
Use the existing selection and request lifecycle so retries do not advance the
playlist or count playback twice. Measure the worker/engine path before deciding
whether preparation must begin before EOF; any prepared request must be
invalidated when the schedule, cue, event or operator intent changes.

## 3. Prevent an empty output near schedule/event boundaries

Refine the twenty-second refill suppression in `tick()`: approaching a boundary
must not strand an otherwise playable automatic output. Check actual current
and prepared sources, not just future queue depth. Supply the minimum eligible
replacement when output would otherwise run dry, using the existing schedule
resolver and event-priority rules. Preserve hard-event interruption policy and
soft-event boundary behavior; do not postpone an event by adding an unnecessary
song ahead of it. Revalidate any prepared replacement at the boundary.

## 4. Verify operator behavior and races

Run focused checks for A/B EOF, manual PAUSE/STOP/CLEAR, manual AUTO crossfades,
the other deck still playing, a prepared paused deck, pending LOAD/PLAY commands,
AUTO_CUE continuation, carts, live microphone, and hard/soft events. Include worker
restart, stale/duplicate EOF and an unavailable socket. Confirm one return and
one replacement start, correct playlist progression, matching UI metadata and
station isolation.

Reuse `tests/test_deck_controls.py`, `tests/test_deck_engine.py`, cue/event tests
and the system harness. Add only the missing end-to-end audio coverage. Do not
change the existing silence/fallback thresholds to obtain a pass.

## 5. Acceptance and endurance validation

For a playable library, target no more than 250 ms between outgoing and incoming
programme audio in the deterministic natural-EOF regression, with no backup tone.
This is a proposed repair acceptance target, not a measured capability today.
Check audio identity as well as RMS so backup tone cannot masquerade as success.
If the worker path misses that target, use its measured latency to refine
preparation and the existing engine handoff before declaring the repair complete.

Run the focused unit/engine/browser checks, then the five-minute programme
rehearsal, including the previously failing boundary timing. Only after those
pass, repeat the full three-hour programme scenario with frozen source and the
same private music bundle. Require every timed ID and DJ takeover to complete,
all programme sections and midnight to be observed, no recorded playback/UI
issues, and no ordering, worker or clock-lag failures. Report resource trends
without treating a three-hour run as proof of indefinite memory stability.

Keep all validation isolated from live broadcasting. Deployment is a separate
step after a concrete patch and passing evidence are available.

Evidence: `/tmp/freo-programme-validation/shift3h/` and
`/tmp/freo-programme-validation/smoke2/`. Baseline report:
`docs/programme-shift-testing-2026-09-20.md`.
