# DJ Booth: aligned decks, responsive loading, seeking, and live lighting

Research and implementation plan — 2026-09-15. No application or live-engine changes made for this investigation.

## Findings

### Layout and lighting

- `app/templates/admin/live.html` puts Fade Length before the decks. Move it immediately below the paired decks, within the same deck workspace.
- The deck markup is different: A has category/BPM/year/loudness rows, while B has a conditional cue warning. Text wrapping and conditional rows move the transport buttons independently. Equal card height alone does not align the buttons.
- `app/static/live.js` gives both playing decks the same `mix-live` class and sets gain to either 0 or 1. It cannot identify the incoming deck during a crossfade. A separate `active` class is based on a loaded song, not whether it is audible.
- Liquidsoap already knows transition start, duration, generation, target, and interpolated deck gains, but `freo_mixer.state` does not expose them.

### Loading delay

- The normal worker sleep and browser status polling are both two seconds. A command can wait for the worker, then wait again before its result becomes visible. Work done in each cycle adds further delay.
- Read-only inspection of 13 recent LOAD commands found submission-to-processed times of 0.079–2.031 seconds, median 1.315 seconds. These timestamps measure command processing, not decoder readiness or the moment the browser displays READY.
- Isolated local MP3 pushes took approximately 3–29 ms in the experiments. This does not establish total load latency, but supports prioritizing command dispatch, readiness reporting, and UI observation rather than assuming disk reads are slow.

### New-song position and seeking

- On both isolated decks, clearing a paused song left the old elapsed reading (3.92 seconds) while the current request identity was empty. After the replacement resolved, its identity changed and elapsed became zero.
- `deck_item()` can return a queued replacement when the engine has no current identity, while the status response retains the engine's old elapsed value. The browser can therefore display a new song with the previous song's position. This is a demonstrated stale-position window and a plausible explanation of the report; actual playback starting one-quarter into a fresh load was not reproduced.
- On the installed Liquidsoap 2.2.4, a paused forward seek returned 5 seconds, but `queue.elapsed()` remained zero. Seeking backward then failed with `Avutil.Error(Operation not permitted)`. A draggable bar cannot safely be implemented by simply calling native seek and trusting elapsed.
- A separately prepared request with `liq_cue_in=5.0` played with roughly 25.09 seconds of duration from a 30-second MP3. Its elapsed value started near zero, relative to that prepared segment. Preparing a new zero-offset request restored a zero start. Absolute file position must therefore include the segment offset.

## Proposed behavior

### 1. One symmetrical deck design

Use one shared deck template for A and B and matching row dimensions. Reserve the same space for metadata, messages, waveform, timers, and transport controls in every state. Keep full song text available through an accessible expanded view when the compact display truncates it.

Both decks contain, in this order:

1. Deck name and state.
2. Matching platter/art area.
3. Title, artist, album, and matching metadata rows.
4. Seek overview, absolute elapsed/remaining time, and cue marker.
5. Rewind, fine seek, and cue controls.
6. Full-width PLAY / TAKE AIR or RESUME / TAKE AIR.
7. Identical secondary transport grid and reserved status row.

Place the shared 0–10 second Fade Length control directly below the decks. Use a containing deck workspace instead of page-level row-number overrides that shift when notices appear. Side-by-side Take Air button top edges must differ by no more than one pixel. On narrow screens, use the same dimensions and row order for the stacked decks.

### 2. Explicit deck and transition state

Publish a versioned, coherent engine observation containing:

- Engine session, deck load generation, current decision/request identity, readiness, and playing state.
- Absolute file position, prepared segment offset, original duration, and cue marker.
- Transition generation, incoming/outgoing deck, phase, start time, duration, progress, and each deck's effective gain.

Tie position and transition updates to the same identity/generation. Ignore stale responses after a load, seek, clear, reversal, or reconnect. A new song immediately shows its requested identity, LOADING, and 0:00, but becomes READY only when the engine confirms that exact request. Preserve error feedback if preparation fails.

### 3. Responsive loading

- Commit the durable command and send PostgreSQL NOTIFY in the same transaction to wake the worker. Retain database scanning as recovery for missed notifications and SQLite tests; the notification is a wake-up hint, not the command itself.
- Give deck commands a short fast path, separate from the two-second scheduling/maintenance cycle. Keep engine ownership in the worker and preserve stale-command checks.
- Capture a fresh observation immediately after preparation and verify readiness instead of equating socket acceptance with READY.
- Add a small deck-state endpoint without schedule/history queries. Poll it at about 200–250 ms while loading or fading and slow down when idle or the page is hidden. Refresh full programming status less often.
- Show LOADING immediately, keep a stable card, and report errors on that deck. Do not disguise latency with a premature READY state.

Measure submission, worker pickup, request acceptance, readiness, observation, and browser rendering separately. Targets for ordinary local files: visible feedback within 100 ms and 95% of loads visibly READY within one second. These are acceptance targets to validate under load, not promises based on the push timings alone.

### 4. Start at zero, rewind, seek, and cue

- Every new LOAD, including loading the same song again, creates a fresh generation and resets position, segment offset, preview cursor, and deck-local cue marker to zero. Library cue-in metadata must not automatically move a manual DJ load away from zero.
- REWIND returns to 0:00. Add ±5-second search buttons, keyboard-accessible timeline scrubbing, and an editable time field for exact targets.
- SET CUE marks the selected absolute position. GO TO CUE moves there. Keep one deck-local cue point initially; persistent multi-hotcue banks can be a separate feature.
- Preview starts at the selected position and remains private. Playing a prepared deck starts at its selected position; normal Pause/Resume retains position.
- Rewind/seek preserve whether the deck was paused or playing. A seek on a live deck is clearly labeled as affecting live audio and commits on pointer release or an explicit seek action, not every drag event. Apply a short de-click envelope around live jumps.
- Use a newly prepared request at the requested cue-in offset as the reliable initial seek/rewind mechanism. Prepare it before replacing the active request where possible. Track absolute position as segment offset plus rendered segment time. Do not introduce native backward seek until compatibility tests demonstrate correct behavior.
- Seeking must retain logical playback identity for history/accounting; internal decoder requests need their own generation mapping so a seek does not create a false new song play. Recompute remaining time and clear obsolete repeats/transition completions as defined by the operation.
- Supply a simple seek timeline immediately. Add cached waveform peaks generated asynchronously; missing peaks must never block loading. Validate MP3/VBR accuracy against recorded audio rather than promising sample-accurate seeking.

### 5. Engine-driven lighting

| State | Visual behavior |
| --- | --- |
| READY / PAUSED | Quiet neutral border; stable cue/position display |
| LOADING | Restrained blue preparation indicator with explicit LOADING text |
| Incoming crossfade | Blue → ice-white pulse around the full deck/control outer edge; GOING LIVE label and transition progress |
| Outgoing crossfade | Warm glow diminishes with actual gain; FADING OUT label |
| Fully live | Smooth red → orange → amber/yellow → red breathing glow around the deck and platter |
| Disconnected / failed | Stop live/transition animation and show the actual connection/error state |

The incoming blue/white treatment takes precedence over the normal live glow, then changes to warm live colors only when the engine completes the transition. An immediate zero-second take goes directly to LIVE. Do not derive completion from a browser timeout. Use bounded opacity, no scale changes or reflow, slow smooth pulses, and static state colors when reduced motion is requested. Labels make direction clear independently of color.

## Delivery order and checks

1. **State correctness:** add generation/readiness/position handling; reproduce replacement of both paused and never-played requests; prove every fresh load starts at zero and remains there while prepared.
2. **Latency and transition telemetry:** introduce command wake-up and focused observations; measure end-to-end latency and prevent missed short fades.
3. **Seek/cue:** implement explicit offsets and verified preparation; test forward/backward jumps, rewind, boundaries, same-song reload, private preview, and history identity using recognizable recorded audio sections.
4. **Layout and lighting:** shared deck template, Fade Length below, equal transport rows, and observed incoming/live states.
5. **Regression and rollout:** check AUTO/DJ switches, repeat, cart overlay/takeover, short songs, overlapping commands, failed loads, reconnects, transition reversal, mobile widths, long metadata, and reduced motion. Validate and deploy using the established database/config backup and station restart process.

Key acceptance checks: no stale elapsed value paired with a new song; no position advance while prepared; selected cue matches audible output within a measured decoder tolerance; no accidental broadcast from preview; no false history starts caused by seeking; aligned Take Air buttons across every state combination; actual incoming deck highlighted throughout a fade; latency measurements include decoder readiness and visible acknowledgement.

## Research sources

- [Liquidsoap seeking and cue points](https://www.liquidsoap.info/doc-2.2.5/seek): native seeks are relative and report the actual displacement; file requests accept cue offsets. The adjacent 2.2.5 documentation was checked against isolated experiments on installed 2.2.4.
- [Liquidsoap 2.2.4 release notes](https://www.liquidsoap.info/blog/2024-02-07-liquidsoap-v2.2.4/): cue processing moved into request resolution/decoding, affecting duration and requiring care around abrupt audio cuts.
- [Mixxx deck, waveform, and cue controls](https://manual.mixxx.org/2.4/en_gb/chapters/user_interface): reference for timeline seeking, cue markers, and preview controls. Freo's required zero-on-load behavior takes precedence over any automatic saved-cue behavior.
- [PostgreSQL NOTIFY](https://www.postgresql.org/docs/16/sql-notify.html): notifications issued in a transaction are delivered after commit; durable command records remain the source of truth.
- [W3C reduced-motion technique](https://www.w3.org/WAI/WCAG21/Techniques/css/C39): honor the user's motion preference while preserving visible state information.
