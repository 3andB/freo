# Architecture and boundaries

Phase 1 has one Flask application factory in `app/__init__.py`, configuration in `app/config.py`, SQLAlchemy and Flask-Migrate in `app/extensions.py`, health routes in `app/routes/health.py`, and `wsgi.py` for Gunicorn. `/health` proves the web process responds. `/ready` runs a small PostgreSQL query and returns 503 without details on failure. No radio health is implied.

Planned flow:

```text
Internet -> Nginx -> Freo Web/API -> PostgreSQL
              |          ^               ^
              |          |           Freo Worker
              |          |                |
              |          +------------ Liquidsoap -> Icecast -> listeners
              +------------------------- controlled listener mounts
```

Nginx uses `www-data`; the web app and future scheduler/control worker use `freo`; Liquidsoap uses `freo-playout`; Icecast uses its package-managed `icecast2` account; PostgreSQL uses `postgres`. Only 80/443 are public by default. Gunicorn, PostgreSQL, Liquidsoap control, and Icecast source/admin backends stay private. The test listener mount is published through an exact Nginx route; future mounts will need equally narrow routing. The current server's `www` host remains equivalent to the apex host.

systemd owns service lifecycles. Future station configuration belongs in PostgreSQL and validated templates, rendered atomically into restricted paths. Routine playout decisions should use a private worker/control interface rather than restarting processes. Web requests must never run arbitrary sudo or shell commands, accept arbitrary Liquidsoap code, write unrestricted system configuration, or restart arbitrary units. Any privileged helper needs allowlisted operations, narrow authorization, and audit logging; `freo` must not receive broad sudo access.

Phase 2 added `deploy/liquidsoap/`, `deploy/icecast/`, `/var/lib/freo/playout`, `/run/freo`, and `/etc/freo`. Media storage is now present under `/var/lib/freo/media`.

## Phase 2 engine

The test engine now implements the planned Liquidsoap -> Icecast -> Nginx listener path. See [radio-engine.md](radio-engine.md) for actual versions, config paths, service units, ownership, ports, and health checks. Icecast and Liquidsoap are independent of Flask readiness: `/ready` still measures core web/database readiness, while `/health/icecast`, `/health/playout`, and `/health/stream` observe real local radio components. No application route executes shell commands or controls systemd.

## Phase 3 station runtime

```text
Internet -> Nginx -> Freo Web/API -> PostgreSQL
              |                         |
              +-> exact listener paths   +-> root-run admin CLI (no web control)
                        |                               |
                        v                               v
                   private Icecast <--- Liquidsoap station A (freo-playout@a)
                        ^          <--- Liquidsoap station B (freo-playout@b)
                        |
                  diagnostic freo-test
```

There is one Icecast backend and one Liquidsoap process/config/socket per managed station. The web app can operate when playout is down. See [stations.md](stations.md) for domain, lifecycle, boot state, security, and future hierarchy. The existing `freo-test` remains a non-database diagnostic fixture.

## Phase 4 media library

Tracks belong to one station. The root-run CLI copies a regular, non-symlink source into private staging, hashes and probes it, then atomically moves an opaque UUID-named file into `/var/lib/freo/media/<slug>/originals`. PostgreSQL stores validated metadata and a per-station unique SHA-256 checksum. Artist and album are text fields for now. Phase 7 adds authenticated web upload through a separate non-root ingest worker using that same trusted service. The web process cannot write approved media or serve raw media. Backups need PostgreSQL, `/etc/freo`, and `/var/lib/freo/media`.

## Phase 5 automation

The `freo-automation` worker is a separate non-root process and the only Freo component with group access to managed Liquidsoap control sockets. The web account has no socket access. PostgreSQL stores category membership, explicit rotation slots, active rotation, cursor, decisions, and confirmed starts. The worker selects an approved station track and sends its controlled request to that station's Liquidsoap queue. Liquidsoap handles decoding and fallback; it does not choose tracks. See [rotations.md](rotations.md) and [automation.md](automation.md). Phase 6 may choose the active rotation from clocks and schedules without replacing the selector.
# Phase 6 programming layer

Station-local weekly assignments resolve a reusable clock from a UTC instant. The clock's ordered `CATEGORY` or `ROTATION` slots feed the established Phase 5 selector, which still enforces track/artist separation and queues approved media. PostgreSQL holds the assignment, clock occurrence, separate clock cursor, selection decision, and actual-start attribution. The non-root automation worker owns runtime selection; Flask exposes read-only programming metadata. See [clocks](clocks.md) and [scheduling](scheduling.md).

## Phase 7 authenticated media boundary

The Flask `freo` identity can write only a private upload staging directory. A generated job ID connects staged bytes to a database job. A separate `freo-ingest` process, with approved-media write permissions but no Liquidsoap control socket, calls the same `ingest()` service as the trusted CLI. It performs checksum, ffprobe, duplicate detection, and atomic storage. Web uploads are accepted disabled; a verify-and-enable job checks the stored file before making it selectable. Forms require an active global admin session and a per-session CSRF token, re-check station ownership, and write sanitized audit records. No browser operation accepts a server path, executes shell commands, or physically deletes media. See [media-library.md](media-library.md).

## Phase 9 imaging layer

`ImagingAsset` and `ImagingGroup` are distinct from music tracks and categories. They share controlled staging, ffprobe, checksum, and private station storage conventions. `ClockSlot` targets exactly one category, rotation, cart, or imaging group. `SelectionDecision` records either a music track or imaging asset; Liquidsoap's existing queue and event log confirm actual starts. Group recurrence uses imaging starts and pending holds, never artist separation. The web account still cannot write approved files or control Liquidsoap. See [imaging](imaging.md).

Phase 10 Live Assist stores station hold state, idempotent manual selection decisions, skip intents, and a sanitized worker-observed queue snapshot. The existing automation worker validates and pushes approved media and issues the single allowlisted skip command. The web process remains unable to access Liquidsoap sockets. See [Live Assist](live-assist.md).

Phase 11 keeps `TimedEvent` definitions separate from clock state and materializes bounded, unique `TimedEventOccurrence` rows. The existing worker prepares verified approved content, reduces lookahead, enforces timing/interrupt policy, and links a `timed_event` selection decision to the occurrence. Only Liquidsoap `on_track` confirmation marks it started. See [timed events](timed-events.md).

## Ordered event blocks

EventBlock definitions and immutable EventBlockExecution snapshots add bounded ordered sequences above Track and ImagingAsset. TimedEvent answers when a block starts; the block answers what plays in order. PostgreSQL state lets the existing worker own an active block and suppress normal refill until completion or abort. No new daemon or public port is introduced.
