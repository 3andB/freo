> Current lifecycle and library behavior: [Station lifecycle and shared music](channel-management.md).
> The Phase 3 notes below describe the original implementation. Creation/deletion
> now also have authenticated UI workflows; music can be available to all channels.

# Station management (Phase 3)

The Phase 2 `freo-test` stream is a separate diagnostic fixture: it answers whether this installation can generate and deliver audio. It is not in the station database. `freo-demo` is the first database-managed station; `freo-demo-2` was used for two-process isolation and is now stopped. Both managed stations currently emit generated tone audio, not programming.

`Station` stores name, immutable slug, description, enabled flag, desired state (`stopped` or `running`), and timestamps. `StreamMount` is a one-to-one primary MP3/64 kbps stream. Its Icecast mount `/<slug>` and listener path `/stream/<slug>` derive from the slug; they are never arbitrary paths. Slugs use lowercase ASCII letters, digits, and interior hyphens, up to 64 characters; reserved names including `admin`, `status`, `server_version`, and `freo-test` are rejected. PostgreSQL also constrains slug shape and uniqueness. Slug changes and permanent deletion are not supported in Phase 3.

The authoritative admin path is the root-run Flask CLI from `/opt/freo`: `venv/bin/flask --app wsgi:app station list`, `create <slug> --name '<name>'`, `show <slug>`, `validate <slug>`, `render <slug>`, `start <slug>`, `stop <slug>`, `restart <slug>`, `enable <slug>`, `disable <slug>`, and `status <slug>`. Run lifecycle commands with `sudo` as an administrator, not from the web process. Creation writes a stopped database row, generates a unique source credential, renders and validates the config, updates Icecast with HUP only when mount config changes, and reloads Nginx after syntax validation. Start enables the specific `freo-playout@<slug>` instance for reboot, waits for audio, then records desired state `running`. Stop disables and stops only that instance and records `stopped`. A failed start is stopped/disabled and never marked running. `status` reports observed socket and Icecast/stream state separately from desired state.

The Flask app publishes only `GET /api/stations`, `GET /api/stations/<slug>`, and `GET /api/stations/<slug>/status`. These return safe metadata and observations. There are no web mutation or service-control routes and no public start/stop buttons. The `freo` user has no sudo or arbitrary systemctl access. Root-run CLI operations validate a known database slug and construct exactly `freo-playout@<slug>.service`; subprocesses use argument arrays, never a shell. The systemd template independently validates `%i` before Liquidsoap reads the config. A future authenticated control plane will need a narrower helper and audit trail before replacing this CLI boundary.

Runtime Liquidsoap configs are `/etc/freo/radio/stations/<slug>.liq`, root-owned and readable only by `freo-playout`; source credentials are `/etc/freo/secrets/stations/<slug>.json`, root-only mode `0600`. Icecast has one private process at `127.0.0.1:8001` with mount-specific source passwords; its config reload preserves existing streams. Nginx has generated exact-match snippets under `/etc/nginx/snippets/freo-stations/`. Each Liquidsoap process owns `/run/freo/playout/<slug>/control.sock` mode `0600`; all sockets are private Unix sockets. The shared `freo-playout` account gives process and restart isolation, not a hostile-code security sandbox between stations. User-supplied Liquidsoap code is not accepted. All service logs go to journald, e.g. `journalctl -u freo-playout@freo-demo`.

A station's public URL is `https://<domain>/stream/<slug>` when HTTPS is configured, or the same path over HTTP on an IP-only install. The public stream proxy contains only exact routes for rendered stations; Icecast admin, status, and source paths are not proxied. The status API checks private backend observations and does not claim to verify external DNS/TLS reachability. Use a bounded public stream byte read for end-to-end validation.

Two managed processes were started on this server. Restarting `freo-demo` left `freo-demo-2` and `freo-test` delivering audio; the first returned. Stopping the second removed only its mount, and starting it restored audio. The second was stopped again to limit resource use. A Liquidsoap process used about 145-150 MiB RSS in the observed snapshots; with the diagnostic fixture, one managed station meant two Liquidsoap processes (~300 MiB RSS), and two managed stations meant three (~445 MiB RSS). CPU rose sharply during the roughly 15-20 second Liquidsoap initialization; no sustained-load benchmark was run.

Future hierarchy, not yet implemented: Station → Stream/Mount; Media Library (Tracks, Artists, Albums, Categories); Clocks; Rotations; Schedule; Carts; Live Assist; Automation; History/Logs. Phase 4 can begin with the media-library foundation. Clean-server installation has not been validated on a separate fresh VM, and full reboot behavior remains untested here; enabled instances represent desired-running stations at boot.

## Station media

Each track belongs to exactly one station. `/var/lib/freo/media/<slug>/originals` contains UUID-named approved files; other stations cannot select them through normal library operations. See [media-library.md](media-library.md) for ingest, verification, and playback.

## Automation state

A station's desired playout state (`running`/`stopped`) is distinct from automation enabled/disabled. One manually selected active rotation drives the station when automation is enabled. Each station retains its own durable cursor and decision history; service restarts do not make another station share its runtime. See [rotations.md](rotations.md).
# Station timezone

Each station has a canonical IANA timezone used only to evaluate and present weekly programming. Absolute events remain UTC. Existing stations receive `UTC` during the additive Phase 6 migration; operators should set their intended zone explicitly with `flask schedule timezone --station <slug> <IANA-zone>`. See [scheduling](scheduling.md).
# Phase 7 media administration

An active global admin can upload and manage media only within the station selected in the URL. Every track and category reference is re-queried under that station. The admin cannot start, stop, or reconfigure the station through the browser. Media files remain private; only Icecast stream mounts are public.

Station audio settings now support 64, 96 and 128 kbps MP3, plus optional processing. See [audio imports and station sound](audio-import-and-processing.md).
