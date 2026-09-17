# Station statistics

Implemented and deployed on 2026-09-17. Open **Admin → Statistics**, then choose **All channels** or an individual channel. Direct routes are `/admin/stats` and `/admin/stations/<slug>/stats`.

The six tabs cover audience, geography, confirmed music/artist plays, current likes/dislikes and approval, transfer/storage, and broadcast reliability. Date presets include the past hour, 24 hours, yesterday, week, month, year, calendar month/year, and custom dates. Calendar boundaries use the selected IANA timezone. Previous-period comparisons, accessible data tables and CSV export are included. Rankings are limited to the top 100 entries; the overview shows seven.

## What the numbers mean

- **Listeners:** sampled Icecast connections, not identified people. Average is time weighted; overall peak is the peak of simultaneous totals, not the sum of individual channel peaks. Current observations expire after 45 seconds. Missing intervals stay empty and coverage is shown.
- **Stream transfer:** differences in Icecast `total_bytes_sent`, with server/source instance UUIDs identifying resets. Measured channel bytes remain in overall totals even when another channel is unavailable; complete transfer coverage only advances when every channel is known. Reset intervals and collector gaps longer than 45 seconds are unmeasured. This is stream payload transfer, excluding website traffic, proxy/TLS overhead and provider billing. Month/year follow the selected timezone; total begins at collection startup. Partial boundary buckets are proportional estimates at the resolution given in API/CSV.
- **Geography:** approximate local DB-IP City Lite lookups; no raw addresses or user agents are stored in analytics. Unknown locations remain in totals. Stream connections expire after 45 seconds; player-page browser sessions after 90 seconds. The online map excludes clients missing from the latest successful list. Historical maps aggregate session-hours in overlapping UTC hours (a continuing session counts once per hour); all-time maps retain observed session visits per location (including a location resolved after an initially unknown observation) and geographic reach after short-lived observations are pruned. These are not deduplicated people. Sessions shorter than the observation interval can be missed. Player-page visitors are separate from stream listeners; directory visits are not assigned to a channel. Logged-in administrators and unpublished previews are ignored.
- **Music:** confirmed `SelectionDecision.started_at` records supply existing history immediately. Queue entries/previews are excluded. Metadata uses the current retained catalog; independently imported tracks/artists stay separate. Rotation coverage is the fraction of currently accessible tracks with a confirmed start. No listening completion or per-song audience exposure is inferred from nominal duration.
- **Feedback:** rankings use current accepted preferences across all time, excluding moderated votes. Activity follows the selected period. Durable transitions begin with this deployment and preserve preference changes/removals. Approval ranking requires at least ten votes.
- **Storage:** hourly read-only physical inventory of music, imaging, artwork files, database artwork, logos/thumbnails and every player image variant. Physical ownership determines channel attribution; shared references do not multiply overall storage. Retained/unreferenced files remain counted. Staging, host capacity and PostgreSQL allocated size are separate. Missing files and inaccessible paths are visible. Symlinks are not followed. Database allocation includes images already counted as payload and must not be added again.
- **Reliability:** observed mount availability, stale playout observations, expected offline mounts, sustained program RMS below −60 dBFS, failed selections, timed-event and commercial outcomes. Overall availability checks channels requested to run. Missing observations are not classified as proven downtime. Audible endings, fallback identification and audience exposure remain future instrumentation.

## Collection and operation

`freo-stats.service` runs every 15 seconds independently of Central reporting and automation. It only accesses fixed loopback Icecast statistics/client-list endpoints. Its systemd credential contains the Icecast admin password, without the engine source/relay secrets; it has no Liquidsoap socket-group access. Samples, aggregates, incidents and checkpoints commit in one transaction. Advisory locks serialize the collector and bounded public presence updates.

`freo-stats-inventory.timer` runs inventory hourly as the existing ingest account, with a read-only filesystem. `freo-geoip.timer` refreshes the local city database monthly. Geographic rendering, boundaries and the CSP-compatible MapLibre worker are served locally; browsers do not send map requests to an external tile provider. Provider attribution appears below the map. A failed update leaves the last valid database intact.

Retention: raw audience samples 14 days, minute buckets 90 days, hourly audience/geographic buckets five years, monthly/lifetime totals and geographic reach indefinitely. Expired presence rows are removed after one day. Storage snapshots last five years. Existing Central reporting retention and outbound payloads are unchanged.

Fresh provisioning applies migration `b185c9a027d6`, installs the pinned Python dependency, and calls `scripts/install-statistics.sh` after migrations. For an existing installation, the update order is dependencies → database backup → `flask db upgrade` → statistics installer → restart the web service. No playout restart is needed. `FREO_GEOIP_DATABASE` and `FREO_STATS_STATE_DIR` have defaults under `/var/lib/freo`; customized paths also require matching service filesystem permissions.

Useful maintenance commands, from `/opt/freo`:

```sh
systemctl status freo-stats.service
systemctl list-timers freo-stats-inventory.timer freo-geoip.timer
systemctl start freo-stats-inventory.service
systemctl start freo-geoip.service
journalctl -u freo-stats.service --since '1 hour ago'
```

## Deployment record

Live database backup: `/var/backups/freo/statistics-20260917T032108Z/database.dump`. Applied additive migration `b185c9a027d6`; started collector and inventory; installed September 2026 DB-IP City Lite. Listener/transfer/geographic history begins on deployment; existing confirmed plays and current preferences are available immediately. Migration upgrade/downgrade and collector/dashboard behavior were validated on a disposable PostgreSQL database before the production migration. Production Freo validation passed, including MP3 audio from the running streams.

Stopping the statistics collector/timers is sufficient to pause collection. To roll back application code, first stop these services and restore the previous code (including feedback hooks); preserve the additive analytics tables unless their history is intentionally being discarded. The migration downgrade drops the analytics tables and their history. Do not restore a full old database over newer live station edits merely to hide this screen.

Final verification included 75 backend regression tests, a Chromium desktop/mobile dashboard and public-player presence workflow, and deployed authenticated API checks for both managed channels. The initial overall availability buckets were reconciled against retained channel samples after correcting the treatment of intentionally stopped channels; listener and transfer totals were preserved.
