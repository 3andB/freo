# Music and calendar changes — September 19, 2026

Implementation follows the [approved plan](music-and-calendar-plan-2026-09-19.md).

## Delivered behavior

- Returning to Music Import opens an empty workspace after submitting a batch, including while background analysis continues. Drafts and failures remain recoverable; the history menu distinguishes processing, completed, and unfinished batches.
- Song details and classification controls start expanded. The upload area stays at least 220px tall on desktop and 160px on mobile.
- Each song has **Apply artist & album to all**, with Undo, revision checks, and support for editing songs already imported in that workspace. Duplicate tracks retain their existing metadata.
- Import supports playlist, category, and tag membership, audio classification, and availability to all stations. Batch organization can also supply defaults for subsequently added files. Failed imports can have unavailable destinations corrected before retrying.
- Music has **Make Available to all channels** for selected songs. It uses the existing server-wide availability flag, including future stations, and preserves ownership.
- Music's bulk toolbar uses compact inline labels and observes wrapping changes, keeping song drop targets clear of the preview player after adding the sharing action.
- Calendar single click selects; Edit details, double click, or Enter opens the editor. Native source drops place content directly. Dragging and both resizing edges preserve exact schedule times; short blocks expose usable handles when selected.
- Recurring moves and resizes use a small scope dialog. Cancelling during server validation discards the proposed edit. Calendar edits are validated before entering the draft, and saves use the server's normalized document without overwriting newer edits.
- Overnight editing identifies Same day versus Next day. Recurrence anchors, exceptions, interval rules, and occurrence scope are preserved.
- Show all / Compact / Hide controls, source and text filters, grouped recurring Agenda entries, bounded Month cells, an event lane, and an expandable calendar reduce clutter. Hidden schedules retain visible occupancy; dated overrides match playback priority.

## Verification

Checks use isolated databases and temporary media. No production migration or data change is required.

- JavaScript scheduling unit tests: **9 passed**.
- Scheduling Python/API tests, including JavaScript/Python recurrence parity across 430 dates: **3 passed**.
- Import, metadata, and availability service regression run: **44 passed**.
- Disposable PostgreSQL integration run: **7 passed**, including concurrent playlist assignment and sharing.
- Focused browser run: **4 passed**, covering expanded imports, apply-all and Undo, organization and sharing, empty return, pointer moves and both resize edges, cancelled validation, short blocks, and native source drops.
- Final importer/browser/API run: **33 passed, 4 warnings in 577.80 seconds**. This includes all ten importer/calendar browser scenarios and the final blank-return behavior while analysis is still running. Log: `/tmp/freo-final-import-calendar.log`.
- Additional details-editor cancellation check: **1 passed in 50.17 seconds**, confirming that closing the inspector during validation leaves the existing draft unchanged. Log: `/tmp/freo-calendar-details-cancel.log`.
- Final Music toolbar regression run: **2 passed in 92.31 seconds**, covering tag drags in both directions, preview, Undo, category editing, notes, mobile layout, and the importer/bulk-sharing workflow after the toolbar fix. Log: `/tmp/freo-music-toolbar-final.log`.
- Final station-sharing and remaining workspace checks: **2 passed in 63.63 seconds**. Log: `/tmp/freo-final-sharing-workspace.log`.
- `git diff --check` and JavaScript syntax checks pass.
- Repository-wide attempt: the reporter recorded **816 passed, 59 skipped, and 6 failures** before the process ended with exit code 143 after 881 of 882 checks. These are counts from the progress log, not a normal pytest completion summary. The remaining workspace test passed separately in the final two-test run above. Log: `/tmp/freo-full-suite-20260919.log`.

The full repository run encountered `test_starter_migration_preserves_custom_and_renamed_playlists`: a duplicate `radio_browser_uuid` column while upgrading a database already built from current models. The same failure was reproduced against an untouched archive of `HEAD` in `/tmp/freo-baseline.aznCwT`; it predates this change. Log: `/tmp/freo-baseline-migration-check.log`.

The full run began before the final importer return behavior and its browser expectations were updated. It therefore executed the previously collected `test_amber_state_incremental_upload_and_edit_in_place`, which expected a plain refresh to restore imported rows. The updated test explicitly reopens the historical workspace and passed in the final 33-test run above. Its timeout in the earlier full run does not describe the final test version.

`test_processing_permission_error_is_actionable` passed independently on the changed code. Its full-suite logging assertion fails because the migration setup disables existing loggers. This was reproduced on untouched `HEAD` by registering the audio-analysis logger before running the migration and logging tests; both then fail identically. Logs: `/tmp/freo-isolated-audio-logging.log`, `/tmp/freo-baseline-existing-logger.log`.

`test_operations_station_switch_back_and_mobile` timed out during station navigation in the full run, then **passed in 37.05 seconds** in isolation on the changed code. On untouched `HEAD`, the same test fails its JavaScript-error assertion with `live.js:339` attempting to set `disabled` on a removed element. The original DJ Booth/navigation implementation is unchanged. Logs: `/tmp/freo-baseline-station-navigation.log`, `/tmp/freo-current-station-navigation.log`.

The full run found a Music toolbar regression: after adding the sharing action, stacked classification labels pushed the song drop target behind the preview player. This was reproduced and corrected with compact inline toolbar labels and resize observation. The existing browser test also needed to retry a click when polling replaced its inspector button; that separate stale-element failure was observed on unchanged `HEAD` as well. Both final browser workflows passed after these corrections, as recorded above.

`test_add_limit_delete_and_share_in_browser` still expected the individual availability form to redirect after saving. Its unchanged JavaScript saves inline; the same timeout was reproduced on untouched `HEAD` (`/tmp/freo-baseline-sharing-redirect.log`). The updated test passes: it waits for the success message, checks the persisted availability flag, and verifies that another station can see the song.

All affected workflow checks pass after the corrections and targeted reruns. The migration and resulting logging-isolation failures remain baseline limitations; a completely green, uninterrupted full-suite run is not claimed.
