# Three-hour realistic programme test

This scenario uses private copies of twelve installed music tracks (147–302
seconds each) and an 8.8-second station ID. Some copies retain their original MP3
encoding; others were converted to FLAC or WAV for format coverage. The originals
and live database are untouched. The bundle and its checksums are retained at
`/tmp/freo-programme-media-20260920`.

The disposable station follows three calendar sections: evening, late programme,
and after midnight. Each uses the twelve-track library in a defined rotation;
normal playlist wraps are expected. The test checks unexpected repeats/skips
within uninterrupted rotation sequences and the configured first track of each
new programme occurrence.

The test station's timezone is selected so setup begins in local hour 22. Its
clock then runs normally through hour boundaries and midnight during the three
hours. Neither the server clock nor any live station's timezone is changed.
The actual timezone and UTC/local start times are written to `programme-plan.json`.

The shift includes hard station IDs at hour boundaries, soft IDs at minutes
25/85/145, and DJ takeovers around minutes 40/100/160. A real browser loads and
plays a normal-length song on Deck A and verifies the existing automatic return
to scheduled playback. Timed events must start within their declared tolerance
and complete; skipped, failed or cancelled occurrences fail the test.

The persistent monitor and independent stream decoder run throughout. Existing
silence, fallback, clock-lag, browser-error and worker-freshness checks remain in
effect. Once output metadata has been stable for fifteen seconds, the displayed
now-playing title must match the engine's actual program decision. The run records
starts, event/DJ completion, schedule dates/hours, console errors and resource trends.

This diagnostic profile records recoverable playback, ordering, metadata and
browser-script issues and continues to the end of the shift. Any recorded issue
still fails the final result. Engine/decoder death, lost worker observations or
an unusable browser stop the test early. Other test profiles retain their
immediate-failure behavior. `programme-issues.jsonl` retains timestamped findings;
up to 24 silence incidents also preserve audio outside the normal two-minute ring.

## Commands

```sh
# Five-minute rehearsal: shortened music copies and compressed section timings.
python3 scripts/test-station-system.py programme --seconds 300 --programme-smoke \
  --media-dir /tmp/freo-programme-media-20260920 \
  --output /tmp/freo-programme-validation/smoke

# Full music, real hour/midnight boundaries, three hours of playback.
setsid -f python3 scripts/test-station-system.py programme --seconds 10800 \
  --media-dir /tmp/freo-programme-media-20260920 \
  --output /tmp/freo-programme-validation/shift3h \
  > /tmp/freo-programme-validation/shift3h-launch.log 2>&1 < /dev/null
```

Output directories must be new. Source is frozen and hashed for each run; the
fixture verifies media checksums before copying it into its private library.
`run.json` records status and process IDs; `runtime/test_three_hour_programme0/`
contains the programme plan, start history, `soak-result.json`, resource samples,
rolling audio, browser evidence, engine logs and disposable database backup.
The rehearsal validates the test machinery; it does not replace the full-length
music run. Only a completed passing result establishes a three-hour pass.

## Rehearsal findings

The first rehearsal (`/tmp/freo-programme-validation/smoke`) stopped on a decoded
silence interval of at least three seconds at natural DJ-track EOF. The source
excerpt itself does not contain three seconds below the detector threshold.
The DJ track ended at 17:23:02.26 UTC; automatic return was audited at 17:23:07.05.
At that point the next calendar boundary was less than twenty seconds away,
which inhibits queue refill in the existing worker. The exact contribution of
stop-detection grace, worker latency and suppressed refill needs follow-up;
this is a real observed interruption, not a completed three-hour result.

The second rehearsal enables collection of recoverable issues, so this known
handoff problem cannot prevent the remaining programme/event checks from running.
No production code was changed for this programme-test task.

The complete private bundle was independently decoded with the same -55 dB,
three-second silence threshold. None of its thirteen files contained a matching
interval. Results: `/tmp/freo-programme-validation/source-silence.json`.

The second rehearsal (`/tmp/freo-programme-validation/smoke2`) completed the
five-minute observation period, with 14 starts, both timed IDs, one DJ takeover,
all three programme sections and 81 matching now-playing checks. It correctly
failed on two recorded findings: a 3.034-second decoded silence interval and
about 23.34 seconds of observed fallback tone. No engine clock lag or browser
script errors were detected. The fixture recovered and completed the remaining
steps, demonstrating that the diagnostic can retain findings without stopping
the shift at the first recoverable interruption.

The full three-hour run is at `/tmp/freo-programme-validation/shift3h`.
Its live `run.json` and `runtime/test_three_hour_programme0/soak-result.json`
are authoritative for progress and completion; launching it is not a pass.
The continuous observation began on September 20 at 17:36:19 UTC and is due to
finish at approximately 20:36:20 UTC. The private station uses UTC+5, crossing
local midnight at 19:00 UTC. Its first samples confirmed advancing browser and
decoder audio, the expected programme source, and matching displayed metadata.
Runner PID: 1647131; test PID: 1647193 (both verified alive after detachment).

## Final three-hour result

The run completed its entire 10,800.36-second observation period on September 20;
the runner finished at 20:36:33 UTC. Final result: **failed on three silence
incidents**, one at each natural DJ-track end/return to automation. The decoded
intervals were 3.04227, 3.04168 and 3.04308 seconds. Playback recovered each time.
The rehearsal's prolonged fallback did not recur; maximum observed fallback in
the full run was 1.34 seconds.

All six timed IDs, all three DJ takeovers, all three programme sections and the
local midnight transition completed. There were 62 track starts and 8,573 matching
now-playing checks. The test recorded no ordering violations, worker exceptions,
browser script errors or engine clock lag. These results cover this scenario;
they do not establish that every system behavior is correct.

The next repair target is the repeatable DJ-to-Auto interruption, followed by a
focused audio handoff regression and a repeat of this programme run. No production
repair or deployment was performed as part of this test. Final evidence is in
`/tmp/freo-programme-validation/shift3h/run.json` and
`runtime/test_three_hour_programme0/soak-result.json`, with incident audio retained
beside the latter file.
