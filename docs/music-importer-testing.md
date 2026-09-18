# Music review workspace: implementation and rollout

The importer now stages audio for review, detects metadata with the existing worker, and commits selected songs only after the user chooses Import. Draft preparation does not create a library track or enable broadcast. Legacy `/media/upload` requests and already queued ingest jobs continue to work.

## Operator flow

- Add files or a folder. MP3, M4A, FLAC and WAV metadata appears after worker preparation; non-MP3 audio gets a compatible authenticated preview. Embedded cover art is optional.
- Review a single song or compact rows grouped by detected album/album artist or folder. Artist and album fields search existing entries and offer creation. New catalog entries immediately become available to all current and later rows.
- Edit an album once, or select songs and edit shared fields. Changes apply only to touched fields; tags/categories offer add, remove and replace. File metadata reset, explicit singles, track/disc numbering, individual overrides and undo are supported. A detected folder cover can be cropped and applied to selected songs.
- Choose Library only or an active rotation category in the visible After import control. Explicit choices are remembered for this station and saved with each upload. Import the selected ready songs while other files continue preparing or remain available for retry. Processing enables them by default after success; Keep disabled preserves an explicit opt-out. Rotation additionally needs an active category. Metadata can be corrected in the same workspace once the song exists, without another upload.
- Return to a workspace to resume uploaded files and saved edits. Files interrupted before reaching the server require reselection. Duplicates are identified by checksum immediately after upload, deselected, and linked to the existing song. They preserve existing library metadata. Preparation and ingest failures can be retried individually; failed ingest jobs retain staged bytes for retry during the draft retention window.

Compilation albums use their album artist as catalog owner while preserving each song's performing artist. Artist pages include compilation appearances, and album pages order tracks by disc and track number.

## Persistence and concurrency

`music_import_sessions` belongs to a station and the signed-in admin. Its items retain file identity, checksum, detected metadata, explicit choices, revision, optional draft preview/artwork, and the final ingest job. Group defaults are stored with the session. Draft edits and finalization lock the session and item; stale revisions produce an actionable conflict. Repeated finalization reuses the original job. Concurrent normalized artist/album creation reuses the canonical row.

A workspace holds at most 500 files and 10 GB, with the existing per-song upload cap. Drafts expire after 7 days without a mutation. Hourly worker cleanup protects live drafts and removes cancelled/expired staged bytes and completed draft previews. Completed result metadata remains available in the database. Browser-local unfinished files are remembered by name/size/path, never by serializing audio into local storage.

The importer polls one aggregate session endpoint with eager loading and no waveform payload. Finished imports slow to a 30-second interval; hidden tabs pause polling. Expired sessions show sign-in and resume controls, preserving local files and refreshing CSRF before retry. Polling does not move focused controls or overwrite unsaved choices. Navigation flushes edits; unfinished uploads get a leave warning. Invalid metadata and optional artwork failures remain visible without discarding successful files.

## Deployment

1. Back up the database through the installation's normal process.
2. Apply additive migration `e92b740a613f` with `venv/bin/flask --app wsgi db upgrade` before loading the new web or worker code. Its parent is `ab31e76f209d`.
3. Restart the web and ingest services together. No audio-engine configuration or stream restart is required.
   Install `deploy/nginx/admin-upload.conf` as `/etc/nginx/snippets/freo-admin-upload.conf`,
   run `nginx -t`, and reload Nginx. The review workspace uploads to
   `/admin/api/stations/<slug>/imports/<id>/files`; this endpoint needs its own
   129 MiB request allowance (128 MiB audio plus multipart overhead). The legacy
   `/media/upload` allowance does not cover it. Artwork at `/admin/api/stations/<slug>/artwork` also needs its own 21 MiB allowance for the application’s 20 MiB cap plus multipart overhead.
4. On a disposable station, import one song, add a second song under a newly created artist, import an album, refresh a pending workspace, and correct an imported song. Confirm original audio, private preview, artwork, classifications and enable intent.
5. Check both services' logs and `/health` and `/ready`. The ingest service needs its existing write access to uploads and media; no new writable directory is introduced.

For rollback, stop the new workers and finish or cancel active review drafts before downgrading. The migration refuses downgrade while pending/preparing/ready drafts remain. Downgrade removes workspace history; imported tracks and legacy ingest jobs remain. Preserve a backup if review choices need restoration. A rollback to an old worker must not let that worker clean active draft uploads.

## Validation

Run the focused checks:

```sh
venv/bin/pytest -q tests/test_import_sessions.py tests/test_import_sessions_browser.py \
  tests/test_catalog_editor.py tests/test_catalog_editor_browser.py \
  tests/test_music_catalog.py tests/test_audio_formats.py tests/test_media.py
scripts/test-import-postgres.sh
```

Run `venv/bin/pytest -q tests/test_upload_proxy.py` with Nginx installed and local
socket access to verify the shipped proxy configuration on an isolated listener.
It checks the 2,236,885-byte request size rejected in production on September 18,
the legacy upload route, and oversized/unrelated request rejection. Browser
coverage in `test_upload_errors_keep_file_for_retry` checks HTML proxy errors,
login redirects, malformed responses, JSON validation errors, and retrying the
same retained file successfully. These checks use temporary storage and databases.

### Upload proxy correction — 2026-09-18

The live review-workspace request received Nginx HTTP 413 because only the legacy
upload path had a larger body limit. The new location allows 129 MiB; Flask still
enforces the configured per-song cap. Upload responses now check status and content
type before parsing JSON, keep failed files available for retry, and identify login
redirects. The importer script version is `imports-5` to refresh browser caches.

Validation: **22 passed, 1 deselected** across the Nginx integration test, all seven
importer browser tests, and the importer service tests. The deselected pre-existing
`test_real_migration_upgrade_preserves_catalog` failed in the initial run because
its already-current schema receives later migrations (`duplicate column name:
broadcast_revision`); no migration code changed in this fix. JavaScript syntax and
`git diff --check` passed. Output: `/tmp/freo-upload-fix-tests.log`.

Production: installed the snippet after backing up its previous contents, passed
`nginx -t`, reloaded Nginx, and sent Gunicorn HUP to refresh web workers/templates.
The same unauthenticated 2,236,885-byte request changed from HTTP 413 to the expected
HTTP 302 login redirect, proving it reaches the application without creating an
import. The live JavaScript matches the tested file; health/readiness returned 200
and Nginx, web, and ingest services remained active. The previous snippet is at
`/tmp/freo-upload-config-backup-e8lfxuig/freo-admin-upload.conf`. No production test
song was added. Retrying the user's original file remains the final user check.

The PostgreSQL script creates and destroys a private cluster under `/tmp` and never reads production database credentials. It validates migration upgrade/downgrade with populated legacy tables, concurrent artist creation, stale edit rejection and idempotent simultaneous finalization. SQLite migration coverage runs in the same script.

Browser coverage includes Amber State on a song added later, post-import artist correction, refresh recovery, album defaults for a later track, classification preservation, a 105-song album, keyboard selection, batch reset/undo, artwork cropping, file/folder drop, daily reminder and mobile overflow. Service tests use actual FFmpeg audio in all four formats and exercise compilation discs, original-file preservation, private previews, duplicates, disabled intent, draft expiry, cancellation, worker failure/retry and optional artwork failure.

## Results — 2026-09-18

- Importer service and browser suite: **21 passed**, covering six browser scenarios and real audio preparation/finalization. This includes the exact first-song import followed by a second song and new Amber State artist, interrupted first upload, and deliberately delayed responses during edits and session switching.
- After the final preview permission fix: **17 passed** (all 15 importer service cases plus two legacy migration checks). A separate check ran WAV preview conversion as `freo-ingest` and successfully read it as `freo`, using temporary files. Worker-created draft previews grant read access to the original uploading user without changing service group memberships.
- Final 105-song album browser rerun: **passed**, including keyboard reset, undo, mobile width and the visible bottom import action.
- Existing editor, file picker/folder drop, audio settings/reminder and forms browser checks: **7 passed**. Additional focused catalog/media/audio and regression runs passed.
- Disposable PostgreSQL migration/concurrency run: **5 passed**; populated catalog data survived upgrade/downgrade, concurrent artist creation reused one artist, conflicting edits were rejected, and concurrent finalization created one job.
- Full repository run: **641 passed, 32 skipped, 3 failed**. Two failures were legacy migration tests incorrectly upgrading to the latest revision; they now target their own migration and pass. The remaining `test_workspace_browser.py::test_calendar_create_edit_and_mobile_layout` failure also reproduced alone: Selenium could not click a scheduling timeline item at `(386, 1057)`. During the subsequent scheduling commit, the test was updated to use the readable edit button provided for short intervals and passed in a 22-case focused rerun. All three observed failures have passing targeted reruns; the full suite has not been repeated since those corrections.
- JavaScript syntax and `git diff --check`: passed.

The user approved production backup, migration, commit, push and web/ingest restart on 2026-09-18. Commit `3aa13d3` was pushed to `main`. A private database backup was verified before upgrading from `ab31e76f209d` to `e92b740a613f`. Web and ingest services restarted successfully at approximately 01:28 UTC. Health and readiness returned `status: ok`; the new importer endpoint required admin authentication, the new frontend was served, and no startup warnings were recorded. No audio engine restart was needed.

Browser screenshots from the temporary test installation are available at `/tmp/freo-import-workspace-desktop.png`, `/tmp/freo-import-workspace-mobile.png` and `/tmp/freo-import-album-mobile.png`. Test logs are under `/tmp/freo-import-*.log` and `/tmp/freo-full-suite.log`. No synthetic songs were imported into the user's production station.


### Simpler flow and review fixes — 2026-09-18

This follow-up uses existing tables and JSON fields; **no new database migration**.
The initial deployment steps above describe installation of the original workspace.

- Import counts refer to ready selected songs. A broken file no longer blocks good songs.
- The drop area shrinks once files are chosen. The visible destination selector supports
  an active rotation category, Library only, or keeping individual categories. Explicit
  Keep disabled choices still take precedence over automatic broadcast eligibility.
- Preview has a Close control. The action bar measures the player’s actual height and
  stays above it on desktop and mobile, with enough content padding to reach all fields.
- Known duplicate audio is skipped by default before editing or finalizing. Existing
  titles, artists, album artwork and rotation settings are retained. Deleted audio can
  still be intentionally imported again.
- Completion distinguishes imported songs from ongoing audio analysis. View imported
  songs opens a session-filtered library; All songs clears that filter.
- Workspace choices show an album, folder or filename with submitted/total progress.
  Failed switching leaves the previous files and browser audio URLs intact.
- Album Add category/tag operations accumulate shared defaults for later songs.
  Multiple draft edits and Undo save in one atomic request, with per-song revision
  checks; a stale row rolls back the batch instead of partially applying it.
- All catalog/import responses check status and content type before JSON parsing.
  Artwork and music have separate proxy limits. Login recovery retains local files.
- The worker commits the job result before removing its staged source. An interrupted
  older job can recover an existing, verified original with the same station/checksum.
  Cleanup failures leave the successful job durable and retry cleanup later.

Focused regression commands for this follow-up:

```sh
venv/bin/pytest -q tests/test_import_sessions.py tests/test_import_review.py \
  tests/test_catalog_editor.py tests/test_upload_proxy.py tests/test_media.py \
  tests/test_audio_formats.py tests/test_music_catalog.py tests/test_sound_room.py
venv/bin/pytest -q tests/test_import_review_browser.py tests/test_import_flow_browser.py \
  tests/test_import_sessions_browser.py tests/test_catalog_editor_browser.py \
  tests/test_audio_settings_browser.py tests/test_sound_room_browser.py
scripts/test-import-postgres.sh
```

Release checks: install the updated Nginx snippet, validate and reload Nginx, reload
web workers, restart the ingest worker, then check health/readiness, services, logs,
served asset hashes and unauthenticated requests through both upload proxy locations.
The tests use isolated databases, storage, Nginx listeners and real audio; they do not
add songs to the production library. A fresh VM installation was not available in
this session; the above installation and cross-service preview checks remain the
fresh-install validation procedure.

Follow-up validation completed: **85 distinct focused checks passed** across the
backend, real audio/proxy integration, PostgreSQL and browser runs. The 105-song
album/Undo case, mobile preview/import clicks, HTML error/retry matrix, artwork,
existing-row CSRF renewal and filtered results were exercised. Preview/import and library pointer regressions
scroll controls into view and use real WebDriver clicks.
This was focused importer and adjacent music coverage, not a rerun of the entire suite.

Deployed at **2026-09-18 03:33 UTC**. Nginx validation and reload succeeded, Gunicorn
workers reloaded, and the ingest service restarted without startup errors. Health
and readiness returned HTTP 200; Nginx, web and ingest services were active. Both
music and artwork accepted the previously failing 2,236,885-byte request through
the proxy to the application login boundary (HTTP 302), without creating production
media. All five changed frontend assets matched the tested local files.

Deployment log: `/tmp/freo-import-flow-deploy.log`. Previous Nginx configuration:
`/tmp/freo-import-flow-backup-cobsec1u/freo-admin-upload.conf`.
