# Two-hour live test: investigation and repair plan

Status: investigation recorded. The owner subsequently narrowed implementation
to the two audio recovery paths, focused checks and one final two-hour run.
The larger monitoring/profiling proposals below are background, not the approved
implementation scope. No application changes or live restarts
were made during that investigation. Implementation is tracked in
`focused-audio-repair-2026-09-21.md`. Preserve existing Station Control, Scheduler
and DJ Booth behavior; late IDs remain acceptable. Do not increase silence or
fallback thresholds to make the test pass.

## Completed run

Application `7803596` ran from 13:46:08 to 15:46:09 UTC on September 21. Final
cleanup finished at 15:46:23; the independent stop hook confirmed audio again at
15:46:29. Both original programming configurations were restored. Fresh post-run checks confirmed both stations had AUTO observations, a rendered
request and no fallback.

The run completed with findings: 168 track starts, 47 DJ returns, 372 UI
navigations, two actual worker service restarts, and hard/soft event completions
on both stations. There were no recorded JavaScript errors, command failures,
authentication failures or stable metadata mismatches. Browser heap samples
ranged up to 4.44 MB and 4.37 MB; these samples do not establish a general leak
absence, but do not show runaway growth in this run.

Evidence: `/tmp/freo-live-2h-20260921/`. Investigation extracts and analysis:
`/tmp/freo-live-dive-20260921/` (service journal, command/selection/audit exports,
engine START/END logs, incident index and audio analysis). Original evidence is
unchanged. The database export includes only test-period rows; the temporary
profiling database is separate and removed after its diagnostic command.

## What is established

### 1. PAUSE/CLEAR recovery still crosses the silence threshold

Five detections follow actual PAUSE/CLEAR commands. The engine timestamps and
command acknowledgments show these are real gaps, not an expired login or a UI
label problem:

| Station / operation | Stop evidence UTC | Next rendered AUTO START | Interval |
| --- | --- | --- | --- |
| demo-2 PAUSE | command processed 14:33:46.694 | 14:33:50.340 | about 3.65 s* |
| demo-2 CLEAR | rendered END 14:34:43.070 | 14:34:46.450 | 3.38 s |
| demo CLEAR | rendered END 14:37:08.640 | 14:37:11.690 | 3.05 s |
| demo PAUSE | command processed 15:29:15.980 | 15:29:19.260 | about 3.28 s* |
| demo CLEAR | rendered END 15:30:10.800 | 15:30:14.000 | 3.20 s |

*PAUSE has no rendered END; command processing is a proxy, not a sample-accurate
stop timestamp. Compressed output and source silence can also shift audible
boundaries relative to engine request timestamps.

The causal ordering is present in code and history: `process_deck_command()`
stops the deck immediately; `return_to_auto_if_stopped()` first observes that
stop, then waits two seconds; only afterward does `tick()` switch to AUTO and
refill the automatic queue. In these five cases the new AUTO selection occurred
only after the `live_auto_return` audit. The previous removal of the extra fade
helped, but left observation delay, the grace period, selection and loading in
series. A 250 ms requested sleep does not bound total multi-station tick time.

### 2. Several natural endings missed the prepared engine handoff

| Station / outgoing decision | Rendered END UTC | Next AUTO START | Request gap |
| --- | --- | --- | --- |
| demo-2 / 12015, Deck B after A-to-B | 14:47:51.570 | 14:47:59.510 | 7.94 s |
| demo-2 / 12066, ordinary Deck A | 15:03:47.550 | 15:03:56.840 | 9.29 s |
| demo / 12105, Deck B near restart | 15:16:16.610 | 15:16:25.010 | 8.40 s |
| demo-2 / 12101, repeated Deck A near restart | 15:16:18.760 | 15:16:27.020 | 8.26 s |

All used the worker's "DJ music stopped" recovery, rather than an accepted
engine-owned EOF completion. The first replacement (12020) was selected only
0.86 seconds before outgoing EOF, never started, and was marked
`programming_changed`; replacement 12021 subsequently started with the **same
programming signature**. This is evidence of cancellation/re-preparation, not
proof of an actual operator programming edit. `prepare_dj_return()` has a
cancellation branch that deliberately passes the synthetic signature
`dj-return-cancelled` to refresh, which can produce that reason.

In the second incident, replacement 12069 was selected seven seconds before EOF
and eventually played, but the engine did not return at EOF. Preparation begins
only inside the last eight seconds; its lease lasts five seconds. The run did
not record arm, renew, cancel, readiness or expiry decisions. Therefore the
specific missed gate—late arming, expiry, cancellation or target readiness—is
**not yet proven**. Do not present a larger lease alone as a demonstrated fix.

Both stations' endings around the second restart had no new AUTO selection
until after EOF. The service restarted at 15:16:09, approximately 7.6 and 9.8
seconds before those endings, directly against the eight-second preparation
window. Existing `worker-restart` audio validation stops/starts an in-process
worker thread **after** a replacement is prepared. It does not cover cold
process startup just before preparation, or two simultaneous endings against
production PostgreSQL and accumulated playback history.

### 3. Test reporting understates some interruptions

All eight silence intervals are about 3.04 seconds. The engine's `blank.detect`
activates backup tone after three seconds, so downstream `silencedetect` stops
counting silence even while music is absent. Retained WAVs confirm silence
followed by the station's 411 Hz backup tone in several incidents. A 0.1-second
spectral analysis is saved in `audio-analysis.json`; some files were captured
while still being written, so their available PCM ends before recovery.

The four recorded fallback recovery spans (8.55, 24.86, 9.80 and 20.15 seconds)
are **polling spans, not measured tone durations**. `condition()` raises a
fallback issue only on another sample that is still active after five seconds.
If a long UI/deck wait spans the episode and the next sample is healthy, the
recovery branch deletes it without raising an issue. Thus prolonged observation
spans appeared in actions without corresponding fallback findings. For example,
the 24.86-second observation span surrounds a 9.29-second engine request gap.
Neither number should be substituted for decoded tone duration. A controlled-time
reproduction using the actual runner's `condition()` method confirmed that an
active sample followed by recovery 25 seconds later records recovery, raises no
issue and clears the episode (`monitor-repro.json`). Such a sampling gap must
itself be visible; continuous monitoring is needed to establish duration.

Incident capture copies the preceding rolling files once, at detection. It does
not append the recovery portion. Also `sample()` attaches this iteration's engine
identity to `latest` only after several checks have already emitted issues,
which can mix a new HTTP snapshot with missing/older engine fields. These are
runner defects and gaps in evidence, not reasons to dismiss audible gaps.

### 4. Calendar coverage has an observation race

For demo, the final Calendar sample before the boundary was at 14:14:49.650.
The runner began leaving Calendar at 14:15:19.407 and confirmed Simple at
14:15:27.121; the next browser sample was at 14:15:37.959, already in Simple.
Boundary counting only happens inside `browser_sample()`, alternating stations
roughly every 20+ seconds. The fixed boundary-plus-15-second dwell did not ensure
that station had been observed after its boundary. Demo-2 was observed in
Calendar at 14:15:16.588 and received coverage credit.

This missing credit does not demonstrate a scheduler failure. Equally, a changed
schedule key alone is not proof that the intended audio aired. The retest needs
both a resolved boundary and the appropriate rendered selection.

### 5. Clock and worker latency need attribution

There was one stale observation, reported at 14:10:54 and observed recovered
4.73 seconds later. Its old worker observation was already about 12.5 seconds
old at detection. The engine still reported AUTO music, without fallback.

The preserved journal has 572 catch-up warnings on `clock.input.http`, peaking
at 8.26 seconds. The microphone's clock name is not proof that the output clock
stalled or that idle microphone input caused these gaps. In particular, no
catch-up warnings occur in the 15:03:35–59 or 15:16:05–28 incident windows.
There are no recorded worker exceptions in the preserved service journal.
CPU pressure and expensive tick stages still require measurement rather than
attribution from log proximity.

An isolated PostgreSQL clone replayed the exact pre-second-restart log prefixes:
115 records on demo and 125 on demo-2. The existing EventReader took 1.128 and
0.909 seconds, issuing 666/748 SQL statements and 98/112 commits respectively.
Application construction after Python imports took 0.377 seconds. This confirms
avoidable replay work, but **does not explain an eight-second interruption by
itself**. The clone was measured after the run, without the original concurrent
load and with rows in their current durable state. Full process import time,
remaining worker stages and the production startup path were not profiled.
Evidence: `replay-profile.json`; the disposable cluster and database dump were
removed by the diagnostic's cleanup trap. Earlier diagnostic setup failures
(account, encoded-path guard and temporary database encoding) were corrected;
none measured production restart latency.

## Repair sequence

1. **Make failures precisely observable and reproducible.** Add bounded engine
   handoff records with station, outgoing/target IDs, generation, arm/renew/cancel
   times, remaining lease and the exact EOF gate outcome. Record per-station
   tick duration, slow stages/socket operations and startup-to-first-observation
   latency. Sample engine/audio health independently of UI and mutation waits;
   put a coherent timestamped snapshot into each issue. Keep a full incident
   interval through recovery, distinguishing silence, backup tone and music.
   Preserve uncertainty if sampling was interrupted. Add regression cases for
   recovery after a long polling gap and for delayed boundary sampling.

2. **Remove the serial loading delay after PAUSE/CLEAR.** Reuse the existing
   prepared AUTO successor mechanism so selection/readiness work happens before
   the grace period expires. Keep the current two-second stop grace and manual
   cancellation semantics. Returning to AUTO must consume a validated ready
   successor, without a fade from an empty deck or a second cold selection after
   the grace period. Apply the same logic to A and B. Validate actual decoded
   audio, including slow selection/loading and competing work on station two.

3. **Make the EOF preparation survive real operating timing.** Reproduce the
   three relevant cases separately: late candidate preparation during A-to-B;
   ordinary EOF with a prepared target but no handoff; cold worker restart before
   preparation, with both stations ending nearby. Use the new gate trace to fix
   the specific failure. Budget preparation against measured selection/startup
   latency, reconcile engine-held candidates after restart, and recheck outgoing
   identity/readiness after blocking preparation. Do not discard a valid
   successor merely because outgoing identity temporarily disappears at EOF.
   Preserve immediate cancellation on manual intent, Cue, events and programming
   changes, and bounded expiry for a genuinely absent worker. Profile startup
   replay before deciding whether it needs an incremental processing change.

4. **Close the coverage and result-accounting gaps.** Remain in each scheduling
   mode until its boundary is observed and its rendered selection is confirmed;
   use a bounded timeout that fails explicitly. Report decoder silence separately
   from backup substitution. Promote confirmed sustained fallback to a finding
   even if a later sample shows recovery; do not infer continuous duration from
   two sparse samples. Keep exercise outcome and restoration outcome separate.

5. **Validate narrowly, then rerun for two hours.** First run repeated A/B EOF,
   repeat, A-to-B, PAUSE/CLEAR and manual AUTO cases on a disposable two-station
   stack with PostgreSQL, real engines and actual worker subprocess restarts.
   Restart before, during and after preparation, with accumulated event history.
   Include synthetic known audio for precise continuity measurements and the
   production MP3 types/durations for preparation realism. Recheck Cue/event
   cancellation, schedule edits, absent-worker expiry and UI lifecycle. Only
   after those pass: commit/push/deploy, verify both streams, then run the full
   two-hour live suite with independent monitoring, explicit completed coverage,
   two worker restarts, final AUTO settling and verified restoration.

## Acceptance criteria

- Natural prepared EOF keeps the existing sub-250 ms synthetic-audio target;
  no backup substitution. File-authored silence is measured separately.
- PAUSE/CLEAR retains the existing two-second grace; synthetic stop-to-AUTO gap
  stays within the existing 2.75-second regression allowance under two-station
  load, with no backup tone. If this cannot be met while preserving behavior,
  expose the tradeoff rather than changing the threshold silently.
- A brief worker restart cannot make both stations lose music at nearby EOFs;
  stale/invalid successors remain ineligible and long worker loss still expires.
- No unexplained decoder silence of three seconds or more; no unexplained
  fallback; no missed/failed controlled hard or soft events. Late IDs are advisory.
- Both stations complete every required DJ case and actual Block/Calendar
  boundaries; browser actions cannot blind the continuity observer.
- Full duration completes, original programming restores, and fresh decoded
  AUTO music is independently verified. Retain all failed attempts as evidence.
