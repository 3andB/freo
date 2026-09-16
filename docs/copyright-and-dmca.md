# Copyright identification and reporting

Tracks retain their existing internal integer ID and UUID. The original uploaded bytes are SHA-256 hashed during ingestion; no decoded/transcoded audio is substituted. Failed ingestion rolls back and removes temporary files. Hashes are private. Legacy hashes can be NULL.

Each track receives a random permanent `FR-XXXX-XXXX` public identifier, protected by a unique database constraint. PostgreSQL serializes candidate allocation to handle concurrent collisions. The migration assigns identifiers to existing tracks without reading audio. Updating metadata does not change an identifier.

ISRC is optional in Song details. Newly supplied values are uppercased, with whitespace and hyphens removed, and must contain exactly 12 ASCII letters/digits. Empty values become NULL. Embedded ISRC metadata uses the same validation; an invalid embedded ISRC rejects ingestion with normal cleanup. Existing nonempty ISRC values are preserved by the migration, including malformed legacy values; unchanged legacy values do not block unrelated metadata edits. Identifiers do not establish ownership or licensing.

## Reports and review

- `GET /dmca`: public form. Optional query parameters `supplied_track_id` and `station_text` prefill the form.
- `POST /dmca`: validated, CSRF-protected report submission; returns a receipt/reference, not a public case lookup.
- `GET /admin/dmca`: paginated global-admin case list.
- `GET /admin/dmca/<reference>`: private details and immutable evidence snapshot.
- `POST /admin/dmca/<reference>/status`: CSRF-protected status update with an `AuditEvent`.

The player always shows a station-prefilled copyright report link, including when stopped, playing imaging, or missing metadata. A Freo Track ID is shown and prefilled only while confirmed track metadata is fresh. Imaging has no track identifier. The admin sidebar, station overview, and station settings link to DMCA reports. Cases preserve the supplied identifier, station text, claimant information, descriptions, confirmations, signature, and submission time. A resolved track contributes its internal track/owner-station association and a title/artist/hash/ISRC/public-ID/station snapshot. The reported station is resolved separately from local names/URLs, since shared tracks can air on another station. No supplied URLs are fetched. Foreign keys become NULL on physical deletion while evidence remains.

All cases begin `OPEN`. Available statuses are `OPEN`, `REVIEWING`, `ACTIONED`, `REJECTED`, and `CLOSED`. Neither submission nor a status change deletes/disables tracks, changes station state, or controls playback. `ACTIONED` is a human-entered record of review, not an automated enforcement command.

## Security and operational limits

The feature uses existing global-admin authentication and session CSRF. Inputs have length limits; requests are limited to 32 KiB; Jinja escapes submitted text. Pages use private/no-store caching and no-referrer policy. Public API serializers add only the public track identifier and report URL, never evidence or claimant data.

A database-backed limit permits five accepted reports per client address per rolling hour (`DMCA_REPORTS_PER_HOUR`). PostgreSQL advisory locks serialize concurrent submissions across web workers. The database stores a keyed HMAC of the address, not its plaintext form. A new browser session does not reset the limit. Invalid forms do not create cases. This application limit is not a general network-level denial-of-service defense.

Production trusts `X-Real-IP` only from loopback peers (`DMCA_TRUSTED_PROXY_IPS`), matching the bundled Nginx templates, which overwrite that header. Testing/development trust no proxies by default. If deploying behind a different proxy, configure trusted peer addresses explicitly and ensure the proxy overwrites the header; never trust arbitrary client forwarding headers. There are no new required environment variables.

Claimant data and evidence are intentionally retained in PostgreSQL and its backups for review. Access follows Freo's existing global-admin model; there is no public case search, claimant portal, notification integration, or automatic retention/deletion job.

## Deploying an approved release

These instructions are for the existing `/opt/freo` systemd installation. Production execution requires explicit authorization; the authorized deployment is recorded below. No dependency, Nginx, or media-file changes are required. Schedule a maintenance window: stopping automation can interrupt normal queue replenishment, and stopping the optional microphone gateway disconnects active mic sessions.

1. Take the normal PostgreSQL backup and confirm it is restorable. Preserve the pre-upgrade application release. The schema downgrade deletes all DMCA cases and removes public identifiers; it is not an evidence-preserving rollback.
2. Stop application processes before installing the reviewed release. Run only the optional mic command if that service is installed/in use. Stop timers before their one-shot workers.

   ```sh
   cd /opt/freo
   sudo systemctl stop freo-provision.timer freo-public-schedules.timer
   sudo systemctl stop freo.service freo-ingest.service freo-automation.service freo-provision.service freo-public-schedules.service
   # Only if installed/in use:
   sudo systemctl stop freo-mic.service
   ```

3. Install the reviewed application release, preserving `.env` and media storage. Using the existing migration account and `.env`, run:

   ```sh
   cd /opt/freo
   sudo /opt/freo/venv/bin/flask --app wsgi:app db upgrade
   sudo /opt/freo/venv/bin/flask --app wsgi:app db current
   sudo /opt/freo/venv/bin/flask --app wsgi:app db check
   ```

   The new revision is `c07d9a21b634`, following `f84c1d92be30`. It creates `dmca_cases`, adds/indexes public identifiers, permits nullable hashes/ISRCs, converts empty ISRC strings to NULL, and backfills only public identifiers. It does not rehash audio. If migration fails, investigate before starting the new code.
4. Start only services/timers that were active before maintenance:

   ```sh
   sudo systemctl start freo.service freo-ingest.service freo-automation.service
   sudo systemctl start freo-provision.timer freo-public-schedules.timer
   # Only if previously active:
   sudo systemctl start freo-mic.service
   ```

5. Check `/dmca`, authenticated `/admin/dmca`, and a live player's identifier/report link. Verify Song details accepts an optional ISRC. Check service logs for migration/model errors. No manual track backfill is needed.

## Isolated validation

Run `FREO_ENV_FILE=/dev/null venv/bin/pytest -q`. Browser/ACL tests need localhost sockets, Chromium/ChromeDriver, and normal host UID/ACL support. Tests create their own temporary SQLite databases/media.

The PostgreSQL test **destroys tables in its supplied database**. Set `FREO_TEST_POSTGRES_URL` only to a disposable database, never production:

```sh
FREO_ENV_FILE=/dev/null FREO_TEST_POSTGRES_URL='<disposable PostgreSQL URL>' \
  venv/bin/pytest -q tests/test_dmca_postgres.py
```

It checks fresh migrations, legacy upgrade/backfill, downgrade/re-upgrade, Alembic schema consistency, concurrent report limits, and evidence survival after physical track/station deletion. `tests/test_copyright_dmca.py` covers hash generation/failure cleanup, public-ID uniqueness/collision/immutability, ISRC validation/editing, reports, admin/CSRF boundaries, auditing, no automatic takedown, proxy handling, shared/custom-domain station resolution, and public privacy. `tests/test_copyright_browser.py` checks the player-to-report workflow and ISRC editor.

## Changed files

- Application/schema: `app/__init__.py`, `app/config.py`, `app/models/__init__.py`, `migrations/versions/c07d9a21b634_copyright_and_dmca.py`.
- Routes: `app/routes/dmca.py`, `app/routes/admin_media.py`, `app/routes/catalog_editor.py`, `app/routes/web.py`.
- Services: `app/services/copyright.py`, `app/services/dmca.py`, `app/services/catalog_edit.py`, `app/services/media.py`, `app/services/music_catalog.py`, `app/services/player.py`.
- Templates: `app/templates/dmca.html`, `app/templates/admin/dmca.html`, `app/templates/admin/base.html`, `app/templates/admin/media_track.html`, `app/templates/admin/overview.html`, `app/templates/admin/station_settings.html`, `app/templates/player.html`.
- Browser code: `app/static/media_editor.js`, `app/static/player.js`.
- Tests: `tests/test_copyright_dmca.py`, `tests/test_dmca_postgres.py`, `tests/test_copyright_browser.py`, `tests/test_music_catalog.py` (existing ISRC fixture updated to the required format).
- Documentation: `README.md`, `docs/copyright-and-dmca.md`.

## Validation results (2026-09-16)

- Full unrestricted suite: **371 passed, 19 skipped, 1 failed** in 18m20s. The sole failure was the preexisting six-character ISRC fixture collected before it was corrected to the required format. Its final-file rerun passed. The skipped tests require optional integration modes/services or demonstration capture.
- Corrected catalog suite plus all DMCA/identification unit/route tests: **23 passed**. This includes the additional embedded-ISRC rejection/cleanup and legacy-preservation test.
- Focused PostgreSQL + DMCA + new browser workflow run: **19 passed** before that additional test was added. Together the final new test files contain 20 passing feature checks across these focused runs.
- Existing PostgreSQL migration/concurrency suite: **5 passed** against a disposable PostgreSQL 16 cluster. New migration upgrade/downgrade/re-upgrade and `db check` passed; concurrent rate limits and evidence survival were verified.
- Existing media/player/catalog browser selection: **12 passed**. JavaScript syntax, Python compilation, and `git diff --check` passed.
- The initial sandbox run could not execute socket/ACL tests; those restrictions were resolved by rerunning with local test-service access. No production database, service, or deployment was modified. The disposable PostgreSQL cluster was stopped after testing.

Existing SQLAlchemy session and Flask-SQLAlchemy migration API deprecation warnings remain unrelated to this feature.


## Authorized production deployment (2026-09-16)

Following explicit deployment authorization, revision `c07d9a21b634` was applied to production and `db check` reported no pending schema changes. All 17 existing tracks received unique public IDs. A before/after comparison confirmed original SHA-256 values, titles, artists, UUIDs, and track/station states were unchanged. No test copyright claims were inserted into production.

A PostgreSQL custom-format backup was created and its archive directory verified at `/var/backups/freo/copyright-20260916T162104Z/before.dump`. The web, ingest, automation, and microphone services were restarted; the provisioning and public-schedule timers were restored. All were active after maintenance.

The final isolated feature/browser/catalog run passed **24 tests**. Live HTTPS checks passed for health/readiness, the DMCA form, unauthenticated admin rejection, missing/invalid-form CSRF validation, both active station players, and public API privacy.


### Link visibility follow-up

The reporting link remains visible without JavaScript or confirmed current-track metadata and retains the station prefill. Only the optional Track ID is hidden when metadata is unavailable. DMCA reports now appears beside station settings in admin navigation, with direct links on station overview/settings. The player script version was bumped for existing browser caches. The 33 focused browser, copyright, and player checks passed across the main run and corrected missing-metadata fixture rerun. This change requires only a web restart, with no migration.
