# Reusable Blocks and calendar scheduling

A Block is a saved 24-hour format. Saving a Block stores its content; day assignments determine what Blocks mode plays. Calendar mode instead follows calendar placements, including reusable Blocks. Simple mode can select a saved Block directly and repeat its 24-hour format from activation time, without a day assignment.

## Create, reopen, and schedule

1. Open Blocks, choose New or a saved Block card, and name the format.
2. Drag a playlist, Show, category, artist, album, or song into the timeline. The first collection fills the remaining day. Select a section to adjust its start/end using the sliders or exact time fields. The explicit 24:00 option represents the end of the day. Slider changes apply when released; exact fields use Apply times.
3. Save Block. The saved-content status, coverage status, and day-assignment status are separate. The last opened item is restored when the workspace reloads. Opening another item reads its latest saved version and asks before discarding content edits. Unsaved edits remain recoverable after navigation.
4. For Blocks mode, choose Assign days. One day defaults to the selected station-local date; weekdays, daily patterns, and selected dates are also available. Save assignment persists the assignment immediately. Use Blocks previews the effective source for the current station-local time before requesting a playback handoff.
5. For Calendar mode, choose Add to Calendar, or use the Blocks library tab in Calendar. Dropping a Block places a midnight-to-midnight entry on that date. Review exact times and recurrence as needed. Calendar placements save automatically. Use Calendar controls playback for those entries.

6. For Simple mode, open the Blocks tab in the content library. Drag a Block into the selection area or click its + button, save, and confirm Use Simple (or Change what plays). It starts at the beginning when activated and repeats every 24 hours. Saving a new selection does not change current playback until the confirmed handoff. Simple retains the selected saved version, including after a worker restart.

Three saved Blocks can be placed on separate dates or repeated through calendar recurrence. Calendar references retain a specific saved version. Editing a Block creates a new content version; existing placements keep their version until Apply to future uses is explicitly selected. Saving an unchanged Block or assigning dates does not create another content version. Day assignments display their version separately from the version open in the editor.

Block times are relative to the start of a calendar placement. Moving a placement shifts the format with it; shortening a placement ends that occurrence early rather than stretching the format. Nested Shows retain their own durations and repeat within their section. Existing song-boundary behavior and timed-event policy continue to apply.

## Diagnostics and controls

Activation distinguishes an unassigned day, an empty section, unavailable content, and an unavailable default playlist. A saved but unassigned Block is not an empty or failed save. The unassigned preview offers Assign days directly. Timeline gaps identify the configured fallback or explicitly state that none is configured.

Timeline zoom changes the visible scale without changing section times. Resize handles retain snapping, scrolling, cancellation, and Undo/Redo. Exact second values are preserved when switching between the time fields and range controls. The assignment retry retains one identity after a lost response, preventing duplicate assignments.

## Deployment

No schema migration or Liquidsoap configuration change is required. The existing worker resolver already supports Block compositions and nested Shows; calendar validation now permits station-owned Block references. Reload the web application and refresh the browser to load the new versioned assets. Scheduling and activation remain operator actions.

## Verification

Validation uses disposable SQLite databases, temporary media and browser profiles, and isolated Liquidsoap sockets/recordings. Production schedules are not test fixtures. Tests cover saved/unassigned diagnostics, station ownership, revisions, overlap rejection, three calendar Blocks, nested Shows, daylight-saving changes, playlist cursor recovery, browser save/load, sliders, resizing, cancellation, responsive layout, and assignment response-loss retry. Engine tests cover Blocks and Calendar handoffs with no event, a waiting event, and an event already playing.

### Completed validation

- Final targeted service/API/editor run: 56 passed. The separate long-running legacy 370-day import comparison was excluded; it is unrelated to Block content placement.
- Earlier scheduling/booth integration regression run: 58 passed, including the worker/booth interaction checks.
- New browser scenarios passed: saved/unassigned/reopen/assign/preview; pointer sliders, exact seconds, resize, zoom and cancellation; three calendar Blocks and direct calendar placement; touch/keyboard sliders and assignment retry after a lost response.
- Existing browser scenarios passed: Show editing, Block weekday assignments, station-control mode switching, and both calendar autosave/recovery scenarios. All nine distinct browser scenarios passed across the runs. Final focused rerun: 2 passed after fixing the source-name compatibility case and waiting for placement validation before asserting save completion.
- Isolated Liquidsoap: 6 passed, covering Blocks and Calendar with no event, a waiting event, and a playing event. Audio fade, engine acknowledgement, correct mode, and retry behavior were asserted.
- JavaScript editor tests, syntax checks, and `git diff --check` passed.
- Gracefully reloaded the running web workers. Authenticated live smoke checks verified the new HTML/assets, Block activation diagnostics, and Chill Night as valid Calendar content. Calendar and day assignments were unchanged. Web, database readiness, automation, and Icecast health returned `ok`.

Logs: `/tmp/freo-block-validation.log`, `/tmp/freo-block-regressions.log`, `/tmp/freo-block-engine.log`, `/tmp/freo-block-browser-2.log`, `/tmp/freo-block-browser-final.log`, `/tmp/freo-block-browser-rerun.log`, `/tmp/freo-block-js-tests.log`. The earlier browser logs retain failed attempts alongside the passing scenarios; the focused rerun resolves their outstanding failures.

### Simple content support

Blocks are also available in Simple's content library. Both saving and explicit mode handoff validate Block ownership and the selected saved version. The existing elapsed-time resolver starts the format at activation, advances through its sections, and repeats after 24 hours; it does not depend on day assignments. Saving another selection or editing the library Block does not silently replace the live selection.

Validation: 21 service tests passed, including Simple save/preview/handoff, elapsed section boundaries, repeating, version retention after a worker session restart, and rejection of foreign or invalid versions. The isolated browser workflow passed clicking and dragging Blocks into Simple, save/reload, and confirmed handoff. An isolated Liquidsoap test passed the real Simple Block handoff and audio fade. The web workers were gracefully reloaded; the authenticated live Simple preview resolved Chill Night as playable without changing the saved selection, mode, or schedules. All four live health checks passed.

Logs: `/tmp/freo-simple-block-services.log`, `/tmp/freo-simple-block-browser.log`, `/tmp/freo-simple-block-engine.log`.
