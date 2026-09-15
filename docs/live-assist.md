# DJ Booth and AUTO

DJ mode is controlled by the buttons on the two decks. There is no broadcast crossfader, Playing Next panel, Queue button, or queue drop target in DJ. AUTO displays schedule status and monitoring without song details or a song browser. Shared Hot Carts, Station IDs and Sweepers work in either mode.

## Deck buttons

Both decks provide the same controls:

| Button | Result |
| --- | --- |
| Load Song / drop a song | Replace a non-playing deck silently and leave the new song READY. A playing deck asks ‘Replace and go live?’; accepting replaces it and starts the new song from the beginning. |
| Play / Take Air | Fade this deck in while fading the other deck out, then pause the outgoing deck. |
| Resume / Take Air | Resume from the saved position and crossfade from the other deck. |
| Pause | Pause this deck in place. It does not start the other deck. |
| Stop / Clear | Stop and unload this deck, including its pending repeat. |
| Fade Out | Fade this deck out over the selected duration, then stop and unload it. A subsequent Play, Pause, Clear, or mode change cancels an older fade timer. |
| Repeat ×1 | Replace this deck's future repeat with one copy of its song, played immediately afterward. Repeated clicks do not build an unbounded queue. |
| Preview | Audition the deck's song privately, stopping MASTER MONITOR. Click again to stop preview. Broadcast playback is unaffected. |

The shared Fade Length slider selects 0–10 seconds for Take Air and Fade Out (default 3 seconds, remembered in this browser). Zero switches immediately. Take Air occupies its own full-width row. Both decks play during a crossfade; the outgoing deck pauses when it completes. A newer Take Air cancels the previous completion timer.

Prepared songs are READY, playing decks LIVE, and interrupted/paused decks PAUSED. Empty Deck B flashes gently. Timers use engine position, including pauses and cart interruptions. Playing neither deck deliberately produces silence in DJ mode. Taking DJ control preserves AUTO's current song on A and clears automated lookahead. Returning to AUTO resumes the current schedule.

MASTER MONITOR remains in the shared header, survives internal navigation, and must be reactivated after a preview. Listening volume and cart ducking remain adjustable; they are separate from deck transport.

Program meters show the worker-observed engine RMS on a −60 to 0 dB scale, smoothed between observations. Both program bars share this aggregate measurement. Monitor meters measure the actual left/right audio of MASTER MONITOR or private preview and return to zero when listening stops.

## Reliable control

The web app stores authenticated, CSRF-protected deck commands with an idempotency token and expected decision identity. It cannot access private engine sockets. The worker rechecks the specific deck before applying a command. A stale command fails without controlling a replacement song; pending and failed commands appear in the UI. Buttons wait for the current command to be applied.

Liquidsoap reports both playing and prepared requests through its `current()` source method: paused prefetched audio is not necessarily listed by `request.on_air`. The worker includes these request identities during reconciliation, so a loaded deck is not incorrectly marked failed. Preparing a request does not count as an aired song. Confirmed starts update history and separation rules only when the deck plays audibly.

DJ ignores old ordinary queue intents; deck preparation/repeat commands and explicit carts own playback. A delayed observation disables mutations without stopping audio. Engine restart invalidates old request identities. The saved AUTO/DJ mode is preserved during rendering.

## Shared carts

Assign an approved song or imaging asset with a label, description, and behavior:

- PLAY OVER keeps the main deck advancing while reducing its volume by the chosen percentage.
- TAKE OVER pauses main audio, plays the cart, then resumes the interrupted position.

One cart plays at a time. The engine restores the selected deck's audio after the cart.

## Validation

`tests/test_deck_controls.py` exercises station scoping, stale commands, repeat targeting and worker intent. Chromium tests cover button requests, loading/clearing/dragging, private preview, queue visibility and responsive layout. Run `FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_deck_engine.py` for isolated real-worker/Liquidsoap playback validation using generated audio and temporary storage. No production station audio is used by those tests.

## Button-deck rollout — 2026-09-15

Deployed migration `b680aa432d19` with a verified database/config backup at `/var/backups/freo/deck-buttons-20260915T073346Z`. Both station templates validated; the running station retained DJ mode and the stopped station retained AUTO. Web, worker and playout services are active. Public/readiness routes returned HTTP 200, the stream returned MP3 bytes, and the worker reported fresh engine observations with no error. Empty DJ decks produced zero program signal.

Validation: 133 regression tests passed (the opt-in engine test skipped in that run); the real worker/Liquidsoap integration passed separately. All eight browser/workspace checks passed, with additional final Preview and screenshot checks. Nine focused deck-command tests passed, including rejection of obsolete DJ Up Next requests. The isolated engine audio proof verified both decks' load/play/pause/resume/fade/clear behavior, repeat once, cancellation of an older fade, cart overlay and takeover/resume, and return to AUTO. PostgreSQL upgrade/downgrade/re-upgrade passed in a temporary cluster.


## Deck transition update

Migration `c39fa204bb17` adds the selected fade duration and confirmed play-on-load intent to durable deck commands. Apply it before restarting the web and automation services. Render and restart playout to activate the updated Liquidsoap envelopes; restarting playout interrupts the stream and clears its in-memory deck positions. The real-engine recording test measures both tone amplitudes through each crossfade and checks RMS telemetry and timer cancellation.

### Activated — 2026-09-15

Applied migration `c39fa204bb17`, validated and installed both station configurations, and restarted the web, automation, ingest, and running Freo Demo playout services. Freo Demo retained DJ mode with empty decks after restart; Freo Demo Two remained stopped in AUTO. HTTP health/readiness and radio checks passed, the stream delivered MP3 bytes, and worker observations were fresh with no playout error. All four restarted services were active. Zero program RMS is expected until a deck is played.

Verified pre-update database and configuration backup: `/var/backups/freo/deck-transitions-20260915T134020Z`. Validation included 146 non-browser regression tests (two filesystem ACL cases passed outside the sandbox), five focused browser workflows, real-worker playback, recorded crossfades in both directions, and migration upgrade/downgrade/re-upgrade checks.
