# DJ Booth Cue

Implementation plan — 2026-09-18. Planning only; no application or runtime changes.

## Intended experience

Split the existing Find a song area vertically: Cue above, Find a song below. Keep both decks visible beside this stack on desktop. The DJ can build and reorder a set while music plays, load either deck manually, or enable AUTO_CUE to continue through the set automatically.

**Confirmed behavior:** when a Cue song finishes, move that entry to the bottom of the working Cue. Do not remove it. With AUTO_CUE enabled, the list cycles continuously.

```text
┌──────────────────────┬──────────────────────┐
│ DECK A      DECK B    │ CUE · Friday Night   │
│                      │ New  Load  Save  ⋯   │
│                      │ AUTO_CUE [OFF / ON]  │
│                      │ ≡  Song one   A B ×  │
│                      │ ≡  Song two   A B ×  │
│                      │ ≡  Song three A B ×  │
│                      ├──────────────────────┤
│                      │ FIND A SONG          │
│                      │ Search…  Categories  │
│                      │ Song       +CUE A B  │
│ Fade length          │ Song       +CUE A B  │
└──────────────────────┴──────────────────────┘
```

## Compact interface

- Use a named Cue header with New, Load, Save, and a small overflow menu for Save as and rename. Show song count, total duration, and autosave status without an extra large header.
- Give Cue and search results independent scrolling and a draggable height divider. Keep search and Cue controls visible while their lists scroll. Store the divider preference locally.
- Aim for 48–56 px desktop rows: drag handle, order, title/artist, duration, LOAD A, LOAD B, remove. Use subtle NEXT, ON A, ON B, and PLAYING labels. Full metadata remains accessible when text is truncated.
- Reduce browser panel padding, artwork size, row gaps, and category spacing. Use a single horizontal action group rather than vertically stacked buttons. Target at least six Cue entries and six search results at 1440 × 900, then verify actual fit with the decks and header.
- Retain readable type, visible focus, and comfortable touch controls. Stack panels on narrow screens; preserve vertical scrolling by limiting touch reordering to handles.
- Add + CUE to results. Dropping a result onto Cue inserts at the highlighted position; + CUE appends. Cue entries drag onto either deck or reorder within the list. Provide keyboard move-up/down alternatives and clear drop feedback.
- Search and category changes update results in place, preserving Cue position, focus, and ongoing playback. Include pagination/load more instead of keeping the current fixed result limit.

## Manual Cue behavior

- Loading an idle deck prepares the song; PLAY / TAKE AIR remains the action that broadcasts it. Preserve the existing confirmation when replacing a playing deck.
- Loading, previewing, or dragging a song does not rotate the list. A confirmed natural finish of an aired Cue entry moves that exact entry to the bottom, with AUTO_CUE on or off.
- Associate playback with a Cue entry ID, not only the song ID. Allow intentional duplicates and rotate only the entry actually used. A song loaded directly from search does not move a matching Cue entry by coincidence.
- A manually played song outside Cue can still trigger AUTO_CUE at its natural end.
- Pausing does not count as completion. Clearing, replacing, or fading out early leaves the interrupted entry in place. A deliberate repeat completes before AUTO_CUE advances; rotate the original Cue entry once after its final repeat finishes.
- Editing or removing an entry never interrupts audio already playing. An entry removed during playback must not reappear when that playback finishes.

## AUTO_CUE contract

- AUTO_CUE is a DJ Booth control, distinct from the station's schedule AUTO mode. Default off. Display its state and next song explicitly.
- Turning it on during playback arms the next handoff without interrupting the current song. If the booth is idle, enabling it explicitly starts the first playable Cue entry. A paused deck remains paused until the DJ resumes it.
- At the natural end of the current program song, start the first eligible entry in current Cue order. Rotate the completed Cue entry first so a one-song list intentionally repeats and longer lists cycle in order.
- Use a server/engine handoff, not a browser countdown. Prepare the next request ahead of the ending where practical, but do not start it early or apply the manual crossfade duration to this end-to-start transition.
- Prefer a free deck; otherwise reuse the deck that just finished. Preserve a song the DJ has manually prepared on the other deck. Do not advance while another deck is still airing music or a manual transition is in progress.
- Manual deck actions win over a pending automatic handoff. Cancel/reconcile the prepared automatic request when the DJ changes the next entry, loads another song, changes mode, or disables AUTO_CUE. Never allow both actions to take air from one completion.
- Pause, stop/clear, and explicit fade-out suspend automatic advancement rather than unexpectedly restarting music. Show the suspension and allow explicit re-arming. Existing station fallback still applies where appropriate.
- Cart overlays do not advance Cue. Takeover carts suspend the handoff until the program resumes. Live microphone and station AUTO modes suspend/disarm AUTO_CUE; returning to DJ Booth requires an explicit re-arm.
- Preserve an armed AUTO_CUE across browser navigation and refresh. Playback must not depend on any tab remaining open. Recover worker restarts using durable playback identity and consumed-event records; an engine restart or missing observation is not a natural completion.
- Skip unavailable/disabled/missing entries with a visible reason, keeping them in the list. Make at most one pass through the list per selection attempt. If none are playable, suspend AUTO_CUE and use the existing station fallback with a clear notice.
- Empty Cue follows that same fallback. Turning AUTO_CUE off lets the current song finish and prevents subsequent automatic starts.

## Working list and saved lists

- Maintain one durable active Cue per station, shared by its authorized booth operators. Autosave additions, order changes, removals, and completed-song rotations to the server.
- Restore that working list after refresh, sign-out/sign-in, browser changes, and service restarts. Show Saving, Saved, or Retry rather than implying a failed edit persisted.
- Save creates or updates a named snapshot of the current order. Save as creates another named list. Playback rotation updates the working Cue without silently rewriting a saved snapshot.
- Load replaces the working Cue with a selected saved list in its saved order. New starts an empty working Cue. Both disable AUTO_CUE and cancel any automatic request that has not started; current audio continues.
- If Load or New would replace unsaved changes to a named snapshot, offer Save / Discard / Cancel. The active draft is autosaved, but the DJ should not accidentally lose a set when explicitly replacing it.
- Use a working-list revision to detect competing edits from tabs/operators. A stale edit should refresh with an explanation rather than overwrite a newer order. Bind pending playback to the active Cue generation so completion from a previous list cannot modify the newly loaded list.

## Implementation map

1. **Persistent data and Cue service.** Add station-scoped active Cue state, ordered entries with independent IDs, saved Cue lists/items, revisions, and playback-to-entry associations. Keep Cue separate from scheduling playlists: existing `PlaylistItem` enforces one instance of each track, and playlist cursors implement scheduling behavior. Reuse availability checks and authorization patterns. Add a migration and migration validation/rollback plan.
2. **Authenticated API.** Extend `app/routes/admin_live.py` and live status with Cue read/edit/reorder, save/load/new, AUTO_CUE state, and entry-aware deck loading. Use CSRF, station permissions, revision checks, and idempotent mutation IDs. Centralize behavior in a new Cue service instead of adding selection logic to route handlers.
3. **Completion and handoff.** Extend `deploy/liquidsoap/station.liq.template`, `app/services/playout_queue.py`, and `app/automation_worker.py` to identify natural completion separately from pause, clear, replacement, repeat, and failures. Process each completion once, rotate the associated entry transactionally, and reconcile preparation/start acknowledgements. Add AUTO_CUE before `return_to_auto_if_stopped()` so the current fallback cannot race the next Cue song. Explicitly route Cue requests to DJ deck queues; current Deck A routing depends on `deck_load`/`deck_repeat` reasons.
4. **Booth UI.** Update `app/templates/admin/live.html`, `app/static/live.js`, and booth styles. Prefer a small dedicated Cue module/partial. Extend the existing pointer drag behavior for insertion, reorder, and dynamically rendered results; avoid duplicate handlers on status refresh. Rework layout sizing rather than adding another layer of conflicting grid-row overrides. Preserve the shared A/B deck alignment.
5. **Validation and rollout.** Validate migrations in a fresh test environment, run the regression suite, then exercise isolated real-engine playback and browser interactions. Review the migration and generated engine configuration before any production rollout; deployment is separate from this planning task.

## Acceptance checks

- Build and reorder Cue while A plays; load B by button and drag; confirm current audio is uninterrupted.
- Naturally finish a Cue song and observe exactly that entry move to the bottom once, including repeated tracks and worker event replay.
- AUTO_CUE continues after a song loaded from search and after a Cue song, cycling at least three entries with the browser closed.
- A one-entry Cue repeats intentionally. An empty or entirely unavailable Cue cannot retry forever or leave automatic takeover stuck.
- Pause, early fade, manual replacement, repeats, both decks active, cart takeover, live mic, and mode switches follow the contract above.
- Reorder/remove the upcoming song during preparation; disable AUTO_CUE just before completion; verify no stale request starts.
- Load another list or create New during playback; the old song finishing does not reorder the new list or restart disabled AUTO_CUE.
- Refresh/restart and two-tab edits preserve state without duplicate rotation, duplicate starts, or lost updates. Saved snapshots retain their saved order until explicitly saved again.
- Verify permission boundaries, CSRF, unavailable tracks, failed saves, connection recovery, and database migration upgrade/downgrade.
- Check desktop and mobile fit, touch/keyboard drag alternatives, long titles, themes, reduced motion, and search pagination. Record isolated audio to verify the actual end-to-start handoff and measure any silence rather than inferring success from UI timers.
