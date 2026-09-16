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

Prepared songs are READY, playing decks LIVE, and interrupted/paused decks PAUSED. Empty Deck B flashes gently. Timers use engine position, including pauses and cart interruptions. After DJ audio has aired, two seconds with neither deck playing returns the station to AUTO. Carts and pending deck commands defer this check. Empty decks before the first DJ playback remain available for preparation. Stop detection survives worker restarts. Entering DJ Booth empties both DJ decks and keeps AUTO's separate source and schedule running. Preparing either deck does not interrupt Auto. Play / Take Air crossfades from Auto into the chosen deck using the deck fade length, then stops the Auto source and holds scheduled playback. Returning to AUTO crossfades the DJ audio into scheduled audio over three seconds. Returning before starting either DJ deck leaves the current Auto song uninterrupted. Scheduled audio also fades in when DJ music has already stopped. Manual and automatic returns show an informational OK popup. The worker refills the schedule during the fade and defers hard timed interruptions until it completes.

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

## Symmetrical decks and observed lighting

Deck A and Deck B now use one shared template with matching fixed row dimensions. Metadata and empty/loading messages cannot shift their full-width Take Air buttons. The deck pair is the first panel in DJ Booth, above the broadcast header and notices. Fade Length sits immediately below the pair. Empty decks show only NOTHING LOADED, with blank reserved artist/album/message rows to preserve the same spacing as loaded decks. A fully playing deck has a red LIVE button and a smooth orange/white/red/yellow perimeter glow. During a crossfade, both edges pulse blue/white; the incoming deck is brighter and labeled GOING LIVE, while the outgoing deck is labeled FADING OUT. Reduced-motion mode keeps static state colors.

The engine reports the incoming deck, transition progress, and gain envelopes. The adapter accepts both the previous nine-field observation and the new thirteen-field observation during rollout. DJ worker and visible-browser observations use a 250 ms cadence; AUTO retains the slower cadence.

A dropped replacement immediately shows LOADING and `0:0:00`, clearing its previous track metadata and progress while preparation is pending. It becomes READY when the engine reports the replacement's request identity. Empty and never-played prepared decks cannot inherit an old elapsed reading; clearing an engine deck also reports zero elapsed. Replacing a previously played deck is covered by the real-engine test.

This update is prepared and tested; installing its station configurations and restarting services is pending rollout approval.

Auto-return validation: isolated recordings verify gradual fades from either DJ deck into scheduled audio. Worker tests cover the stop grace period, preparation, handovers, carts and restart persistence. Chromium verifies both notification paths. Engine queue behavior follows the [Liquidsoap request-source reference](https://www.liquidsoap.info/doc-2.2.5/reference/source-track-processing).

The schedule uses `freo_queue`; Deck A uses `freo_a`; Deck B uses `freo_b`. The 16-field mixer observation adds Auto standby, current identity, and gain while retaining older observation parsing. The worker refills the schedule during DJ standby and only suspends scheduled blocks after a DJ deck takes air.

## Auto and DJ operation status

Auto **Skip to next** requests a three-second fade-out, then advances the Auto queue. The request and the engine callback both verify the expected playback identity; a song change or mode change cancels an obsolete fade. Repeated requests cannot advance additional items. Fading is unavailable while a cart is on air.

Auto shows the active program, the actual on-air item's category, artist and title. The old clock-name label beside Monitor is removed. Imaging, carts and manual selections are labeled explicitly.

The status bar stays visible in Auto and DJ mode. An action message lasts 15 seconds; each new message restarts that period. With no action message it rotates every five seconds between broadcast, operating mode, and station listener count. Observed connection/stream faults take priority over rotation. Listener counts come from the station's Icecast mount, polled by the worker at most once every five seconds; unavailable or stale observations never display a fabricated zero.

### Exclusive carts

Triggering a cart locks every cart playback button on that station. The selected slot pulses blue with **QUEUED…**, then glows red with **PLAYING** once the engine confirms its start. Completion or failure releases the lock. Losing the connection keeps the controls locked until reliable observations return. Locking is enforced on the server across operators and tabs. Other stations remain independent. Slot identity is captured with the playback request, so two slots containing the same audio still highlight correctly.

### Programming edits and the next automatic song

Each automatic selection saves a programming signature and its prior clock/rotation cursor positions. The worker compares committed station configuration every tick, including schedules, clock/rotation slots, category membership, eligible shared songs, imaging groups and block definitions. This covers UI edits, CLI changes and database bulk updates. Normal worker detection is within its two-second polling interval.

When programming changes, a new engine command removes only outdated future automatic requests. It leaves the current source, explicit manual/event requests, DJ decks and carts intact. The worker restores the cancelled selection's cursor checkpoint and refills from current programming. Confirmed playback counts are unaffected by cancelled lookahead. A saved cancellation marker permits recovery after a worker restart. Active clock blocks keep their progress and execution snapshots.

An item already starting when the edit reaches the worker is considered current and continues playing; the following automatic selection uses the change. Explicit manual/event/block playback takes precedence over automatic music. Editing an active block definition applies to future executions, not its already captured items.

### Deployment for this update

Back up the database and apply revision `c48f1d207ab9`. This release also changes the Liquidsoap station template: regenerate and validate every managed station configuration, then restart the station engines and the web/automation services. The worker requires the new `freo_queue.remove` and `freo_mixer.fade_next` commands. Arrange the engine restart as a broadcast maintenance operation; updating Python alone does not install these commands into a running engine.

## Live microphone

The third **LIVE MIC** board captures a browser-connected microphone or USB mixer,
with software gain, meters, mute, and the same carts and station IDs. Opening the
board leaves the current feed playing; only **GO LIVE** fades it out and opens the
mic. See [LIVE MIC setup and behavior](live-mic.md) for the optional audio gateway,
activation steps, return behavior, and connection recovery.
