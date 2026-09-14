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

## Phase 2 additions

On the fresh VM, also confirm `liquidsoap` and `icecast2` install and record their versions; `freo-playout` and `icecast2` exist as non-login, non-root identities; `/etc/freo/secrets/engine.json` is restricted; rendered configs and control socket are private; Icecast listens only on localhost; and Liquidsoap connects to the test mount. Verify `/health/icecast`, `/health/playout`, and `/health/stream`. Read bounded bytes from the public test stream and confirm `audio/mpeg` and nonzero payload, rather than relying on HTTP status alone. After reboot and installer rerun, confirm the stream recovers, credentials did not rotate, and no runtime config or secret entered Git.

## Phase 3 additions

On the separate fresh VM, create a managed station through the root-run CLI, confirm its row and stream relationship, render and validate config, start its templated non-root unit, check its private socket, and read public audio bytes. Stop it and verify its mount disappears; start it and verify return. Create a second station, restart the first, and verify the second and diagnostic fixture remain online. Reboot and confirm only desired-running station instances return. Rerun the installer without rotating credentials or destroying station data. Confirm generated station configs, secrets, sockets, and exact route snippets are outside Git and permission-restricted.

## Phase 4 additions

On the separate fresh VM, confirm `/usr/bin/ffprobe` exists and record the `ffmpeg` package version. Confirm `/var/lib/freo/media` and `/var/lib/freo/playlists` are mode 0750 and not world-writable. Generate a short legal MP3 test tone with ffmpeg; ingest it through `flask media ingest`, confirm checksum, metadata, station ownership, UUID storage key, and `flask media verify`. Check duplicate binary ingest returns the same track in one station while another station remains separate. Start the station, identify test metadata and tone in Icecast and the public stream, then disable the track and confirm fallback. Re-enable it and confirm playback returns. Reboot and verify the database row, file, playlist, and stream recover. Rerun the installer and verify no media or credentials changed. Check no media, playlists, or generated fixtures entered Git.
