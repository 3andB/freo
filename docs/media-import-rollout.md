# Media editor and import rollout

Apply migration `f61c20d9a843` before loading the new web and ingest-worker code. It adds import metadata, a bounded cached waveform, an explicit auto-enable intent flag, and uploaded artwork references. Existing song states remain unchanged. Artwork bytes are stored separately in a deferred database column so the restricted web service needs no additional filesystem privileges.

## Deployment

1. Back up the database through the usual deployment process and review the additive migration.
2. Apply `venv/bin/flask --app wsgi db upgrade`.
3. Restart the web and ingest worker services together. The audio engine requires no configuration changes.
4. Verify `/health`, `/ready`, and a disposable import: listen before upload, choose an artist and its album, upload/crop artwork, assign tags/categories, and confirm audio processing automatically enables the song.
5. Verify the media screen shows the waveform, permits seeking, and keeps manual disable in effect after reprocessing. Confirm tags/category changes update scheduling readiness without a page reload.

New browser imports auto-enable only after successful audio analysis. A manually disabled or decommissioned song cancels that intent. Existing disabled songs do not become enabled merely because this migration runs. Completed existing songs gain a waveform when processed again. Album art is optional and does not gate audio eligibility. An enabled song still needs an active category for rotation.

## Validation on a disposable installation

Apply the migration on PostgreSQL containing existing artists, albums, tracks and ingest jobs. Confirm those rows and their states remain intact. Create and edit songs through the catalog API; reject cross-station selections and artist/album mismatches. Test JPEG/PNG cropping, existing album art replacement, singles, duplicate imports, mixed-artist batches, failed analysis, and manual disabling while analysis is running. Exercise restart recovery and a downgrade/re-upgrade on disposable data. Downgrading removes uploaded artwork, pending import choices, waveforms and activation flags; preserve a backup if those need restoring.

Run `tests/test_catalog_editor.py`, `tests/test_catalog_editor_browser.py`, the existing Music/ingest suites and the file-picker/drop browser regression. Browser-owned audio blob URLs are permitted by the media CSP for local previews; script policy remains unchanged.
