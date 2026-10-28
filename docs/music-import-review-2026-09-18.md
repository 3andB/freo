# Music import reliability and experience review

The normal import path works across MP3, M4A, FLAC, and WAV. The remaining
problems are concentrated in recovery, HTTP error handling, incremental album
edits, and polling cost. Fix those before adding substantial new importer features.

This review adds isolated regression coverage and recommendations. It does not
change application behavior or production configuration beyond the upload fix
already deployed earlier in the conversation. Live checks were unauthenticated
requests, which cannot create imports. No test music was added to production.

## Confirmed findings

| Priority | Finding and evidence | User impact | Recommended fix |
| --- | --- | --- | --- |
| High | **Listening covers the Import button.** The existing `test_import_and_edit_catalog` fails in both the broad suite and an isolated rerun: after listening and choosing artwork, a real click on Import is intercepted by the preview player's `preview-normalize` label. Both the player and import action bar are fixed to the bottom; the player sits above it. | A normal listen-before-import workflow leaves the primary action obstructed. The preview has no close control, and pausing does not hide it. | Give the preview and import actions one coordinated layout, or reserve the player's measured height below the import bar. Add an explicit close control. Verify real pointer and keyboard interaction at desktop/mobile sizes, including playback ended and paused states. |
| High | **Artwork still hits the proxy limit.** A live 2,236,885-byte request to `/admin/api/stations/freo-demo-2/artwork` returns HTML HTTP 413; the corrected music endpoint reaches the expected login redirect with the same size. The artwork API accepts up to 20 MiB, and the browser exports JPEG artwork up to 3000 pixels at quality .93. | Detailed cover images can fail with “Session unavailable. Sign in again to save,” even while music uploads work. | Give the artwork endpoint an allowance consistent with its actual limit plus multipart overhead. Use common status-aware response handling for all import/catalog requests. Add a real-proxy artwork regression and validate the installed configuration during release. |
| High | **A worker interruption can leave a saved song reported as a failed import with no usable retry.** The injected final-commit failure leaves the song committed, the job in `processing`, and its staged source deleted. Startup recovery resets the job, but retry then fails because the source no longer exists. | A user sees an import failure even though the song is in the library. Repeated Retry cannot repair the job. | Commit the accepted job/track association before deleting staged bytes. Make cleanup repeatable after commit. Reconcile interrupted jobs with an already-created track using station and checksum. Test interruptions at each filesystem/database boundary. |
| High | **The original JSON parsing error still occurs after session expiry during polling.** The upload-specific fix handles login redirects; `jsonGet()` does not. The browser follows a login redirect and tries to parse the successful HTML response as JSON. | An import left open can return to `Unexpected token '<'` instead of offering sign-in and recovery. | Centralize request decoding for uploads, polling, catalog loading, notices, and saves. Detect login redirects and 401 separately from proxy/validation failures. Preserve local state and offer an explicit sign-in/reopen path. |
| Medium | **A failed workspace switch drops current local file references.** `openSession()` clears the current map and DOM before the new workspace request succeeds. A simulated 502 after a retained failed upload removes its row. | A network hiccup while selecting “Start new import” can force file reselection. Server-saved drafts remain stored, but local convenience/recovery state is lost. | Fetch and validate the destination first, then replace the current workspace. Keep the original workspace and file references on any failure. |
| Medium | **Repeated Add category/tag operations lose earlier album defaults for later songs.** Add Power, then Add Additional to an album: its existing song has both; a later song inherits only Additional. The same shared-default update handles tags. | Songs added later silently receive different classifications from the rest of the album, potentially changing rotation eligibility. | Implement Add as a union for both selected items and stored shared defaults; Remove as subtraction and Replace as replacement. Show the resulting shared classifications. Test later uploads and browser-closed preparation. |
| Medium | **Completed imports are expensive to poll.** One cold GET for 100 finalized songs executes **405 SELECT queries** in the isolated SQLite test. The page requests another aggregate update every 2.5 seconds, including after completion. | Large imports and multiple open tabs add avoidable database work and may slow the admin interface. This is a measured query-count issue, not a measured production latency claim. | Eager-load jobs, songs, classifications, and catalog relationships; omit waveform data from the query itself. Use compact progress responses. Reduce/stop polling after completion and pause hidden tabs, with refresh on focus. |

Relevant code:

- Upload limits: [Nginx configuration](../deploy/nginx/admin-upload.conf), [artwork route](../app/routes/catalog_editor.py), [shared catalog HTTP helper](../app/static/catalog_controls.js).
- Worker commit/cleanup ordering: [ingest worker](../app/ingest_worker.py), [ingest transaction](../app/services/media.py).
- Polling, workspace switching, and batch defaults: [import frontend](../app/static/media_upload.js).
- Preview/action bar layout: [music styles](../app/static/music.css), [preview controls](../app/static/music_preview.js), [existing failing browser test](../tests/test_catalog_editor_browser.py).
- Aggregate serialization: [import routes](../app/routes/music_import.py), [catalog song state](../app/routes/catalog_editor.py).

Strict expected-failure tests in `tests/test_import_review.py` and
`tests/test_import_review_browser.py` preserve five of these confirmed gaps. They
are explicitly reported as expected failures, not passing functionality. Remove
each marker when its fix lands; strict mode will flag an unexpected pass.

## Working behavior verified

- Real audio in all four supported formats goes from staged review through final
  ingest and audio analysis to enabled broadcast state when an active category is
  selected. Original bytes remain identical; review and library previews respond
  successfully; waveform and loudness results are produced.
- Intentionally reimporting a permanently deleted song creates a new song. The
  deletion path frees the old checksum correctly.
- Clearing an imported file's track-number override remains blank after refresh.
  A suspected problem here was ruled out by the browser test.
- Concurrent PostgreSQL artist creation reuses one artist; simultaneous draft
  edits reject stale revisions; duplicate finalization creates one job.
- The import migration's isolated SQLite/PostgreSQL roundtrip preserves existing
  data and refuses downgrade with active drafts.
- Existing browser coverage exercises incremental artist edits, album edits,
  multi-disc ordering, large batches, refresh recovery, upload error/retry, and
  delayed polling. Existing service coverage includes invalid audio, draft expiry,
  station/CSRF boundaries, duplicates, retained retry sources, and optional artwork.

Coverage limits: desktop Chromium and a narrow mobile viewport are covered;
Safari/iOS and real mobile network interruptions have not been exercised. Most
tests run with isolated storage under the test process identity, so they do not
replace a deployment test using the separate web/ingest service users.

## Make the flow easier

1. **Import the ready songs.** Replace a globally disabled button with, for
   example, **Import 11 ready songs**, leaving one failed row with **Retry** or
   **Choose replacement**. Explain excluded files in the action bar. Currently
   the user must find and deselect every failed selected song first.
2. **Put rotation beside the import action.** Offer a clear **Add to rotation**
   category selector with an explicit **Library only** choice. Categories are
   currently hidden under “Track details, artwork & rotation,” even though they
   determine whether an enabled song participates in rotation. Remember a user's
   explicit preference per station; do not silently change broadcast intent.
3. **Find duplicates during review.** Use the checksum already calculated while
   staging to show **Already in your library — View song** before someone spends
   time editing a duplicate. Keep the existing default of preserving library
   metadata; updating an existing song should be a separate explicit action.
4. **Give the work a clear finish.** Show Uploading → Reading details → Ready to
   import → Processing → Ready for rotation/Library only. Replace the disabled
   **Import 0 songs** state with a completion summary and **View imported songs**.
   Distinguish “saved to library” from “analysis finished.”
5. **Keep the music visible.** Collapse the large drop zone into **Add more music**
   after selection. Use compact song rows with title, artist, album, status, and
   preview; expand less-common fields on demand. Retain album-level editing,
   which already exists. Reduce admin navigation space on mobile.
6. **Make reopening recognizable.** Name workspaces from an album/folder or a
   user-supplied label and show “8 ready · 1 needs attention,” rather than only
   timestamps and total file counts. Offer **Continue unfinished import**.

## Add polish after reliability

A standalone interactive concept is available at `/tmp/freo-import-concept.html`
with screenshots at `/tmp/freo-import-concept-desktop.png` and
`/tmp/freo-import-concept-mobile.png`. It demonstrates ready-only importing,
visible rotation choice, duplicate handling, editable metadata, and a completion
view using sample data. Its interactions and narrow layout were checked in
Chromium. It is a design artifact, not deployed application code.

- Album cards with cover art, total runtime, missing-track warnings, and one
  shared rotation choice. Much of the grouping and artwork infrastructure exists.
- Optional **Use filename for missing details** with a visible preview for names
  such as `Artist - 03 - Song.mp3`; apply only where embedded metadata is missing.
- An opt-in **Import automatically when ready** mode for trusted, well-tagged
  folders. Keep explicit review as the default and route duplicates/invalid files
  to attention without blocking good files.
- A persistent import-status badge so the user can leave the page and return to
  unfinished processing. Server-side processing already continues; the interface
  should make that durability obvious.
- Resumable uploads and limited concurrent file transfers if large WAV/FLAC
  imports are common. The current fixed 180-second request timeout can expire
  during an otherwise healthy slow upload. Prioritize elapsed-time/connection
  feedback and retry behavior before taking on resumable-upload complexity.

## Prevent repeated regressions

Establish one release gate that crosses the actual boundaries: browser → installed
Nginx locations → authenticated application → staging owned by the web user →
ingest worker → private preview/original → completed analysis. Include audio above
1 MiB and detailed artwork above 1 MiB. Run it on a disposable installation with
the real service-account permissions and apply the installation scripts there.

Add deliberate failures for login expiry, proxy 413/502/504, dropped upload and
finalization responses, worker termination around commits, full/unwritable storage,
and catalogue edits while preparation is running. A single item's failure should
not lose another item's work or permanently block the batch.

Keep real pointer-click tests for primary actions. Do not use JavaScript-forced
clicks to declare obstructed controls usable. Capture a screenshot, DOM state, and
request/response summary on test failure through pytest's result hooks; a fixture's
`try/except` around `yield` does not reliably capture a test-body assertion failure.

Record preparation exceptions with traceback and item/session identifiers in
server logs. `prepare_one()` currently stores a generic user message for unexpected
exceptions without logging their details. Add queue age, processing duration, and
failure-stage metrics. Report a stalled worker explicitly instead of leaving
“Reading audio and metadata…” indefinitely.

Implement in this order: unobstructed preview/import controls, HTTP/artwork consistency, and durable worker completion;
workspace/batch recovery and polling efficiency; then ready-only import, rotation
selection, early duplicates, and the completion view. Add visual polish on that
stable foundation.

## Validation records

- New review coverage: **7 passed, 5 expected failures**, including all four audio
  formats through analysis, deletion/reimport, cleared metadata after refresh,
  and importing the good song from a mixed batch after deselecting the bad file.
- Running the five expected failures with `--runxfail` independently confirmed
  their actual assertions: missing staged source/job `processing_failed`; 405
  SELECTs; raw HTML/JSON parse error; zero remaining local file rows after failed
  switching; and later categories `{2}` instead of `{1, 2}`.
- Disposable PostgreSQL plus SQLite migration/concurrency checks: **5 passed**.
- Existing catalog browser test: **failed again in isolation**, confirming a real
  click on Import is intercepted by the preview controls after listening. Evidence:
  `/tmp/freo-import-review-catalog-rerun.log`; no JavaScript-forced click was used
  to bypass the obstruction.
- Live proxy comparison: artwork **413**, corrected song upload **302** to login
  for the same 2,236,885-byte unauthenticated request.
- Browser screenshots: `/tmp/freo-import-review-mixed-desktop.png` and
  `/tmp/freo-import-review-mixed-mobile.png`. The mixed batch shows one ready song
  and one invalid song, with the main import button disabled until deselection.
- Exact failure evidence: `/tmp/freo-import-review-confirmed-failures.log`.
  Final review regression log: `/tmp/freo-import-review-regressions-final.log`.
  PostgreSQL log: `/tmp/freo-import-review-postgres.log`.

The extra repository-wide run was deliberately stopped after import-specific
coverage, during unrelated tests. Its progress recorded **287 passes, 19 skips,
and 2 failures out of 699 collected cases**. The failures were the preview/import
button obstruction and the existing import migration test, which upgrades an
already-current fixture and hits `duplicate column name: broadcast_revision`.
This is not a complete-suite result. Interrupting the broader run also exposed a
pytest temporary-directory teardown `KeyError`, so it did not produce its normal
summary; counts above come from the progress records. Log:
`/tmp/freo-import-review-full-suite.log`.


## Follow-up implementation

The user approved the simpler flow and fixes. The implementation now includes
ready-only submission, visible rotation/library choice, early duplicate skipping,
compact upload area, meaningful workspace labels and a session-filtered results link.
The confirmed recovery, artwork proxy, preview/action-bar, album-default and polling
issues are repaired. The regressions previously marked as expected failures are now
normal assertions. Album saves and Undo also use one atomic, revision-checked request.

The final validation and rollout procedure is recorded in
[music-importer-testing.md](music-importer-testing.md). Historical failure counts
above describe the review baseline, not the final implementation.
