# Microphone exit correction — 2026-09-24

Baseline: `f93b4f5`, branch `fix/live-mic-exit`, development version
`0.3.0-rc.7.dev5`. This is source for the next candidate, not a signed release.

## Behavior verified

- AUTO and DJ BOOTH wait for microphone shutdown before selecting their mode.
- In-app departure and sign-out warn the owning broadcaster. Cancel keeps the
  microphone live; confirmation restores the interrupted program before leaving.
- Browser Back cancellation restores the booth URL. Submitted workspace navigation
  also invokes the microphone guard.
- Native refresh warnings support both Cancel and Leave. The browser fixture uses
  an explicit beforeUnload prompt policy and an active BiDi connection so that
  ChromeDriver does not automatically accept the dialog.
- Late microphone permission responses stop their tracks. A failed return blocks
  switching modes and reconnecting until a subsequent return/off-air observation.
- Server-side mode/deck guards reject changes while the gateway is returning.
- The existing authenticated disconnect action cuts speech and permits a bounded
  silent handoff to the existing worker/mixer. It does not add a scheduler, public
  endpoint, persistent microphone identity, recording or database migration.

## Local verification

- Service/version/live-assist regression run: **95 passed**, with opt-in engine
  checks run separately. Log: `/tmp/freo-mic-unit.log`.
- Final gateway and cue guard run: **22 passed**, 3 opt-in audio cases skipped
  here and run below. This overlaps the preceding regression run.
  Log: `/tmp/freo-mic-guards.log`.
- Browser coverage: **15 distinct cases passed** across the final regression run
  and focused rechecks. Logs: `/tmp/freo-mic-browser-final.log`,
  `/tmp/freo-mic-browser-recheck.log`, `/tmp/freo-mic-native-warning.log`.
  The initial native-warning failure was ChromeDriver automatically accepting
  beforeunload; the final explicit-policy test passed without weakening assertions.
- Real WebRTC/Liquidsoap audio: **3 passed**. Measured mic-tone removal, restored
  music audibility and resumed position for AUTO and DJ, including WebRTC closure
  arriving before the exit beacon. Abrupt loss still returned to AUTO.
  Log: `/tmp/freo-mic-audio-exit-race.log`.
- JavaScript syntax checks and `git diff --check` passed.

The normal CI workflow now includes microphone service/browser checks; the full
candidate audio suite includes both interrupted-feed restoration cases. These
workflow changes have not been run remotely as part of this local implementation.

No VM TLS/access changes were made, as requested. Tests used isolated databases,
browser profiles, generated audio and local engine processes. Production/main,
production streams, preserved RC5/RC6 artifacts and accepted test VMs were not
changed. Physical microphone compatibility was not newly tested; the operator
reported that microphone capture already works on freo.world.

Deploy browser assets and the gateway together after ending any live mic session;
restart the web and mic services. No playout restart or station re-render is needed.
