# DJ Booth Cue

The booth's music area has a working Cue above Find a song. Add songs using **+ CUE** or drop a search result at a position in the Cue. Drag Cue entries to either deck, or use **LOAD A / LOAD B**. Loading a ready deck prepares it; **PLAY / TAKE AIR** broadcasts it. Replacing a playing deck retains the existing confirmation.

Drag the dotted handle to reorder. Keyboard users can focus the handle and press **Alt + Up / Down**. Drag the divider between Cue and Find a song to resize the panels, or focus it and use the arrow keys. Search and category changes preserve the working Cue.

When a Cue entry finishes airing, it moves to the bottom. Duplicates are independent entries. Loading and previewing do not rotate the Cue; an interrupted song stays in place. A requested deck repeat owns the rotation after its final playback finishes.

The Cue panel has a slow orange → yellow → red light: gentle when AUTO_CUE is armed, brighter when a Cue entry is confirmed on air. Preparing a deck alone does not light it. The light fades when inactive or disconnected, including when a status request stalls for five seconds. Reduced-motion settings keep the warm light steady.

## AUTO_CUE

Switch **AUTO_CUE** on to continue at the natural end of the current deck song, including a song loaded directly from search. Finished Cue entries move to the bottom, so playback cycles through the set. A single playable entry repeats.

AUTO_CUE operates in the worker and audio engine, even with the browser closed. It reuses an empty deck and preserves songs prepared on the other deck. It waits for another airing deck, a transition, or a cart to finish. Pausing, stopping/clearing, or fading out explicitly switches AUTO_CUE off; turn it back on to re-arm. Turning it off leaves current audio playing. Station AUTO and live microphone operation also disarm it.

Unavailable audio is skipped without deleting the entry. An empty or entirely unavailable set pauses AUTO_CUE with a message and permits the existing return-to-schedule behavior. A failed or uncertain engine start pauses AUTO_CUE for operator review rather than retrying a destructive deck command.

## Saved sets

The working Cue autosaves to the station's database and is shared by authorized operators. Refreshing or returning later restores it. **Save** stores the current order as a named set; **Save as** creates another. Playback rotation changes the working Cue, while the named snapshot retains its saved order until saved again.

**Load** restores a named set. **New** starts an empty working Cue. Both switch AUTO_CUE off and leave current audio playing. If the working order differs from its saved snapshot, the dialog offers Save, Discard, or Cancel. Concurrent edits use revision checks: an outdated edit is rejected and the latest list is shown.

## Deployment and rollback

This change requires both the database migration `ab28c910d642` and regenerated Liquidsoap station configurations. The new worker reads `END <decision> <timestamp>` events emitted by the updated engine template. Updating only the web assets does not enable automatic advancement.

Before rollout, back up the database and installed station configurations. Validate an upgrade from `f19a73b206ce` on a disposable database with existing stations and music, then boot the web app and worker against it. Generate station configuration using the normal provisioning path and validate it with the installed Liquidsoap version. Use a temporary output and generated audio to verify manual playback → Cue → Cue, pause/clear/repeat, and worker restart without duplicating completion. Check the browser at desktop and mobile widths and with two operators editing.

Apply the additive migration before restarting application workers that use the new tables. Regenerate and restart station playout through the installation's normal controlled deployment process; this can interrupt broadcast audio and should be scheduled accordingly. No production migration, service restart, or station configuration replacement is performed by the implementation tests.

Rollback application code and engine configurations together. Retaining the new tables preserves saved sets for a later re-upgrade. The migration downgrade drops all Cue drafts, snapshots, mutation records, and playback associations; export or back them up before using it.

## Validation commands

Run the focused regression checks, browser workflows, and short-clip audio proofs together:

```sh
bash scripts/test-dj-cue.sh
```

This uses isolated databases, generated audio, and local recording outputs. Cue clips are six seconds long; the deck-control test uses a twenty-second clip to leave time for commands. Playback is verified without a browser driving the engine. The checks cover automatic cycling, reordering while a Cue song airs, worker event-reader recreation, finished-entry rotation, pause, disabling AUTO_CUE, repeat, clear, saved sets, and connection-aware lighting. Chromium, ChromeDriver, FFmpeg, and Liquidsoap must be installed. Individual suites can also be run:

```sh
FREO_LIVE_MIC=0 venv/bin/pytest -q tests/test_booth_cue.py tests/test_cue_migration.py tests/test_deck_controls.py tests/test_live_assist.py tests/test_booth_state.py
FREO_LIVE_MIC=0 venv/bin/pytest -q tests/test_cue_browser.py tests/test_live_browser.py tests/test_booth_state_browser.py
FREO_LIVE_MIC=0 FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_cue_engine.py tests/test_deck_engine.py
```

Browser and real-engine tests require local socket access and use temporary databases/media. Explicitly disabling the installation's microphone input keeps these tests isolated. The Cue engine tests record audio and check that the expected generated song frequencies actually aired.

The current handoff is worker-mediated after confirmed EOF, using the booth's existing 250 ms worker cadence. It does not prefetch a hidden next deck request or promise gapless mixing. End callbacks use `source.on_end(delay=0)` with durable playback identity and interruption checks; see the [Liquidsoap track processing reference](https://www.liquidsoap.info/doc-2.2.5/reference/source-track-processing).

Validated during implementation on 2026-09-18: 66 focused Cue/live/deck backend checks passed; a subsequent 43-check Cue/deck/migration run also covered pending-start reordering, disable, and New cancellation. The two new browser workflows passed, as did the existing library-to-deck drag workflow and the deck-control/mode-visibility and responsive-alignment checks. The isolated Cue audio test passed after the final automatic-start revalidation. Broad suite attempts were interrupted; these results describe targeted checks, not a complete suite pass. Implementation tests did not change production services or data.

Deployed on 2026-09-18 after a database/configuration backup and an upgrade → downgrade → upgrade rehearsal on a restored PostgreSQL database. Both generated station configurations passed Liquidsoap validation before the live migration. Application services and both managed station engines were restarted; the installation validator passed, both streams delivered MP3 data, authenticated booth pages included the Cue controls with fresh worker observations, and public HTTPS assets matched the release files. Station operator modes were preserved. No deployment errors were found in the restarted service logs.

Cue glow follow-up (2026-09-18): all 75 targeted checks passed across the focused run and the corrected browser rerun. The initial run passed 74 checks; the new browser check needed its scroll reset after mobile resizing so the fixed header did not intercept clicks. Its rerun passed, including playback/armed/idle lighting, reduced motion, offline recovery, and a stalled status request. Both six-second Cue audio scenarios passed, including mid-playback reordering and event-reader recreation, as did the real-engine load/play/pause/repeat/clear check. Day, night, and mobile screenshots were inspected. These are targeted regression results, not a full repository suite.
