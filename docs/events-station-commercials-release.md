# Station audio and Events implementation

Activated on 19 September 2026. Application commit `9a7c02a` was pushed to `origin/main`; the database and both running station engines have been upgraded.

## Operator workflow

New stations receive Playlist 1, Playlist 2, STATION, and COMMERCIALS. The database upgrade adds the two system collections to existing stations without replacing custom playlists, including custom playlists with the same names. System collections are identified by their purpose, not their names.

Choose Music, STATION, or COMMERCIALS when importing audio, editing an audio item, or classifying selected library items. STATION supports `station_id`, promo, announcement, jingle, sweeper, liner, cart, and generic labels. Classification maintains the system collection automatically. These two collections cannot be deleted; reclassify an item to remove it. Station and commercial audio stays private to its owning station and is excluded from ordinary music fallback.

Events can select a playlist, individual audio, or an ordered sequence. Search prioritizes STATION and COMMERCIALS, then other playlists and individual audio; it supports titles, artists, filenames, cart codes, tags, and station audio labels. Playlists can be searched internally. STATION defaults to one rotating item; COMMERCIALS defaults to the entire playlist once. Full event sequences are snapshotted and submitted together, preserving their order and preventing music between commercials. Sequences support up to 500 items.

Events support one-time, every 15 minutes, hourly, daily, weekly, and monthly schedules. Interval rules use selected local days/hours. A quarter-hour rule at `00:05` runs at :05, :20, :35, and :50. Monthly rules include a day number, the last day, and an ordinal/last weekday; absent dates are skipped. All input, previews, and displayed execution times use the station timezone from Settings. Daylight-saving gaps shift forward; repeated wall times execute once. Future one-time events retain the entered wall time if the timezone changes.

New events wait for the current song to finish. An event already waiting for that boundary does not expire because a song is longer than the recovery allowance. INTERRUPT DJ defaults to No. Yes allows an event sequence after the current audible DJ song, preserves DJ mode, and returns control after completion. Live microphones remain protected. Existing HARD events retain their explicitly labelled legacy policy unless converted in the editor.

Target time, then descending priority, then occurrence ID determine ordering. An active sequence finishes before another event starts. Stale repeats are coalesced under the default Skip policy; unavailable DJ/outage events have a bounded recovery allowance. Duration-overlap warnings help identify conflicting schedules. Edits invalidate obsolete preparation, and cancellation removes pending engine requests. Confirmed playback history remains available separately from paginated upcoming occurrences.

## Activation and existing Imaging data

Deploy the application and engine template together in a planned station maintenance window. The new worker requires the new engine commands.

1. Back up the database and station media. Stop station playout and worker processes through the installation's normal operations procedure; finish pending Imaging ingest jobs first.
2. Apply the schema with `venv/bin/flask --app app db upgrade` using the installation's normal environment. The new revision is `e28a91bc7304`.
3. For each station, run `venv/bin/flask --app app migrate-station-audio --station SLUG` to inventory legacy assets, checksum/file problems, duplicates, and references. Set the station's desired state to stopped and reconcile any stale queued requests before conversion.
4. Resolve enabled missing/corrupt assets. If a legacy asset duplicates existing catalog audio, review the match and provide `--mapping PATH`, containing a JSON object mapping the legacy asset ID to the existing track UUID.
5. Run the same command with `--apply`. It copies verified audio into the regular catalog, classifies it, converts groups to playlists, and remaps events, clock slots, carts, traffic, ingest jobs, and playback/history references. Re-running is supported. Original Imaging files and database records remain as migration/history evidence; the retired feature has no write routes or registered Imaging CLI.
6. Inventory again and verify every reported legacy asset reference count is zero. Render each station with the existing `flask --app app station render SLUG` command and restart through the normal operations procedure. Verify an ID and a commercial sequence on the station before returning it to service.

An Alembic downgrade is intentionally rejected after this conversion-capable migration. Roll back the application, database backup, media backup, and prior station engine configuration together.

## Verification

The implementation was exercised with SQLite service/route tests, Selenium browser tests, disposable PostgreSQL migrations/concurrency tests, and isolated Liquidsoap engines rendering temporary audio to files. No test used production media or changed a live station.

Final verification: **270 distinct tests passed**.

- Scheduling, events, playlist, traffic, DJ controls, Live Assist, Imaging retirement, and calendar regressions: 173 passed.
- Final event editor and event service checks: 21 passed, including two additional timezone/cancellation tests (the other service cases and browser case overlap the other runs).
- Event, playlist, and import browser workflows: 4 passed.
- Catalog, media, import, station, and settings regressions: 75 passed.
- Real imports classified as STATION / station_id and COMMERCIALS: 2 passed.
- Disposable PostgreSQL migration and station/scheduling concurrency checks: 8 passed.
- Isolated Liquidsoap audio sequencing: 6 passed, covering insertion with two or six queued songs, atomic full sequences, and two-item DJ event sequences on decks A and B.

Python compilation, JavaScript syntax checks, and `git diff --check` passed. Remaining warnings are the existing playlist fixture's SQLAlchemy session warning and the migration tooling's deprecated `get_engine` API. These tests validate repository behavior. Deployment checks are recorded below.


## Deployment — 19 September 2026

- Backups: `/var/backups/freo/events-20260919T014709Z`. Includes a verified custom-format database dump taken after pausing writers, the previous committed application, media/configuration archive, and original station states.
- Applied migration `e28a91bc7304`. Converted five verified Imaging assets on Freo Demo into four STATION items and one COMMERCIALS item. All five retained their disabled state; original files remain preserved. Legacy reference counts are zero. Freo Demo Two had no Imaging assets to convert.
- Both stations now have Playlist 1, Playlist 2, STATION, and COMMERCIALS. Freo Demo retained America/Denver; Freo Demo Two retained UTC. Both retained running/AUTO state.
- Rendered and validated both Liquidsoap configurations. Restarted the web, automation, ingest, central API, statistics, and both station playout services; resumed maintenance timers.
- Re-ran 30 focused event/browser tests before deployment: all passed.
- Post-restart checks passed for HTTP health/readiness, automation, Icecast, public station data, updated JavaScript, authenticated Events/create/playlist pages, Imaging redirects, prioritized audio search, and recurring local-time previews.
- Both live engines answered the new event protocol, delivered 8,192 MP3 stream bytes, and had fresh worker heartbeats. Web, automation, ingest, and both station engines reported active with zero restart loops. The converted disabled audio was not aired as part of validation.
- Full installation validation passed. The previously failed statistics inventory completed successfully after retry; no Freo service units remained failed.
