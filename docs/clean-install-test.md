# Fresh Ubuntu 24.04 acceptance test

This test must run on a separate, disposable, fresh Ubuntu 24.04 VM before Freo claims third-party installation support. Record OS image, commit, package versions, results, and defects. Do not use the production Freo database.

1. Create the VM, install Git if required, clone the public Freo repository, enter the checkout, and run `sudo ./scripts/install.sh`.
2. Confirm the installer finishes; `/opt/freo/venv` exists; Python dependencies import; PostgreSQL is active; the `freo` role/database exist; and `flask db current` and `flask db heads` agree (both at the latest revision).
3. Confirm `freo.service` is active and its Gunicorn master/workers run as non-root `freo`. Confirm Nginx is the web entry point and Gunicorn binds only localhost. Confirm PostgreSQL does not listen publicly.
4. Confirm `/health` and `/ready` succeed locally and through Nginx. Validate an IP-only HTTP install first.
5. On a separate domain pointing to the VM, test domain HTTP installation, then optional Certbot HTTPS. Confirm TLS and HTTP redirect. Ensure the application is reachable on the domain.
6. Reboot and confirm PostgreSQL, Nginx, and Freo return automatically. Rerun the installer and verify no database reset, secret rotation, or `.env` overwrite; confirm services and endpoints still work.
7. Check secret files are not world-readable; no generated secrets, private keys, media, logs, or database dumps appear in tracked files. Check the `freo` account has no broad sudo rights.
8. Practice rollback of application code and the backed-up systemd/Nginx configuration. Database rollback requires an operator backup; uninstall must never delete data automatically.

The current production server is not a substitute for this clean-install test. Record a signed-off result in a future release checklist before marking installation supported.

For the web UI, verify `/`, `/stations`, and `/player/<station-slug>` render without demo data or invented listener metrics. Confirm the player begins audio only after a user gesture, handles an unavailable stream, and shows confirmed history with an accurate observation label. Confirm `/admin` and admin media routes redirect to login before an account exists. Create an administrator with `flask --app wsgi:app admin set-password --email operator@example.com` using the hidden prompt; confirm successful sign-in, failed-password handling, CSRF rejection, and logout. Verify `/admin`, station detail, Media, Categories, Rotations, Clocks, Schedule, History and System render real station data and keep stations separate. Upload a generated MP3 through the browser, wait for the non-root ingest worker, review metadata, assign a category, verify and enable, then disable without restarting playout. Confirm duplicate and invalid uploads, cross-station rejection, audit entries, no raw-media URL, and the 128 MB limit. Rerun the installer and confirm it neither creates nor resets an admin account. Verify no account password or hash is committed to Git.

## Phase 2 additions

On the fresh VM, also confirm `liquidsoap` and `icecast2` install and record their versions; `freo-playout` and `icecast2` exist as non-login, non-root identities; `/etc/freo/secrets/engine.json` is restricted; rendered configs and control socket are private; Icecast listens only on localhost; and Liquidsoap connects to the test mount. Verify `/health/icecast`, `/health/playout`, and `/health/stream`. Read bounded bytes from the public test stream and confirm `audio/mpeg` and nonzero payload, rather than relying on HTTP status alone. After reboot and installer rerun, confirm the stream recovers, credentials did not rotate, and no runtime config or secret entered Git.

## Phase 3 additions

On the separate fresh VM, create a managed station through the root-run CLI, confirm its row and stream relationship, render and validate config, start its templated non-root unit, check its private socket, and read public audio bytes. Stop it and verify its mount disappears; start it and verify return. Create a second station, restart the first, and verify the second and diagnostic fixture remain online. Reboot and confirm only desired-running station instances return. Rerun the installer without rotating credentials or destroying station data. Confirm generated station configs, secrets, sockets, and exact route snippets are outside Git and permission-restricted.

## Phase 4 additions

On the separate fresh VM, confirm `/usr/bin/ffprobe` exists and record the `ffmpeg` package version. Confirm `/var/lib/freo/media` and `/var/lib/freo/playlists` are mode 0750 and not world-writable. Generate a short legal MP3 test tone with ffmpeg; ingest it through `flask media ingest`, confirm checksum, metadata, station ownership, UUID storage key, and `flask media verify`. Check duplicate binary ingest returns the same track in one station while another station remains separate. Start the station, identify test metadata and tone in Icecast and the public stream, then disable the track and confirm fallback. Re-enable it and confirm playback returns. Reboot and verify the database row, file, playlist, and stream recover. Rerun the installer and verify no media or credentials changed. Check no media, playlists, or generated fixtures entered Git.

## Phase 5 additions

On the separate fresh VM, verify the `freo-automation` non-login account and service, PostgreSQL heartbeat, `/health/automation`, managed socket mode 0660, and denial of socket access to the `freo` web account. Generate and ingest several distinct legal MP3 fixtures through the CLI; create station-scoped categories, assign tracks, define an explicit rotation, preview without database mutation, activate and enable automation. Confirm at least ten actual start events and their category sequence, metadata changes, artist/track separation or audited relaxation, bounded empty-slot skip, queue refill, and stable HTTPS stream. Restart the worker and one station instance separately; confirm recovery and diagnostic isolation. Corrupt a copied test fixture only with automatic restoration and confirm failed-request history and fallback continuity. Reboot, rerun installer, and confirm no secret rotation, data destruction, or public control socket. Record this independent VM result before claiming supported one-command installation.

## Phase 6 additions

On the separate fresh VM, assign an IANA timezone to a station, create two reusable clocks with `CATEGORY` and `ROTATION` slots, validate them, and add weekly local-time assignments. Check a schedule preview and the next UTC transition, including Sunday-to-Monday carry, spring-forward, fall-back, and a non-DST timezone. Enable automation and confirm actual Liquidsoap starts carry the correct clock/slot/assignment context. Move a temporary transition a few minutes ahead; confirm the on-air track finishes, later selections switch clocks, and no Liquidsoap restart occurs. Restart the worker and station instance separately; verify cursor recovery, stream continuity, and the diagnostic stream. Reboot and confirm the intended weekly state resumes. Rerun the installer; verify no demo schedule was seeded and no existing schedule was overwritten.

## Phase 8 browser programming additions

After admin login, create a category and assign an accepted track; create a rotation, add and reorder category slots, validate and preview it, then activate it. Create a clock with category and rotation slots, reorder and preview it. Assign that clock on a station-local weekday and time, preview the next day and week, and confirm the active clock and next transition. Try an invalid weekday, unsupported slot type, missing CSRF token, and cross-station reference; all must fail without changing programming. Verify audit entries and actual confirmed starts after a controlled boundary, with no Liquidsoap or automation restart. Change timezone only on a test station, then restore it.

## Phase 9 imaging additions

Upload a generated legal MP3 as a station ID through Admin → Imaging. Confirm it is accepted disabled, verify and enable it, and check a same-station duplicate and a renamed invalid file. Create an imaging group, assign the asset, and add both an IMAGING_GROUP and CART clock slot. Preview without cursor/history/queue mutation. Observe music → imaging → music confirmed starts and Icecast metadata while both test and managed streams stay online. Remove temporary slots, disable the asset, verify future group selection excludes it, and decommission it without deleting confirmed history. Check missing CSRF, cross-station references, path secrecy, oversized upload handling, and rerun installer. Record fresh-VM results before public installability is claimed.

## Phase 10 Live Assist additions

Log in, open a running station's Live Assist page, confirm real Now/Next/Recent, hold automation and observe that existing queue items may finish while refill stops. Queue an enabled generated music track and cart, confirm each actual start and manual history attribution, skip a controlled item, then resume and confirm current scheduled programming refills without service restart. Test a schedule boundary during hold, worker restart with a pending request, Liquidsoap restart reconciliation, queue idempotency and limit, CSRF/IDOR, and web socket denial. Verify both streams remain online and restore normal automation. Fresh-VM validation remains the public installation gate.
