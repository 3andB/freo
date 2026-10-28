# Music import, Music, and calendar implementation plan

Requested September 19, 2026; implementation authorized with “go”. The changes below are now implemented in the working tree. The investigation and acceptance plan are retained for review; validation results are recorded in [music-and-calendar-validation-2026-09-19.md](music-and-calendar-validation-2026-09-19.md).

Baseline validation: `tests/test_schedule_editor.py`, `tests/test_schedule_editor_browser.py`, and `tests/test_schedule_studio_browser.py` completed with **9 passed in 203.02 seconds**, using an isolated database and temporary media. Log: `/tmp/freo-calendar-plan-tests.log`. The first sandboxed attempt could not bind the browser fixture's local server; the permitted rerun completed successfully. These results establish the existing coverage baseline, not resolution of the reported issues.

## Findings before implementation

- `media_upload.js` opens `list[0]` on entry, including completed imports. Its session summary counts finalized submissions as imported, even when a job still needs attention. Completion must be based on actual results.
- Import rows after the first start hidden (`editor.hidden=items.size>0`), and the additional song fields are in a closed details element.
- `music.css` reduces the drop zone from 140px to 60px once files are present.
- Categories and tags already exist in import metadata. Playlist membership and channel availability are absent from the shared metadata validator and need durable handling through ingest.
- Music already has individual channel availability controls and playlist/category/tag assignment actions. Its selection toolbar lacks the requested all-channels action.
- Availability already supports the requested sharing behavior: make a song available to all stations on the server. Reuse this rule and retain the existing storage/catalog owner.
- `/calendar` renders Schedule Studio. The active implementation is `schedule_studio.js`, `schedule_editor.js`, and `visual_schedule.py`; the older `calendar.js` is not the editor to fix.
- A recurring block's drag/resize completion explicitly opens the full inspector. This explains at least some unwanted details dialogs.
- Short calendar blocks hide resize handles. All blocks display the repeat symbol, including one-time entries.
- The renderer draws overlapping definitions at the same horizontal position. Playback gives dated overrides priority over recurring schedules; the visual rendering does not resolve that priority into effective coverage.
- Recurrence collision handling differs between local editing and server validation. The local editor only trims overlapping one-time definitions; recurring conflicts can reach the draft before the server rejects saving.
- Time inputs wrap at midnight. Overnight edits need explicit end-date/day-offset representation so a displayed end time cannot silently change the duration.

## 1. Finish and reset the import workspace

On returning after a completed import, show a blank workspace ready for new songs. Retain completed results in import history without automatically reopening them. Reuse an empty workspace or create one lazily to avoid accumulating empty sessions.

Preserve unfinished uploads, review drafts, active processing, and failed jobs in a clearly labeled resume/status entry. Mixed batches must not lose unimported songs when their successful songs finish. Explicitly opening an existing workspace should still work. Test both normal reload and in-app navigation.

Keep every new song's information expanded, including useful classification fields. Preserve deliberate user collapse/expand choices through metadata polling, regrouping, and adding more files.

Use a stable, spacious drop zone: approximately 220px minimum on desktop and 160px on narrow screens, with centered copy and file/folder actions. Keep it tall after songs are added and keep the import button clear of the preview player.

## 2. Apply artist and album to the batch

Add **Apply artist & album to all** to each song. Copy the source song's effective artist and album, including edited or detected values, to all eligible songs in the current workspace regardless of selection or display filter.

Preserve titles, track/disc numbers, artwork, and classifications. Resolve catalog identities and album ownership consistently, including explicit empty albums. Save the batch atomically with revision checks and provide Undo. Clearly report skipped duplicates or entries currently locked for processing. Already imported entries still open in the workspace need an explicit, supported update path rather than silent omission.

## 3. Organize songs while importing

Reuse Music's button, picker, chip, selection, and feedback patterns for playlists, categories, tags, and **Available to all stations**. Support per-song edits and selected-song bulk actions, with a clearly marked option to apply defaults to subsequently added files.

Save assignments in the draft and carry them into the ingest job. Validate destinations and permissions again at finalization. Apply memberships after a track exists using existing playlist/catalog services. Preserve playlist order and make retries idempotent. Report assignment failures as actionable failures instead of displaying a fully successful import.

User clarification: sharing simply makes a song available to every station on the server, including stations added later, using the existing availability flag. No selected-station picker, ownership transfer, or new sharing relationship is needed. Keep STATION/COMMERCIALS classification distinct from channel availability and retain existing restrictions on sharing nonmusic audio.

## 4. Add the Music bulk action

Add **Make Available to all channels** to the selection toolbar. Apply it to the explicit selected set across pagination, show the affected count, reuse availability validation and auditing, and refresh availability badges. Do not reinterpret this as every track in the library. Preserve inherited artist/album availability semantics.

## 5. Correct the calendar interaction and data model

First reproduce the reported failures with real browser pointer actions and record the date, view, recurrence, scroll position, and before/after schedule values. Extend coverage to both handles, recurring entries, and overnight fragments; existing horizontal-move and bottom-resize coverage is insufficient on its own.

Use explicit idle, selected, moving, and resizing states. A drag must consume its following click. Keep pointer capture and cleanup reliable through rerenders, cancellation, loss of capture, and page navigation. Use consistent coordinate-to-time conversion for normal and compressed hours, scroll, snapping, and cross-day movement. Preserve duration when moving; resize only the chosen edge. Show live start/end times and the proposed position before release.

Single click selects a block. An explicit Edit action, double click, or keyboard command opens details. Recurring moves/resizes use a compact scope choice: **This occurrence**, **This and following**, or **Entire series**. Show the affected date range and allow cancellation without changing the draft. Ordinary drags should not open the full details form.

Provide accessible top and bottom resize targets. Very short blocks need selected-block handles or a precise time editor without expanding their rendered duration. Add explicit overnight end-day information, minimum duration validation, and safe midnight boundary handling.

Keep canonical schedule definitions separate from rendered day fragments. Make drag, resize, the detail editor, undo/redo, saving, and reloading use the same edit semantics. Preserve recurrence anchors, intervals, exceptions, and following-series boundaries unless the user changes them deliberately.

Resolve visible effective coverage using the same dated-override priority as playback. Represent suppressed recurring coverage clearly. Detect conflicts before publication and identify the dates and entries involved. Save responses should include the authoritative normalized document and revision; incorporate them without overwriting edits made while a save is in flight. Provide recovery for stale revisions and failed saves.

## 6. Make repeating schedules manageable

Proposed default: **Compact recurring schedules**, with **Show all / Compact / Hide** controls and a station-specific remembered preference.

Render recurring coverage as quiet background bands in compact mode. Keep one-time additions, changed occurrences, selected entries, and conflicts prominent. In Hide mode, show a hidden-item count and a reveal control. Filtering must not change playback or make occupied time appear to be free; collision checks and coverage calculations still include hidden schedules.

Add search and source-type filters. Group repeated entries in Agenda; limit Month cells to a few entries with a **+N more** action. Put timed announcements/events in their own lane and include recurrence metadata in their API response so the same visibility controls can handle them. Keep recurrence dates and content-looping indicators distinct.

Preserve the visible time and scroll position when refreshing, changing filters, or saving. Use clear selected states, readable labels, keyboard editing, and touch-friendly controls across Day, Week, Month, and Agenda.

## Delivery and acceptance

Implement as reviewable stages: import lifecycle/layout; shared metadata and organization; Music availability; calendar correctness; calendar density and interaction polish. Establish calendar reproductions at the beginning so they guide its repair.

Acceptance scenarios:

1. Import an album, leave, and return to an empty importer; unfinished/failed work remains recoverable.
2. Add several batches: every new song stays expanded, the drop zone stays spacious, and preview playback never covers Import.
3. Apply one song's artist/album to all, Undo, reload, and verify unrelated fields and catalog relationships.
4. Import with playlists/categories/tags and all-station availability, interrupt and retry processing, and verify exact memberships and availability without duplicates.
5. Share selected Music songs with all channels and verify discovery and playback eligibility in another channel, including inherited sharing.
6. Move and resize both ends of one-time, recurring, short, full-day, and overnight blocks in Day/Week views; verify exact draft, saved, reloaded, and playback-resolution times.
7. Verify recurrence scope, exceptions, monthly rules, station timezone/DST boundaries, hidden-item conflicts, cancellation, Undo/Redo, slow saves, and concurrent edits.
8. Verify recurrence filtering across all views, including repeating timed events, dense schedules, narrow screens, and keyboard interaction.

Run the relevant browser/service suites and then the repository's required full pytest checks during implementation. Reuse the existing all-station availability model; no new sharing migration is planned. Production data is not needed for these checks.
