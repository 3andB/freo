# Station Control and DJ Booth system testing

This suite exercises the existing workflows. It uses disposable databases,
generated audio, temporary Liquidsoap sockets, a private loopback Icecast server,
and Chromium. No test uses the installation database, station credentials,
production stream mounts, systemd services, or live library as fixtures.

For the separate normal-length music scenario, see
[three-hour programme testing](programme-shift-testing-2026-09-20.md). That scenario
uses disposable copies of library audio, timed IDs, DJ takeovers and real local
hour/midnight boundaries.

## Repeatable runs

Run from the repository with the development venv installed:

```sh
python3 scripts/test-station-system.py quick
python3 scripts/test-station-system.py integration
python3 scripts/test-station-system.py soak --seconds 300
python3 scripts/test-station-system.py soak --seconds 10800
python3 scripts/test-station-system.py soak --seconds 172800
```

Each command creates a new `/tmp/freo-station-…` directory containing a frozen
copy of the current edited source, SHA-256 source manifest, pytest log, JUnit
report, and `run.json`. `--output /tmp/my-new-run` chooses another new directory.
Tests execute sequentially to avoid making engine timing failures out of
concurrent browser/codec startup load. A run returning zero means its selected
tests passed; check JUnit skips as well. Do not interpret a running job as passed.
`case-results.jsonl` preserves completed test outcomes during the run, before the
final JUnit report is available. For focused reruns, repeat `--test tests/file.py`
or provide a full pytest node; `run.json` labels those runs as a focused selection.

The integration and soak profiles require localhost TCP/Unix sockets, Chromium,
chromedriver, ffmpeg, Liquidsoap, and Icecast. A restricted execution sandbox
may need permission to run local processes and sockets. Icecast binds only to
127.0.0.1 on a dynamically selected port. When invoked as root it drops to nobody.
The test adapter manages only the engine process it created, not a system service.

For an unattended run, preserve its launcher output and inspect `run.json`:

```sh
setsid -f python3 scripts/test-station-system.py soak --seconds 172800 \
  --output /tmp/freo-station-48h > /tmp/freo-station-48h-launch.log 2>&1 < /dev/null
```

`run.json` records the runner and pytest process IDs. To stop a run gracefully,
send SIGINT to its `test_pid`; fixtures then stop their private processes and
preserve the available evidence.

Allow sufficient host capacity; one engine and one browser still consume CPU and
memory. Prefer a separate test host for sustained load experiments. The venv is
shared with the repository, so leave its installed dependencies unchanged during
a run. Source is frozen; the installed OS binaries are not containerized.

## Coverage

`quick` includes the existing station, scheduling, cue, event, and deck service
regressions plus accelerated scheduling tests. Those tests advance four weeks
without waiting for audio. They sample both sides of hourly boundaries, all three
scheduling modes, Denver and London time, daylight-saving changes, and session
recovery. They exercise the real resolver and selection logic; media presence is
simulated, and no confirmed airplay is fabricated.

`integration` runs existing browser and engine tests, the legacy 65-second
scheduling soak, and a two-minute full-stack endurance smoke test alongside the
new connected journeys. The connected harness uses real Flask routes, automation `tick`,
Liquidsoap events, encoded Icecast audio, statistics collection, and browser
monitor playback. It checks scheduling handoffs, deck loading/playback, carts,
cue reordering/cycling, a timed event, navigation, worker restart, browser
disconnect, automatic return, and broadcast OFF/ON. A recorded tone identifies
the actual deck audio rather than relying solely on a meter or metadata.

The test worker is a restartable thread using the production tick and its
normal/adaptive cadence. It shares a disposable SQLite WAL database with Flask;
it does not prove process isolation, PostgreSQL advisory leases, systemd,
Nginx/TLS, or physical microphone/audio-device behavior. Existing dedicated tests
cover those components separately where available. Run PostgreSQL concurrency
and station-isolation checks with:

```sh
FREO_ENV_FILE=/dev/null bash scripts/test-scheduling-postgres.sh \
  tests/test_events_postgres.py tests/test_station_postgres.py
```

`soak` repeatedly operates Station Control through the browser and covers all
six directed scheduling-mode changes. It navigates between the booth and Control
every six switches while the browser stays tuned to the private stream. The
monitor must remain playing and advance; an independent decoder measures the
stream's audio. The worker continues decoding short MP3 and FLAC fixtures;
separate connected journeys cover WAV, normal-length deck audio, carts and events.

The soak checks:

- Real engine START evidence for every applied handoff; completion is history,
  so a track need not still be current when a later query arrives.
- Handoffs within ten seconds and displayed mode convergence within fifteen.
- No three-second silent interval in the continuously decoded private stream.
- No sustained fallback tone for five seconds during expected music playback.
- Fresh worker observations, running processes, and no engine clock lag above
  ten seconds. The decoder must also keep writing audio, so a stalled connection
  cannot pass merely because no silence samples arrived. Clock lag failures
  require checking host load as well as code.

`runtime/.../soak-result.json` is updated atomically and reports running/passed/
failed status, transitions, starts, timing, sampled process RSS, and browser heap,
DOM and event-listener counts. Memory values
are evidence for trend review, not a blanket leak-free assertion. The audio probe
retains the last two minutes of decoded mono WAV in four rotating segments.
The live JSON keeps only the last sixty resource samples; `resource-samples.jsonl`
retains the full minute-by-minute history without repeatedly rewriting it.
Screenshots, HTML, browser console messages, engine events, worker errors and the
disposable database are preserved at teardown. A failure's source manifest and
artifacts make the case reviewable and repeatable.

Uncaught browser JavaScript errors are checked every five seconds and immediately
persisted to `browser-console.jsonl`; teardown retains the combined console report.
Resource samples include summed Chromium process-tree RSS (shared memory may be
counted more than once). Natural memory samples are retained without forcing GC.
For a separate diagnostic of collectable pages/listeners, run:

```sh
FREO_NAVIGATION_ROUNDS=300 python3 scripts/test-station-system.py integration \
  --test tests/test_workspace_lifecycle_browser.py
```

That focused diagnostic uses garbage collection at checkpoints and checks stable
retained resources while navigating with the monitor playing. It is separate from
the real-audio endurance run.

## Findings from the September 20 work

The previous 48-hour scheduling soak actually stopped after about 7 hours
28 minutes. Its target decision 10553 has both START and END callbacks in the
preserved event log before the failed current-ID assertion; Liquidsoap also
reported clock lag exceeding forty seconds. This is evidence of a faulty
instantaneous test assumption and a timing problem in that run, not proof that
the stream was healthy. The old assertion now accepts only a real END callback
when the started target is no longer current. The new soak measures decoded
audio and clock lag separately.

A new browser regression reproduced Station Control polling becoming permanently
stuck behind an unanswered HTTP request. Station Control now bounds its requests
at six seconds, reports the interruption, and can refresh again. Writes are not
automatically retried. A second regression checks a lost broadcast response and
double-clicks without duplicating the saved broadcast intent.

The initial service baseline had 180 passes and one obsolete test failure: a
data-migration test used the latest schema, stamped an old revision, and tried to
apply all later schema migrations again. It now targets only the data migration
it is testing. Full schema migration tests remain separate.

Current validation evidence and any unfinished endurance run are recorded in the
accompanying validation report. Short runs never establish a 48-hour pass.
