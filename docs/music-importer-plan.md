# Music importer review and plan

Date: 2026-09-18. Status: implemented in the working tree. See [implementation, testing and rollout](music-importer-testing.md). The findings below describe the original review.

## Outcome

Make adding one song, several unrelated songs, or an album feel like the same simple task: add music, review the detected details, and import. Creating an artist must immediately select it for the intended songs and make it available throughout the import. Adding another song must work without refreshing or restarting.

## Findings and evidence

The review covered the upload page, shared artist/album controls, metadata reader, catalog endpoints, ingest worker, audio processing, song editor, navigation, and existing tests.

| Finding | Evidence | Effect |
| --- | --- | --- |
| Creating an artist refreshes only its originating selector. | `catalog_controls.js` replaces the selector's private `data`; `media_upload.js` keeps the initial catalog for later cards. Reproduced in Chromium with Amber State. | First song can select Amber State; a second song and the batch selector cannot see it. The same architecture affects album creation. |
| Song metadata controls stay disabled after upload. | Browser reproduction and the upload handler. | Correcting an uploaded song requires following a separate Edit song link once a track exists. |
| Batch controls replace classifications even when untouched. | Browser reproduction: a selected category was cleared by applying the otherwise untouched batch form. | Applying an artist can accidentally remove categories or tags. |
| Returning to file metadata is ambiguous and ineffective in batch operations. | Browser reproduction: the first song retained Amber State after applying the batch defaults. `values()` omits unset fields, and `set()` merges rather than resets. | The displayed batch choice does not describe the resulting song choices. |
| Artist-only batch changes can retain an incompatible album selection. | Code inspection: batch `set()` does not run the artist-change handler's album reset. | Upload can fail with a generic metadata error. |
| Album preparation repeats a large form for every track. | Template, stylesheet, and rendered browser review. | Even two songs require substantial scrolling; an album duplicates shared controls and artwork actions. |
| Metadata preview is inconsistent across formats. | The browser reader handles a subset of ID3 v2.3/v2.4 text frames. Full format probing occurs in the ingest worker. | FLAC, M4A, and many WAV files can appear to lack metadata before import despite having it. Disc number, album artist, and embedded artwork are not reviewed locally. |
| Shared choices are a one-time copy. | `apply-batch` only visits current selected items without jobs. | Later additions do not inherit a deliberate album setup. |
| Status does not reconcile the displayed artist/album with saved metadata. | Polling updates status, preview, and sometimes title, but not artist/album controls. | The completed import does not clearly show what was actually saved. |
| Retry and navigation lack a durable import workspace. | Files and job references live in the page's `items` array; uploads use independent XHRs. | Reloading loses the working list. Server-accepted jobs continue, but the importer cannot reconstruct the session. A lost upload response leaves an uncertain result. |
| Duplicate detection discards the incoming metadata choices. | `media.ingest()` returns an existing checksum match before applying overrides. | A second import cannot be used to correct the existing song; the UI should make this explicit and offer editing. |
| Compilation support needs a catalog decision. | Albums belong to an artist; validation requires song artist and album artist IDs to match. | A compilation cannot cleanly remain one album while preserving distinct performing artists. |

Validation completed: 10 existing catalog/editor tests passed. An isolated browser diagnostic also passed, confirming the stale artist lists, classification clearing, failed batch reset, and disabled controls after upload. It used a temporary database and synthetic files; it did not inspect or change the user's actual songs. The diagnostic upload checked browser/staging behavior, not audio processing. The user's exact sequence remains unconfirmed, so both selection-before-upload and editing-after-upload are covered by this plan.

## Proposed experience

One workspace adapts to the files selected. Users do not need to pick a mode before adding files.

| Selection | Main presentation | Typical work |
| --- | --- | --- |
| One song | Title, artist, optional album, preview; expandable additional details. | Check detected details and import. |
| A few songs | Compact selectable rows with title, artist, album, duration, and status. | Correct individual rows or select several and change shared fields. |
| An album | One album header with artist, title, cover, and optional year; rows underneath show track numbers and titles. | Set album details once, review order, and import the album. |
| Several folders/albums | Separate suggested album groups plus ungrouped songs. | Review each group without forcing one artist or album on everything. |

The primary action remains visible: **Import song**, **Import 8 songs**, or **Import album · 12 songs**. It reports the eligible selected count. Show **Needs attention** as a filter, and keep additional metadata collapsed until needed. On mobile, use compact expandable rows and a reachable action bar. Keyboard navigation and screen-reader labels must identify the target song and affected selection.

### Add music and detect details

- Accept the existing audio formats through files, folder selection, and drag/drop; allow more files to be added throughout the session.
- Stage files with visible upload progress so the server can inspect all supported formats before final import. Explain: “Preparing files for review. They enter your library when you import.”
- Reuse the existing worker's trusted probing and preview facilities. Extract title, performing artist, album, album artist, disc/track number, year, duration, and cover into draft items. Metadata-only edits must not trigger another audio upload.
- Suggest album groups from album title and album artist. Use folder names only as fallback suggestions, and make grouping reversible. Never overwrite differing performing artists merely because files share a folder.
- Prefer embedded track/disc numbers; flag missing or repeated numbers. Offer numbering in the displayed order rather than silently renumbering.
- Display detected and user-entered values clearly. Late metadata extraction fills untouched fields only. Missing artist/title gets an actionable warning; valid audio can still be imported with an explicit fallback choice.
- Skip unrelated folder files with a count. Offer a detected `cover.jpg` or `folder.png` as artwork. Explain unsupported, empty, or oversized audio next to the affected file.

### Select or create an artist

- Replace the separate search box, select, and add panel with one searchable artist field.
- Typing a name shows existing matches and, when appropriate, **Create “Amber State”**. Use the server's canonical identity normalization; an exact existing match is reused.
- Creation selects that artist immediately. The control states its scope: this song, this album, or the selected N songs.
- Use one station-scoped catalog store for every selector. Successful create/reuse updates all controls and any subsequently added songs without page reload.
- Return the canonical saved artist/album from the create API so creation does not depend on a second fetch succeeding. Handle concurrent creation by returning the existing match.
- Newly created artists become available everywhere; they are assigned only to the stated target. Unrelated songs keep their artists.
- Album creation follows the same interaction. Typing Enter chooses/creates the highlighted result; Escape closes suggestions; errors retain the typed name and focus.

### Edit shared details without losing individual work

- Album headers hold shared album values. Rows inherit those values unless explicitly overridden. Adding another track to that album inherits its current settings; adding unrelated music does not.
- Outside album groups, the selection toolbar edits only selected rows and only fields explicitly changed. Report “Artist updated on 4 songs.”
- Keep distinct operations: **Leave unchanged**, **Use file metadata**, **Choose a value**, and **No album**. Empty input must not ambiguously mean all four.
- Tags/categories support **Add**, **Remove**, and an explicit **Replace all**. Ordinary bulk edits default to adding classifications and leave untouched fields alone.
- Validate artist/album relationships immediately. Never submit an invisible stale album ID. Explain any dependent change next to the fields.
- Give batch changes an Undo action before import; keep a short description of the affected count.
- Allow optional category assignment with a plain explanation of rotation eligibility. Distinguish “Imported” from “Ready for rotation.” Preserve the current enable-after-success default and offer **Keep disabled** before final import.
- Treat cover art as optional. Show existing album artwork and explain when replacing it will also affect that album's existing tracks.

### Import, correct, and recover

- Keep one row per song through preparation, review, import, processing, success, duplicate, and failure. Show overall counts as well as per-file progress.
- Do not leave completed rows as disabled forms. Render saved metadata with **Edit details** opening an editor in the same workspace.
- During finalization, briefly hold metadata edits and then direct them to the created track; never accept edits that cannot be saved. Editing after import requires no re-upload and preserves processing/broadcast state.
- On duplicate detection, show **Already in library** with **View / Edit existing song**. Incoming edits do not silently overwrite the library copy.
- Retry failed items only. A lost response is reconciled by a stable item identifier before another upload or import is attempted.
- Persist draft metadata, accepted uploads, job IDs, and completed results in the import session. Returning to a session restores its state. Files never fully uploaded may require reselection after a reload; do not promise transparent recovery of browser-local bytes.
- Removing an unimported row cancels/removes its draft. Removing a completed row only dismisses it from this view. Library deletion stays a separate action.
- Show completion counts and links to the imported album/songs, plus **Add more music**. Persist changes before navigation, and warn only when local edits or unfinished uploads would actually be lost.

## Implementation sequence

### 1. Repair current selection behavior

Change `catalog_controls.js` and `media_upload.js` to share catalog updates, apply explicit field patches, reset incompatible albums, and distinguish selection scope. Refresh saved metadata in result rows and provide an in-place edit path once a track exists. Add the Amber State regression first, including a first song uploaded before a second is added.

This can ship independently of the larger redesign. No schema change is needed for these repairs.

### 2. Build the compact review workspace

Update `media_upload.html`, `music.css`, and importer JavaScript. Separate import state from DOM elements so grouping, selection, inheritance, status, and undo operate on explicit data. Reuse the shared artist/album control in the importer and song editor. Add compact rows, album headers, selection toolbar, and persistent primary action.

Use explicit field modes in UI state; resolve these to validated metadata overrides at the API boundary. Keep detected metadata separate from overrides and saved results. Do not depend on `undefined`, omitted fields, and shallow object merging to represent user intent.

### 3. Add durable preparation and review

Add station-scoped import sessions and items with additive migrations. An item holds a stable client identifier, file identity, stage/job references, detected metadata, overrides, revision, status, errors, and final track reference. Server endpoints create/resume a session, stage a file, update a draft, finalize selected items, and return aggregate status.

Preparation must not create an enabled library song. Split probing/preparation from final catalog creation; retain the existing trusted storage and ingest-worker boundaries. Define draft size/count limits, expiry, cancellation, and cleanup for staged audio, previews, and unreferenced artwork. Adjust existing staging cleanup, which currently uses job status and a 24-hour cutoff, so it cannot discard a live draft unexpectedly.

Use revision checks when applying draft edits/finalizing, idempotency per item for upload/finalize retries, and a server-owned transition from draft to track. Finalization snapshots validated choices; subsequent edits target the track after creation. Worker retries must not apply old metadata over a later correction. Use a bounded upload queue and one session status request rather than polling every song separately.

### 4. Complete album and recovery behavior

Finish full-format metadata review, artwork selection, disc ordering, multi-folder grouping, retry/reopen behavior, and post-import editing. Add a regression for each transition, including manual disable during analysis.

For compilation albums, separate album artist from performing artist in validation and grouping. Existing `Track.artist_id`, `Track.album_id`, and `Album.artist_id` relationships can represent this, but the current editor rules, organizing logic, artist pages, and shared-catalog visibility assume they match in places. Review these consumers together and backfill album-artist metadata where appropriate. Do not solve compilations by replacing every track artist with “Various Artists.”

### 5. Validate and roll out

Deliver small reviewable changes in the sequence above. Test additive migrations against populated SQLite and PostgreSQL data; retain legacy job processing for already-queued imports. Document web/worker deployment order, draft cleanup, and rollback behavior. Exercise disposable imports before enabling the redesigned importer broadly.

## Acceptance criteria

1. Add song A, create Amber State, then add song B: Amber State is available immediately in both rows and every applicable shared control. Repeat with A already uploaded and with both songs present before artist creation.
2. Creating an artist from a selected group assigns exactly that group; creating it on one song does not change another song. Existing normalized names reuse the canonical record.
3. Import one correctly tagged song without creating an album or opening advanced fields.
4. Import a 12-track album by reviewing one album header and track rows. Add track 13 later and inherit that album's chosen shared values without losing row overrides.
5. Import unrelated artists, two albums from different folders, a compilation, and a two-disc album while preserving performing artists, grouping, and ordering.
6. Review metadata and available artwork consistently for MP3, FLAC, M4A, and WAV. Late extraction cannot overwrite typed corrections.
7. Apply only an artist: title, tags, categories, and artwork remain unchanged. Restore file metadata, clear an album, and undo a bulk edit with predictable results.
8. Correct artist/album after upload and after processing from the same workspace; the saved record and displayed values agree.
9. Handle duplicates, invalid files, interrupted uploads, lost responses, processing failures, expired login, worker restarts, refreshes, and multiple open tabs without duplicate songs or lost saved choices.
10. Confirm no draft becomes broadcast eligible. After import, preserve enable-after-analysis behavior, explicit keep-disabled intent, and the category requirement for rotation.
11. Enforce authentication, CSRF, station/shared-catalog boundaries, and valid artist/album choices on every new endpoint. Review existing shared album artwork effects.
12. Validate keyboard-only use, focus, status announcements, mobile layout, and responsive selection/editing with 100+ files. Batch updates should not fetch the entire catalog once per song.

The new test coverage should assert saved results and user-visible behavior. Existing tests passing did not catch the multi-song selector issue; a successful single-song import is not sufficient acceptance for this work.
