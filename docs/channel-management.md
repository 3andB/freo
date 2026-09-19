# Station lifecycle and shared music

Stations and channels refer to the same broadcast unit. Fresh installs contain no
managed stations. An active global administrator can add or delete stations at
**Admin → Stations**. A station starts stopped; the existing root CLI starts and
stops its broadcast.

## Installation and upgrades

The default limit is `FREO_MAX_STATIONS=3` in the server environment. Set another
non-negative integer to change it; `0` means unlimited. Restart the web service
and ensure the provisioning CLI/timer uses the same environment after changing
it. Stopped, disabled, provisioning, and failed stations count toward the limit.
A completed deletion frees a slot. Lowering the limit never deletes stations.
Creation is serialized in PostgreSQL, including an initially empty database.

Run the database migration before starting the updated application:

```sh
venv/bin/flask --app wsgi:app db upgrade
```

The installer installs `freo-provision.service` and `freo-provision.timer`.
For an existing installation, install those two files from `deploy/systemd` into
`/etc/systemd/system`, run `systemctl daemon-reload`, and enable the timer with
`systemctl enable --now freo-provision.timer`. Restart the web, automation, and
ingest services after upgrading their code. Back up the database and media first.

The timer runs the root-only `station process-pending` command. Browser requests
only record validated intent. This worker accepts no user-supplied commands,
service names, configuration paths, or executable code. Failed operations remain
visible on the Stations page with a Retry control. The CLI also offers
`station retry <slug>`. A crash before completion leaves an operation that can
be safely rerun. Filesystem changes and database commits are not one transaction.

The optional diagnostic tone stream is **off by default on fresh installs**.
Install with `FREO_ENABLE_DIAGNOSTIC=1` to enable and validate it. Existing enabled
diagnostic services are not stopped by an upgrade. With no diagnostic stream,
`/health/playout` and `/health/stream` still describe that optional fixture;
use `/ready`, `/health/icecast`, `/health/automation`, and managed station status
for installation checks. The installer adjusts its checks accordingly.

## Scripted setup

Run from `/opt/freo` as the server administrator:

```sh
venv/bin/flask --app wsgi:app station create user-radio \
  --name 'User Radio' --timezone UTC --if-not-exists --json
```

This waits for configuration validation and provisioning. Add `--start` to start
the stream and wait for audio. `--if-not-exists` resumes an identical setup
request, including a failed provisioning attempt; it rejects different name,
description, or timezone settings. JSON output goes to stdout, failures return a
nonzero status, and error output does not include source credentials.

```sh
venv/bin/flask --app wsgi:app station delete user-radio --yes --json
```

Deletion disables selection, stops and disables that specific playout unit,
removes its source credential, Liquidsoap configuration, playlist, and Nginx
snippet, and reloads shared configuration. Other station processes are not
restarted. Failed cleanup keeps the station disabled and its slot reserved until
retry succeeds. Repeating deletion of an already deleted station is a no-op.

Deletion archives the database identity, programming, and history. It retains
**all media**, including private uploads and shared music. Pending ingest jobs
are rejected; already-running analysis can finish against retained files.
Station slugs and URL aliases stay reserved to prevent an old listening URL or
storage namespace from silently identifying a different station. Use a new slug
for a replacement station. Permanent archival-media purge and restoration are
not exposed by the station-delete command.

## MAKE AVAILABLE TO ALL CHANNELS

Artist, album, and song detail pages contain this option. It includes stations
created later:

- An artist shares its current and future songs.
- An album shares its current and future songs.
- A song shares that song.

The effective rule is **song OR album OR artist**. Turning off the song checkbox
does not override a shared album or artist. Pages explain inherited sharing.
Sharing does not enable a disabled song or bypass approval, decommissioning, or
file validation. Each channel assigns its own categories and tags. Music metadata,
audio settings, and broadcast enable/disable belong to the shared catalog; edits
to those fields affect every channel using the song. All current accounts are
global administrators.

Audio stays in its original immutable storage namespace; sharing never copies
files and deleting the originating station never removes shared audio or artwork.
Library discovery, previews, category selection, events, blocks, AUTO, DJ decks,
and song carts use the same availability rule.

Removing sharing is blocked if another channel has a selected/queued decision or
is running with playback history for that song (a conservative check also covers
paused decks). Stop the consuming channel and clear queued selections first.
Existing category/event/block references remain, but availability is checked
before future selection and again before the engine receives audio. Unavailable
references are reported by the existing validation/playback status. Shared music
can be permanently deleted through the master-library song-delete action, which
removes its song-level references across all channels automatically.

## Verification

The tests include zero-station routes, browser creation/sharing/deletion, default
and changed limits, alias conflicts, failed create/delete retries, repeated
create/delete cycles, retained shared audio/artwork, category isolation, and
revocation. Runtime cleanup failure injection checks that neighboring station
files and processes are untouched.

```sh
venv/bin/pytest tests/test_station_lifecycle.py tests/test_channel_availability.py
venv/bin/pytest tests/test_station_lifecycle_browser.py
FREO_ENGINE_TEST=1 venv/bin/pytest tests/test_station_streams.py tests/test_deck_engine.py
FREO_TEST_POSTGRES_URL='<disposable database URL>' venv/bin/pytest tests/test_station_postgres.py
```

The PostgreSQL test requires an empty, disposable database and exercises migration
upgrade/downgrade and eight simultaneous creations. The audio test uses temporary
Icecast/Liquidsoap processes, the real station template, and Liquidsoap validation.
Its Icecast configuration is generated in the test; systemd supervision and Nginx
reloads are substituted. It never controls installed production services.
A separate clean Ubuntu VM and full systemd/reboot acceptance remain necessary
before claiming the public installer has been validated end to end.
