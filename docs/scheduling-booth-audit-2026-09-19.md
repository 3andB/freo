# Scheduling and DJ Booth audit — 19 September 2026

Starting revision: `13c87ff`. Scope: scheduling editors and resolution, worker execution,
Events, Booth/Cue/decks/carts, public playback status, persistence, recovery and audio.
Active tests use isolated databases, media, sockets and Liquidsoap processes.
Installation checks are read-only. These repairs require coordinated activation of
the application, worker and rendered station engine configurations.

## Reproduced findings and repairs

| Finding | Evidence | Repair |
| --- | --- | --- |
| A schedule switch can stall while a DJ Event owns the output. | A real engine remained in the worker's FADING state after the handoff; the Event bus continued pausing the scheduled source. | Clear the Event bus, boundary reservation and queued Event audio atomically with the engine handoff. Cover both waiting and playing Events. |
| Forced handoffs and operator skips can falsely complete Events. | The engine emitted END after cutting a 40-second Event after approximately two seconds. Worker regressions also reproduced false completion after Skip/Fade. | Suppress natural-completion callbacks for sources cut by a schedule handoff. Mark accepted operator interruptions explicitly and keep those outcomes terminal while preserving confirmed starts. |
| Direct visual sources were omitted from programming-change detection. | Disabling or changing the file/duration of a directly scheduled song left its signature unchanged and queued selection intact. | Include active song/artist/album candidates and selection-order metadata in the signature; invalidate stale automatic lookahead. |
| Booth and public program labels ignored the active visual schedule. | Simple mode reported the legacy rotation in the Booth and “Station mix” in the public player. | Use the visual resolver's program label. |
| DJ Event and cart display could identify inaudible audio. | The public player selected the paused DJ deck during an Event. The real engine reported the Event during a takeover cart. | Use the observed Event for public Now Playing; respect microphone and takeover-cart suppression in engine metadata. |
| Finished sequences could leave their occurrence labelled Playing. | Three installation occurrences from September 15 remained STARTED although their executions and all items were COMPLETED. | Reconcile active occurrence labels from durable terminal execution records. Preserve recorded timestamps and terminal failure/cancellation states. |
| Booth Event status could fail on database timestamps without an offset. | Browser server logs showed HTTP 500 responses from subtracting a naive playback timestamp from an aware Event timestamp. | Serialize playback timestamps with an explicit UTC offset, including when SQLite returns a naive value. |

The history repair uses existing execution evidence. It does not infer successful
completion from elapsed time. Interrupted playback remains confirmed airplay history,
but is not counted as a completed Event or sequence.

## Verification

Evidence directory: `/tmp/freo-scheduling-audit-20260919`.
The repository runs use frozen source copies with SHA-256 manifests. `final-source`
covers the initial repairs; `final-source-v2` adds the UTC correction found during
the browser run; `final-source-v3` adds operator-interruption history; and
`final-source-v4` adds the final recorded-audio test instrumentation.
Browser tests exercise real Chromium against isolated
Flask servers; their simulated worker observations are complemented by separate real
engine tests.

The broad non-browser run passed 677 cases and skipped 53 opt-in checks. Its two
failures were isolated Liquidsoap startup timeouts during concurrent test load;
the codec case subsequently passed in the dedicated engine run. The opt-in
categories include engine, PostgreSQL, scale, soak and pinned external API tests;
the separate runs below cover the scheduling-related categories.

The dedicated engine/scale/codec run passed 31 of 33 cases. One failure was the
soak fixture's 40-second startup deadline. Its initialization allowance is now
120 seconds; runtime handoff and silence limits remain unchanged. The other
failure was a five-second Cue test item finishing naturally before the handoff
completed. The test now uses a 20-second second item, verifies absence of its END
callback and checks recorded output instead of estimating silence from delayed
worker polls. Both mixed-media reruns passed, with maximum recorded silent spans
of 1.0 and 0.5 seconds against a three-second limit.

The final Event/Booth/history service run passed 82 cases. The initial disposable
PostgreSQL run passed ten scheduling, Events and station-isolation checks; five
scheduling/Events PostgreSQL cases passed again after the repairs. The latter
report also includes fourteen SQLite regressions, which are not PostgreSQL proofs.

The six-case supplementary audio run passed: both mixed-media scenarios, both
ordinary/Event Skip scenarios, loudness normalization and the short soak. The
65-second soak made seven switches covering all six directed transitions, recorded
twenty actual starts and 116 steady-state samples, and measured a maximum handoff
of 2.85 seconds. Both additional real integration cases passed: microphone
fade/return/disconnect with cart interaction, and continued streaming while another
station is created/deleted and shared-media ownership changes.

Browser verification covered all 83 collected browser cases across the original
and continuation runs: 82 passed and the optional demonstration screenshot case
was skipped. Across the final evidence reports, 815 distinct current pytest cases
passed out of 825 collected. The ten remaining opt-in skips are the demonstration
screenshots, pinned external API source validation and eight PostgreSQL cases for
API licensing/schema, DMCA and importer behavior. These are not scheduling-specific
PostgreSQL checks. Counts are deduplicated across reruns in `coverage.json`; the
individual group totals above overlap and must not be added together.

Both candidate station engine configurations passed `liquidsoap --check`. Python
compilation and `git diff --check` passed. Runtime and test source hashes match the
final frozen source copy; subsequent changes only document the audit.
The Events browser test now waits for the debounced search to replace the old
results before clicking “Search within”; previously it could click a detached node.

Additional regressions live in `tests/test_schedule_booth_integration.py` and
`tests/test_schedule_booth_engine.py`. They cover visual-source edits, program labels,
DJ Event display, queued/started single and sequence handoffs, replay of completion
notifications, recovery of stale sequence history, and the full worker path through
MP3/FLAC/WAV Cue playback, DJ Event permission, reader restart and return to scheduling.

The extended soak uses a separate engine and discards output audio. Its PID, pytest
log and eventual JUnit report are in the evidence directory: `soak48-final-launch.json`,
`soak48-final.log` and `soak48-final.xml`. It launched at 13:20:28 UTC on September 19
from `final-source-v4`, at reduced process priority, with PID 1276557. Runtime metrics
are under `/tmp/fs48-final/test_continuous_scheduling_soa0/soak-result.json`. At the
13:24 UTC audit check it had made eighteen switches and recorded 55 starts without an
assertion failure; the largest handoff was 2.88 seconds. Expected completion is
approximately 13:21 UTC on September 21. The earlier attempt (`soak48.xml`) failed
during initialization under concurrent test load; it is preserved as failed evidence.

**The 48-hour soak is running, not passed.** This controlled-tone test also does not
replace the separate mixed-media and fault scenarios. Successful foreground checks
do not establish that unactivated repairs are working in production.

## Installation observations

At 12:21 UTC both managed station engines, the application and automation worker
were active. Web health, database readiness and automation health returned OK.
Migration head was `f38c6a902e17`. Both stations had two queued requests, fresh
observations, no reported playout errors and no pending schedule switches.

`freo-demo` was following its legacy clock in AUTO, with America/Denver station
time. `freo-demo-2` was following Playlist 1 in Simple/AUTO, with UTC station time.
The three stale Event history records were on the first station; their existing
completed executions were inspected in a read-only transaction.

At 13:16 UTC all six health endpoints returned HTTP 200/OK. Both station mounts
returned MPEG audio; both had two queued requests, no pending switch or observed
playout error, and snapshots younger than three seconds. The worker heartbeat was
2.54 seconds old. Both station engines, web application, automation worker and public
schedule refresh timer were active. The three stale Event labels were still present,
as expected before activating the repair.

Candidate engine configurations were rendered from both stations' actual audio
settings, using placeholder credentials, into the evidence directory and validated.
No live station configuration, database record, service or broadcast mode was
changed during these checks. Live activation must render and validate the updated
Liquidsoap template and restart the affected engines alongside the application and
worker. No schema migration is required by these repairs. Keep a paired source and
engine-configuration backup for rollback; verify the observed output, modes, worker
heartbeat and Event history after activation.
