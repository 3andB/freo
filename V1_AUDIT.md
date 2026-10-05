# Freo V1 implementation audit

Audit date: 4 October 2026. Audited branch: `develop/v1`, source commit
`32495f607711a432c08973abeaf979973c9ee2ad`, in the separate `/opt/freo-v1`
worktree. This is an implementation inventory and release recommendation, not an
authorization to implement or deploy V1.

Production remains 0.3.2 at `83200e6508654bea13f404e9d5699a8ad3eae19d`, frozen
by `v0.3.2` and `production/v0.3.2-2026-10-04`. The audited development base
differs from that production source only in documentation and ignore rules.
See [the frozen baseline](docs/production-baseline-2026-10-04.md) and
[production deployment record](docs/production-0.3.2-2026-10-01.md).

## Audit method and classification

Reviewed application factories, model definitions, migration scripts, route
decorators and handlers, services/workers, frontend scripts/templates, generated
radio configuration, systemd units, installer/updater/recovery code, tests, and
release/feature documentation. Static inspection found **50 migration revisions,
one head (`c83d4e5f9012`), and 155 route decorators** across the route modules.
Route count includes HTML and dynamically dispatched action routes; it is not a
count of public API operations.

No application was started and no production database, service, media, generated
configuration, or deployment was changed for this audit. No `.env`, runtime
symlink, or production virtual environment was copied into the development
checkout. Two isolated, in-memory probes executed only extracted pure selector
functions: Straight playlists accept consecutive same-artist tracks; the
category selector relaxes artist before track separation when candidates are
exhausted. No application imports or database connections were needed.

Existing tests were read, not rerun as a full regression suite. Historical
[0.3.2 acceptance](docs/0.3.2-acceptance.md) records 1,273 passes and three optional
skips across retained runs, plus fresh-VM installation/reboot and separate
upgrade/recovery evidence. That is supporting evidence, not new V1 certification.
The final owner VM did not validate public certificate renewal or remote live
microphone use. Actual customer data composition and host customizations require
a separate authorized pre-upgrade inventory; models alone cannot prove them.

| Classification | Meaning in this audit |
| --- | --- |
| **COMPLETE** | Existing bounded feature has an end-to-end implementation and supporting release/test evidence; preserve it. This does not certify extensions, arbitrary scale, or every deployment. |
| **PARTIAL** | User-facing behavior exists, but part of the requested capability is absent. |
| **FOUNDATION** | Reusable underlying mechanisms exist, without the requested finished feature. |
| **MISSING** | No implementation of the requested capability was found in the reviewed source. |
| **REFACTOR** | Existing behavior/contracts need a focused change before the dependent V1 capability is safe. This does not mean replacing the subsystem. |

Missing findings are based on model, route, worker, frontend, template and source
searches, not merely absence from navigation or documentation. Liquidsoap
`request` means an engine media request, not a listener song request. “Cue” also
names a DJ playlist feature, which is distinct from per-track cue-in/out.

## 1. Current architecture relevant to V1

### Application and authority boundaries

`app/__init__.py` assembles one Flask application with SQLAlchemy/Flask-Migrate
(`app/extensions.py`), blueprint routes and CLI groups. Gunicorn serves the app
behind Nginx. Jinja templates plus plain JavaScript implement the UI; this is not
a separate SPA/API product. `app/static/workspace.js` coordinates navigation and
page lifecycle; feature scripts maintain their own forms, polling and controls.
Preserve workspace cleanup, live-mic departure handling and autosave behavior.

Browser mutations normally use authenticated sessions and CSRF, then write
validated database state or worker intent. `app/services/admin_auth.py` implements
the common boundary. `admin_users`, `admin_login_sessions` and `admin_bootstrap`
support first-use setup, password authentication and revocable login sessions.
`installation_admin` separately restricts software/license operations. Ordinary
programming/playout/statistics permission helpers currently authorize all active
admins; there is **no customer/tenant membership or restricted DJ role model**.

| Runtime component | Existing responsibility and source |
| --- | --- |
| `freo.service` | Flask/Gunicorn as `freo`; web account can stage uploads, not write approved media or control Liquidsoap sockets. `deploy/systemd/freo.service`. |
| `freo-automation.service` | `app/automation_worker.py` as `freo-automation`; selects content, reconciles actual starts, controls queues/decks/events through private sockets, persists observations. |
| `freo-ingest.service` | `app/ingest_worker.py` as `freo-ingest`; approved media writes, ingest jobs, analysis and compatible previews. |
| `freo-playout@<slug>.service` | One Liquidsoap process per station as `freo-playout`; generated config, socket and event log per station. Diagnostic `freo-playout.service` is separate. |
| `icecast2.service` | Shared private Icecast backend at loopback port 8001; Nginx publishes controlled station listener paths. |
| `freo-mic.service` | `app/mic_gateway.py`; aiortc/WebRTC receiver and bounded PCM delivery on loopback 8091. Ephemeral mic sessions. |
| `freo-provision.timer/service` | Root-run allowlisted station provisioning/lifecycle, domain and audio-settings work; validated rendering in `station_runtime.py`, not arbitrary commands from web requests. |
| `freo-stats.service` | Independent 15-second Icecast collector as `freo-stats`, with admin-only Icecast credential; no Liquidsoap socket access. |
| Statistics inventory / GeoIP timers | Read-only storage inventory as ingest identity; monthly local GeoIP update as stats identity. |
| `freo-public-schedules.timer` | Publishes public schedule snapshots away from the playout worker's timing path. |
| `freo-central-api.service` | Outbound installation enrollment, registration/licensing, heartbeat, aggregate reporting and release discovery. External central server is not implemented here. |
| `freo-updater.timer/service` | Root executes explicitly approved, root-prepared signed upgrade plans; separate from station provisioning. |

Service templates retain legacy `/opt/freo` paths; `freo_ops/upgrade.py` rewrites
managed units to `/opt/freo/current` and `/etc/freo/freo.env` during versioned
adoption. Do not confuse source-template paths with the recorded installed unit
paths. The new development checkout is not a second running installation; fresh
provisioning currently supports only `/opt/freo` on a dedicated Ubuntu 24.04
x86_64 host. Development integration tests need disposable hosts/isolated fixtures.

### Data and playout flow

```text
Browser / CLI -> validated service -> PostgreSQL state / durable intent
                                    |
                          automation worker (single control authority)
                                    |
                         allowlisted Unix-socket commands
                                    v
                 Liquidsoap queues / decks / events / microphone
                         -> processing + limiter -> Icecast -> Nginx
                                    |
                 actual-start / completion observations -> PostgreSQL

Upload -> private staging -> ingest worker -> immutable original + analysis/preview
Icecast observations -> stats collector -> samples, aggregates, presence, incidents
```

Principal tables, in [models](app/models/__init__.py),
[scheduling models](app/models/scheduling.py), [cue models](app/models/cue.py),
[import models](app/models/imports.py), and [statistics models](app/models/statistics.py):

- Station/runtime: `stations`, `stream_mounts`, `station_domains`,
  `station_aliases`, `automation_states`, `automation_heartbeat`, `live_queue_snapshots`.
- Library: `tracks`, `artists`, `albums`, `music_artwork`, `music_tags`,
  `song_tags`, `media_categories`, `track_categories`, `media_ingest_jobs` and
  import-session/item tables. Song remains the original Track identity.
- Programming: `rotations`, `rotation_slots`, `clocks`, `clock_slots`,
  `schedule_assignments`, `schedule_programs`, `clock_states`, `rotation_cursors`,
  `playlists`, `playlist_items`, `playlist_cursors`; modern `channel_schedules`,
  `schedule_compositions`, immutable `schedule_composition_revisions`,
  `schedule_transitions`, `schedule_cursors` coexist with legacy programming.
- Actual playout: `selection_decisions`, `live_control_commands`, `live_cart_slots`,
  `booth_cues`, `saved_booth_cues`, `cue_playbacks`, `cue_mutations`.
- Events/traffic: `timed_events`, `timed_event_occurrences`, `event_blocks`,
  `event_block_items`, execution/item-execution snapshots, advertisers, campaigns,
  commercial creatives, stopsets, traffic logs/placements and cancellation intents.
- Public/UI: `station_player_settings`, `station_player_assets`,
  `public_schedule_revisions`, `listener_votes`, `listener_feedback_events`,
  website publication/assets/settings, `song_flags`, `music_edits`, `audit_events`.
- Installation: `installation_settings`, `software_license`, `system_upgrades`,
  central installation/station-state/hourly-metric records.

Music, STATION audio and COMMERCIALS now share `tracks.audio_kind`. STATION
subtypes include station ID, jingle, promo, sweeper, liner, announcement and cart.
Permanent STATION/COMMERCIALS playlist collections already exist. Legacy
`imaging_assets`/`imaging_groups` and references remain for compatibility;
`app/services/imaging_migration.py` supplies an explicit, resumable conversion.
`app/routes/admin_imaging.py` now redirects retired Imaging screens. Do not build
a new parallel station-ID asset system from the older architecture document.

Storage ownership is `station_id`; `available_to_all` on tracks/artists/albums
permits installation-wide sharing through `app/services/availability.py`. This
is useful multi-station behavior, **not tenant isolation**.

## 2. Feature-by-feature inventory

### 0. Upgrade system — PARTIAL for V1; substantial existing implementation

| Capability | Status | Evidence and exact boundary |
| --- | --- | --- |
| Installed version and release identity | **COMPLETE** | `app/version.py` is 0.3.2; `freo_ops/releases.py` emits signed-payload manifest with version, commit, schema head, platform, Python, file hashes/modes/sizes, and hashed dependency wheels. `freo_ops/__main__.py:installed_version()` parses version without booting Flask. |
| Update availability/status | **COMPLETE** | `app/services/central_api/releases.py` projects server heartbeat status (`CURRENT`, `UPDATE_AVAILABLE`, `AHEAD`, `UNKNOWN`) and optional discovery metadata; stale/changed-running-version states are explicit. `central_api/client.py` calls external `/v1/releases/latest`; it does not install anything. `tests/test_versions.py`, installation UI. |
| Fresh installer | **COMPLETE** for accepted platform | `scripts/install.sh`, `provision.sh`, `install-python.sh`; guards detect existing environment/runtime/media before replacement, install dependencies and PostgreSQL schema, bootstrap services/admin, validate vhost. Never rerun fresh installation on 0.3.2. See `tests/test_installer_guard.py`, `test_dependencies.py`, `test_admin_validation_nginx.py`. |
| Signed managed upgrade | **COMPLETE** within current compatibility envelope | `freo_ops/upgrade.py:upgrade()` validates/stages release, uses offline wheels/separate venv, locks and journals operation, stops recorded active units under persistent maintenance guards, backs up and actually restores before migration, checks preservation, switches runtime pointer, restarts previous active units and checks audio. Supported platform is Ubuntu 24.04 x86_64 / Python 3.12. |
| Browser upgrade workflow | **COMPLETE** for root-prepared plans | `freo_ops/web_updates.py` prepares immutable private plans; `system_upgrades` records state. `POST /admin/software/upgrades/<identifier>` requires installation admin, CSRF and maintenance acknowledgment. Root timer executes the plan; no arbitrary upload-to-root-shell route. It uses installed updater code, which matters for future compatibility changes. |
| Schema versioning | **COMPLETE** | Alembic chain ends at `c83d4e5f9012_revocable_admin_logins.py`; startup does not auto-migrate. `/ready` checks exact release migration head plus adopted installation settings (`app/routes/health.py`). Historical migrations must remain immutable. |
| Encrypted backup and isolated restore | **COMPLETE** for full, quiesced recovery bundles | `freo_ops/recovery.py` exports a PostgreSQL snapshot, custom-format dump, row-value/sequence inventory, file hashes and ownership/mode/ACL metadata; verifies unchanged state. Restore creates a new `freo_restore_<id>` DB and new directory, verifies rows/sequences/schema/files and never overwrites live DB. `verify` alone is integrity verification, not restore proof. |
| Configuration preservation | **COMPLETE** for inventoried roots/settings | `freo_ops/__main__.py:inventory()` includes explicit env, `/etc/freo`, durable state, optional Nginx/TLS/PostgreSQL config and service units; configured media/upload/API/stats/GeoIP roots included. `installation_settings` is revisioned; `import_environment()` preserves adopted values. Secrets stay in protected host files. |
| Media/storage preservation | **COMPLETE** for declared existing roots | Original and pending-upload references checked against captured files/checksums; originals, images, settings and persistent import state are preserved. A new recording/generated-audio/custom storage root must explicitly enter inventory and restore tests. Browser-local drafts are not a server backup. |
| Upgrade health checks | **PARTIAL** for future V1 breadth | Current checks cover exact schema/settings readiness, active units and bounded managed-station audio reads. `scripts/validate-install.sh` adds dependency, permissions, private listener, HTTP/radio validation. Neither HTTP 200 nor MP3 bytes prove correct schedule, cue/fade behavior, remote microphone, TLS renewal or request policy. |
| Rollback | **PARTIAL** | Pre-migration failure attempts to resume old active units. Post-migration failure retains maintenance/recovery-required state and diagnostic journal. Recovery is an operator-controlled matched release+DB+files restore into new locations; no one-click automatic rollback or safe general downgrade. Preserve newer writes and reconcile/forward-fix. |
| General V1/V1.x compatibility | **REFACTOR** | Static supported-source revision list, template-change refusal, existing-unit-only activation and strict old-row preservation require deliberate extension before affected V1 migrations/engine/service features. Detailed gates in section 9. |

Preserve the updater, release format, publisher trust, explicit maintenance
window, matched recovery and immutable version contents. A V1 button or new
installer is not needed to replace these capabilities. Automated downloads,
incremental backups, retention pruning, cross-platform upgrades, PostgreSQL major
upgrades and zero-downtime broadcasting upgrades are not provided.

### 1. Advanced scheduling / smart playlists — PARTIAL; selective REFACTOR

| Capability | Status | Evidence and extension needed |
| --- | --- | --- |
| Calendar, reusable shows/blocks, simple looping | **COMPLETE** within existing modes | `visual_schedule.py`, `schedule.py`, `schedule_documents.py`, `schedule_switch.py`; `channel_schedules` supports CALENDAR/BLOCKS/SIMPLE; immutable compositions, recurrence/exceptions, station-local time/DST, revision conflict handling and worker-acknowledged mode switching. UI: `schedule_studio.html`, `schedule_studio.js`, `schedule_editor.js`, `schedule_studio.py`, `admin_calendar.py`. |
| Legacy clocks and explicit rotations | **COMPLETE** | `clocks.py`, `automation.py`, `rotations`/slots and clocks/slots; ordered category/rotation/cart/group/event/playlist slots, durable cursors, default-clock/rotation fallback. Preserve existing customer schedules and their compatibility path. |
| Ordinary playlist editing/playback | **COMPLETE** | `playlists.py`, `playlists`/items/cursors; explicit unique membership/order, STRAIGHT and RANDOM, availability filtering, revision checks, non-destructive removal/Undo. `playlists.html`, `playlists.js`, Music bubbles, `routes/playlists.py` and `routes/sound_room.py` action dispatcher. Adds from category/artist/album copy current membership, not a live query. |
| Artist and track separation | **PARTIAL** | `AutomationState.artist_separation_seconds`/`track_separation_seconds` and `automation._choose()` enforce windows for category/rotation path, include pending holds, use normalized artist strings and least-recently-started selection. On exhaustion relax artist, then track; defaults are zero. Ordinary `playlists.advance()` and `visual_schedule.select_visual()` do not apply that policy, including modern visual category sources. |
| Random-cycle continuity | **COMPLETE**, preserve semantics | RANDOM avoids repeats within cycle and avoids immediately repeating the last track across cycles when alternatives exist. Modern shuffled source cursor survives block/occurrence boundaries and worker restarts; `select_playlist()` also retains RANDOM state across occurrences. STRAIGHT resets at a new occurrence. `tests/test_rc4.py` and `test_playlists.py` encode this; older `docs/playlists.md` says every occurrence starts fresh and is outdated. |
| Categories/tags | **COMPLETE** for catalog organization | `media_categories`, `track_categories`, `music_tags`, `song_tags`; tagging/category UI in Music and `admin/tags.html`, `music_tags.js`. Source search can match tags. HIT/FAVORITE/SPONSORED starter labels do not automatically weight selection. |
| Dynamic smart-playlist rules | **FOUNDATION** | Source filters and metadata (artist/album/category/tags/BPM/genre/year), availability, history and cursors exist. No persisted general smart-rule engine, tag-expression playlist, numerical weights, BPM progression or automatic membership reevaluation on ordinary playlists. `Track.scheduling_restrictions` currently stores free-text notes, not enforced scheduling rules. |
| Weighted rotation/selection | **PARTIAL** | Repeating category slots supplies explicit frequency weighting; `_choose()` uses least-recently-started, RANDOM uses `random.choice`. No configurable track/category probability weight engine. Campaign priority in traffic is unrelated to music weighting. |
| Ordering and priority | **PARTIAL** | Playlist positions, slot ordering, timed-event timing/interrupt policy and traffic placement priorities exist. No general playlist-to-playlist priority arbitration. Mode selection and validated scheduled occurrences should remain authoritative; do not add a competing scheduler. |
| Optional playlist leader | **MISSING** as a feature; strong foundation | `Playlist` has no leader track/asset reference and neither selector has leader-first logic. `system_key=PLAYLIST_1/PLAYLIST_2` and migration `f38c6a902e17` only identify/order starter collections. A song at position 1 is not a leader independent of shuffle/order or fallback. |

**Recommended leader extension:** add an optional reference to an approved Track
(MUSIC or station-owned STATION audio), reusing the existing classified-audio
library rather than reintroducing Imaging. Expose it in the existing playlist
editor and include it in programming signatures, availability/deletion validation
and revision checks. Where legacy imaging remains, use explicit conversion or
reviewed compatibility mapping, never a second leader asset store.

“Whenever a playlist begins” needs an occurrence contract shared by ordinary and
visual scheduling: a new playlist activation/occurrence must play the leader
before its first normal member; worker restart, lookahead refresh and transient
retry must not spuriously repeat it. Persist pending/confirmed leader state using
selection decisions and existing checkpoint/reconciliation machinery. Preserve
random membership progress separately from leader occurrence state. Define/test
repeat-cycle versus reactivation, consecutive same-playlist blocks, manual cue
use, timed-event playlist snapshots, missing/disabled/deleted leader, and stop/
resume. Recommended default: one leader per explicit occurrence, not per shuffle
cycle or worker restart; unavailable leader fails the leader requirement visibly
and uses configured fallback rather than silently claiming it played. These are
proposed semantics, not existing behavior; lock them in before implementation.

**Freo versus Liquidsoap:** Freo owns policy, candidate choice, station/customer
authorization, scheduling times, priority, durable occurrence/cursor state and
confirmed history. Liquidsoap owns resolving/decoding queued approved local
audio, sample-time playback, transitions/mixing, engine-level readiness/fallback
and output. The managed engine uses `request.dynamic` and deck/cart queues; it
does not currently choose random music or enforce artist/track separation.
Keep one selection authority. Extend shared policy helpers behind existing
selectors with opt-in rules, preserving explicit Straight order and documented
shuffle behavior unless the operator chooses a new policy.

Evidence: `tests/test_automation.py`, `test_playlists.py`, `test_rc4.py`,
`test_visual_schedule.py`, `test_programming_refresh.py`, `test_schedule_engine.py`,
`test_schedule_postgres.py`, `test_schedule_soak.py`, `test_timed_events.py`,
`test_event_blocks.py`; corresponding schedule/playlist browser suites.

### 2. Listener analytics — mostly COMPLETE; sessions/devices PARTIAL

| Capability | Status | Evidence and interpretation |
| --- | --- | --- |
| Current listeners/status | **COMPLETE** | `broadcast_status.py` combines fresh stats and worker snapshots; `statistics/icecast.py` polls private `/admin/stats` and per-mount `/admin/listclients`. Unknown/stale data is not zero. Current worker/status and analytics expiry policies differ intentionally. |
| Historical audience, peaks and duration aggregates | **COMPLETE** | `stats_samples`, `stats_buckets`, `stats_states`; `statistics/collect.py` accumulates listener-seconds/observed-seconds, time-weighted averages, simultaneous all-channel peaks, online time and transfer deltas with source/server reset handling. Listener-hours are connections over observed time, not identified people. |
| Individual sessions/duration reporting | **PARTIAL** | `stats_presence` has pseudonymous key, source, first/last seen and geo; `stats_geo_buckets` and `stats_geo_reach` retain session/hour and duration aggregates. No durable exact connect/disconnect session ledger or finished duration-distribution/completion report. Polling can miss short sessions; hourly session counts are not unique people. |
| Geography | **COMPLETE** for approximate local GeoIP | `statistics/geo.py`, DB-IP City Lite, `freo-geoip.timer`, current/historical/lifetime maps; local MapLibre assets in `app/static/vendor/maplibre`. Unknown locations remain in totals; browser-presence and stream listeners stay separate. |
| Device/client breakdown | **FOUNDATION** | `statistics/icecast.py` reads transient `useragent`; analytics do not persist raw IPs/user agents or device/browser/OS classes. No device chart or classifier. Add minimized aggregate classifications if needed, not raw identifier retention by default. |
| Icecast statistics ingestion | **COMPLETE** for polling | Bounded credential-isolated XML fetches, 15-second collector, checkpoints/locks, expiry and counter resets; Icecast 2.5 proxy trust configuration. |
| Access-log ingestion | **MISSING** | Icecast template directs access/error logs to `-`; no durable access-log tailer, offset/replay parser or disconnect-log session importer found. Do not describe current polling as log ingestion. |
| Dashboard/charts/export | **COMPLETE** | `routes/statistics.py`, `admin/statistics.html`, `statistics.js/css`; audience, geography, plays, feedback, storage/transfer and reliability, date windows/timezones, comparisons, tables and CSV. `/admin/stats[/data|/export.csv]` and station equivalents. |

Retention is already implemented: samples 14 days, minute buckets 90 days,
hourly audience/geography five years, monthly/lifetime totals/reach indefinitely;
expired presence one day, storage snapshots five years. Reuse these aggregates
and UI. Extend with explicit sampled-session metrics or tested log ingestion only
if exact session requirements justify it. A device breakdown must fit existing
privacy and retention behavior. Scope-zero aggregate statistics currently mean
**the entire installation**, so customer-level totals need authorization/scoping.

Evidence: `app/models/statistics.py`, `app/services/statistics/`,
`deploy/systemd/freo-stats*.service`, `scripts/install-statistics.sh`,
`tests/test_statistics.py`, `test_statistics_browser.py`, `docs/statistics.md`.

### 3. DJ/live improvements — PARTIAL

| Capability | Status | Evidence and boundary |
| --- | --- | --- |
| DJ Booth, decks, carts and saved Cue | **COMPLETE** for current admin operators | `live_assist.py`, `booth_cue.py`, `playout_queue.py`, `live_control_commands`, `live_cart_slots`, Cue tables; A/B decks, crossfader/fades, station-ID and hot-cart slots, prepared AUTO return, saved/rotating Cue. UI `live.html`, `_dj_deck.html`, `_booth_cue.html`, `live.js`, `booth_cue.js`. |
| Restricted DJ accounts/permissions | **REFACTOR** | Authentication works, but `can_control_playout()` and `can_manage_programming()` permit every active admin. No per-station DJ grant, show-time authorization or separate encoder credentials. Preserve login/session revocation and extend centralized permission boundaries plus every caller/query. |
| Browser live microphone | **COMPLETE** for implemented WebRTC path | `routes/live_mic.py` actions `status/offer/heartbeat/go/end/disconnect/config`; gateway ownership by admin and tab token, off-air test, observed readiness, gain/mute, PCM delivery and gated GO LIVE. UI `_live_mic.html`, `live_mic.js`; physical devices/WAN ICE/TURN still need deployment acceptance. |
| Live detection and automatic fallback | **COMPLETE** for browser microphone | Gateway tracks arriving RTP/heartbeat; Liquidsoap `freo_mic` phase/readiness and six-second worker lease. Input/lease loss closes mic and returns AUTO. Intentional exit returns the interrupted feed; it is distinct from abrupt-loss fallback. Preserve tested no-buffered-speech replay behavior. |
| External encoder/live-source ingest | **MISSING** | No managed `input.harbor`, DJ source-login model, external ingest mount UI, encoder handoff rules or public source port. The template's `input.http` is a private mic-gateway input, not configurable remote DJ ingest. |
| Show/session recording | **MISSING** | Gateway explicitly keeps sessions ephemeral and records no audio. No managed `output.file`, recording table/job, recording root, retention/download interface or recording scheduler. Audio capture in test harnesses is not a user feature. |

Preserve `deploy/liquidsoap/station.liq.template`'s worker-controlled program/deck/
event buses, microphone gates, output limiter and backup tone. Silence protection
uses a three-second blank detector and a synthetic tone; this is not a configurable
emergency music playlist or proof that any live speech pause is a disconnected
source. Transport readiness and acoustic silence are separate signals and need
explicit acceptance for future external-source/relay behavior.

Evidence: `tests/test_live_mic.py`, `test_live_mic_browser.py`, `test_dj_return.py`,
`test_dj_return_audio.py`, `test_deck_engine.py`, `test_cue_engine.py`,
`test_master_broadcast_engine.py`, `docs/live-mic.md`, `docs/dj-booth-cue.md`.

### 4. Track editor — PARTIAL; cue application requires REFACTOR

| Capability | Status | Evidence and boundary |
| --- | --- | --- |
| Metadata editing | **COMPLETE** | `Track`/Artist/Album identity; title, artist, album/album artist, disc/track/year, genre, ISRC, artwork, tags/categories, notes, enablement and sharing. `catalog_edit.py`, `routes/catalog_editor.py`, `routes/admin_media.py`; `media_track.html`, `media_editor.js`, `catalog_controls.js`. |
| Cue-in/cue-out/segue editing | **PARTIAL** storage/UI; **REFACTOR** playout contract | `tracks.cue_in_ms`, `cue_out_ms`, `segue_ms`; analysis proposes cues and advanced form saves them. `admin_media.edit_track()` bounds each independently but does not enforce cue-out greater than cue-in. `playout_queue.push_decision()` does not transmit them and managed Liquidsoap does not consume them. They are not effective broadcast trims today. |
| Per-track fade-in/fade-out | **MISSING** | No per-track fade-in/out persistence or envelope UI/engine annotations. Existing deck/mic/manual transition fades are operational mixer commands, not per-song envelope settings; `segue_ms` is not an implemented fade-out. |
| Loudness normalization | **COMPLETE** for measured gain | `audio_analysis.py` measures integrated LUFS/true peak; `loudness.gain_for()` uses station target (default −16 LUFS), −1.5 dBTP ceiling, boost cap and neutral fallback for unanalyzed audio. `playout_queue.py` passes `freo_gain` annotation; engine applies `amplify(override="freo_gain",...)` on music/event buses and a final limiter. |
| Manual per-track gain trim | **MISSING** | Automatic calculated gain exists; no separate persisted user gain override. Do not confuse microphone gain or station processing with track trim. |
| Station processing | **COMPLETE** | `station_audio.py`, `stream_mounts` pending/active audio settings; validated 64/96/128 kbps, optional AGC/EQ/multiband, root renderer and target-station restart/rollback. `station_settings.py`, audio settings UI and tests. |
| Nondestructive audio and preview | **COMPLETE** for current edits | Metadata is in DB; approved originals retain storage keys/checksums. Analysis writes measurements, waveform/artwork and compatible preview derivatives. `media_preview.py` converts a separate preview; broadcast uses original. Shared gain policy is reused in preview. No destructive rewrite is needed for V1 cue/fade/gain. |
| Waveform editing workflow | **FOUNDATION** | Waveform data and preview controls exist (`audio_analysis.py`, Music preview scripts). A complete drag-handle cue/fade editor with verified broadcast parity is not present. |

For ordinary Track playback, `push_decision()` currently annotates only the Freo
decision ID and calculated gain. The legacy Imaging branch also annotates title
and artist. Freo's public player projects current database metadata, but ordinary
track title/artist edits are not explicitly sent as new Liquidsoap annotations
or rewritten into original file tags. Include Icecast/third-party player metadata
parity in a future editor contract rather than assuming the UI edit updates every
stream consumer.

Extend the current editor, not a new media library. Establish one validated
effective-duration/gain/cue contract for previews, AUTO, DJ decks, carts, timed
events, event sequences and leader/request playback. The socket command regex
allowlist in `playout_queue._command()` currently accepts decision/gain annotations
and controlled local paths; new annotations require deliberate allowlist changes,
injection tests and generated-engine audio tests. Do not pass arbitrary paths,
URLs or raw Liquidsoap expressions from editor input. Existing stored cue values
must not suddenly become audible trims during upgrade without reviewed opt-in
semantics and validation of potentially reversed/zero-length ranges.

Evidence: `tests/test_catalog_editor.py`, `test_catalog_editor_browser.py`,
`test_sound_room.py`, `test_audio_formats.py`, `test_station_audio.py`,
`test_loudness_playout.py` (real rendered output), `test_media.py`.

### 5. Listener requests — MISSING feature, reusable FOUNDATION

| Capability | Status | Evidence and reuse |
| --- | --- | --- |
| Request model/routes/UI | **MISSING** | No listener-song-request table, request lifecycle, pending queue, approval endpoint or request widget found. Existing public feedback is voting/comments on an already-started song, not requesting a future song. |
| Public interaction and moderation | **FOUNDATION** | `listener_votes`, `listener_feedback_events`; `GET/POST /api/stations/<slug>/feedback/<decision_id>` with listener cookie, CSRF/origin checks, revision/idempotence handling and per-listener/network limits. Admin feedback screen has review/exclusion. Reuse design patterns, not vote rows as requests. |
| Queueing and engine integration | **FOUNDATION** | `selection_decisions`, fixed queue operations, approved-track availability, checkpoint reconciliation and confirmed starts; DJ manual intents and scheduled events already demonstrate insertion. No connection from listener feedback to playout exists. |
| Request policy/rate limits | **MISSING** | No song-request cooldown, pending duplicate limit, request eligibility, station enablement, expiry, moderation approval or fairness policy. Feedback's limits are only for feedback. |
| Embeddable/public requests | **MISSING** | Public `/player/<slug>` and player APIs provide a frontend home, but no request embed/interface or tested cross-origin request credential policy. Reuse player components while defining a narrow public catalog and request contract. |

Add a distinct durable request lifecycle that references existing tracks and
selection decisions; insert through the automation worker, never directly from
a public route into the socket. Moderation approval must not imply “played”; only
existing actual-start confirmation does. Dependencies: authorization/public
visibility, common eligibility/separation, priority relative to events/leaders,
idempotence, expiry, abuse limits and station/customer scoping. Test deletion,
disabled/shared tracks, live takeover, duplicate submission, restart and public
catalog data exposure before enabling it.

### 6. Public API + webhooks — PARTIAL APIs; MISSING webhook product

There is a substantial unversioned HTTP surface. Preserve working client/player
contracts and expose supported API projections over existing services. Do not
assume `/admin/api` endpoints are a token-authenticated third-party API.

| Surface and representative exact routes | Current auth/behavior | Classification for roadmap |
| --- | --- | --- |
| `GET /api/stations`, `/api/stations/<slug>`, `/status` | Public station metadata/observed radio status; `routes/stations.py`. Status can do bounded live backend reads. | **COMPLETE** bounded reads; **PARTIAL** public contract |
| `GET /api/stations/<slug>/player` | Public now-playing/recent/next program, fresh/online flags; `routes/player_experience.py`, `services/player.py`. Uses confirmed decisions/observed mixer, not last queued selection. | **COMPLETE** |
| `GET /api/stations/<slug>/public-schedule` | Published sanitized schedule snapshots, date range bounded to 31 days, respects public schedule setting. | **COMPLETE** |
| `GET /api/stations/<slug>/schedule`, `/schedule/current`, `/clocks`, `/clocks/<clock_slug>` | Public programming reads; `routes/schedule.py`. Legacy clock target serializer only names category/rotation targets, while runtime supports more slot kinds. | **PARTIAL** contract/serialization |
| `GET /api/stations/<slug>/categories`, `/rotation`, `/automation/status`, `/history` | Public metadata/history; `routes/automation.py`. History is bounded to last 100 starts. | **COMPLETE** current bounded reads; **PARTIAL** extensibility |
| `GET /api/stations/<slug>/media`, `/media/<track_uuid>` | Public metadata only, no raw paths; `routes/media.py`. List limit 100, no general pagination; availability scope includes installation-shared songs and may include disabled/decommissioned status depending on query. | **REFACTOR** public visibility/eligibility before request API |
| `GET/POST /api/stations/<slug>/presence` | Public first-party session/CSRF presence heartbeat, not listening proof; `routes/statistics.py`. | **COMPLETE** bounded website-presence feature |
| `GET/POST /api/stations/<slug>/feedback/<decision_id>` | Listener session/CSRF with moderation and limits; votes/comments only. | **COMPLETE** feedback, **FOUNDATION** requests |
| `/admin/stats/data`, `/admin/stations/<slug>/stats/data`, export CSV | Session-authenticated listener/geo/transfer/history data. No dedicated scoped public listener-count/analytics API product. | **PARTIAL** listeners API |
| `/admin/api/operations`, `/broadcast-status`; station `/snapshot`, `/now`, `/live-status`, `/song-search`, `/cart-search` | Admin session; UI polling/projections in `web.py`, `admin_live.py`. | **COMPLETE** internal UI API |
| Station `/admin/api/.../catalog`, `/song/<identifier>`, `/music`, `/music/actions/<action>`, `/playlists`, `/flags/<identifier>` | Admin session; CSRF on mutations; `catalog_editor.py`, `sound_room.py`, `playlists.py`, `song_flags.py`. | **COMPLETE** current management UI, **FOUNDATION** external library API |
| `/admin/stations/<slug>/schedule-studio/api/<action>`, calendar/programming/events/blocks/traffic action routes | Session+CSRF/permission helpers; revision/worker semantics, not stable third-party write API. | **FOUNDATION** schedule write API |
| `POST /admin/api/stations/<slug>/live-mic/<action>` and `/admin/stations/<slug>/live/<action>` | Session+CSRF and current global-admin playout boundary. | **COMPLETE** current internal controls |
| `/admin/software`, `POST /admin/software/upgrades/<identifier>`, license upload | Installation-admin-only privileged intent; do not expose through generic station API. | **COMPLETE** existing boundary |
| `/admin/installation`, `/admin/installation/check-connection` | Local admin management of outbound central integration. | **COMPLETE** integration UI |
| `/health`, `/ready`, `/health/{icecast,playout,stream,automation}` | Health/readiness routes with different meanings, not customer analytics or authorization. | **COMPLETE** bounded probes |

The outbound `central_api/client.py` allowlists `/v1/enroll`, `/v1/register`,
`/v1/activate`, `/v1/stations/sync`, `/v1/heartbeat`, `/v1/license` and
`/v1/releases/latest` on the configured external HTTPS origin. Installation bearer
credentials and central retry/checkpoint machinery are **not** a local public API
token system. External server behavior is outside this repository audit.

- **MISSING:** local API keys/service accounts, scoped bearer authorization,
  versioned public contract/OpenAPI, consistent pagination/errors/rate limits,
  documented third-party write operations and tested embedding/CORS policy.
- **REFACTOR:** per-station/customer authorization and consistent public visibility.
  Existing public station/programming/catalog endpoints differ from player
  publication rules. Decide allowed public fields before exposing requests,
  private libraries or customer data. Preserve old URLs with compatibility tests.
- **FOUNDATION:** `AuditEvent`, confirmed `SelectionDecision` starts, timed-event
  outcomes, worker event logs and central reporting checkpoints supply event
  sources. They are not a webhook delivery system; audit writes alone are not a
  reliable public event contract.
- **MISSING:** webhook subscriptions, durable transactional outbox, delivery
  attempts/retry/backoff/dead-letter state, signed payloads, secret rotation,
  event IDs/idempotence, replay UI and destination validation. Add delivery away
  from the automation timing path. Outbound destinations need network/SSRF
  controls and tenant ownership, not arbitrary fetches from public requests.

Evidence: route modules above; `tests/test_app.py`, `test_player_experience.py`,
`test_statistics.py`, `test_central_api.py`, `test_distribution.py`,
`test_logout_sessions.py`. API modernization should wrap existing service logic,
not duplicate scheduling/catalog/playout logic in a second backend.

### 7. Relay streams — FOUNDATION engines; MISSING managed feature

| Capability | Status | Findings |
| --- | --- | --- |
| Managed external relay | **MISSING** | No relay source model, URL/credential configuration, schedule source, route, UI or worker policy. `StreamMount` describes Freo output/processing, not upstream relay selection. |
| Liquidsoap network input | **FOUNDATION** | Renderer already generates `input.http` for a fixed loopback microphone endpoint. No arbitrary upstream URL or relay reconnect/fallback/metadata behavior is exposed. Reuse validated rendering/control patterns, not the mic session contract itself. |
| Icecast relay configuration | **FOUNDATION** | `deploy/icecast/icecast.xml.template` has a generated relay password; `scripts/render-radio-config.py` manages credentials. No configured `<relay>` source or managed master/slave relay workflow. A relay password does not implement relaying. |
| Production relay operations | **MISSING** | Source authorization/secret storage, reconnect/backoff, silence vs disconnect policy, local AUTO fallback, recovery priority, codec/metadata validation, observability and endpoint restrictions. |

Distinguish **rebroadcasting an upstream stream as a station's input** from
**distributing Freo's output to another Icecast server**. The roadmap does not
choose between them; scope each separately before implementation. For upstream
station inputs, keep selection/fallback policy in Freo and sample-level network
audio handling in Liquidsoap. For downstream distribution, avoid making it part
of the music selector. Both require tested configuration-generation and upgrade
support, and bounded/authenticated endpoints; neither should accept arbitrary
URLs in the current approved-local-file socket interface.

### 8. Future voice tracking / AI station IDs — FOUNDATION

| Capability | Status | Evidence/reuse |
| --- | --- | --- |
| Audio capture transport | **FOUNDATION** | Browser Web Audio/WebRTC and mic gateway exist, but no MediaRecorder-based durable take editor or gateway recording output. |
| Ingest/analysis/storage | **COMPLETE** reusable subsystem | Existing staged upload, validated decode/checksum, opaque file keys, analysis/previews, background jobs and approved originals. Generated/recorded files can enter this trust boundary. |
| Station IDs/insertion | **COMPLETE** for uploaded audio | STATION subtypes, permanent collection, carts/ID slots, timed events, event blocks and visual show/block inserts already play station audio. `audio_classification.py`, `live_assist.py`, `timed_events.py`, `event_blocks.py`, `visual_schedule.py`. |
| Voice-track authoring | **MISSING** | No take/retake/edit workflow, microphone take persistence, gap placement linking preceding/following songs, timing/mix envelope editor or approval lifecycle. |
| TTS / AI generation | **MISSING** | No TTS client/provider adapter, generation job, voice/model configuration, cost limits, provenance or generated-audio review UI found. Existing FFmpeg analysis/preview generation is not speech generation. |

Future work should stage recorded/generated audio, validate and approve it through
the existing ingest boundary, classify it as station audio, and schedule it through
existing inserts/carts/events or the future leader mechanism. Keep provider calls,
recording/transcoding and retries off the broadcast worker. Recording consent,
voice-use rights, retention and provenance become requirements of that future
feature; no provider or AI dependency is needed to prepare the present codebase.

## 3. What we should preserve

1. **Stable Track/catalog identities and original audio.** Keep existing UUIDs,
   checksums, paths, history foreign keys and station ownership. Extend metadata,
   do not reimport music or regenerate originals to introduce editing/features.
2. **One automation/control authority.** Keep selection decisions, observed-start
   accounting, cursor checkpoints, queued-intent reconciliation and narrow socket
   commands. Do not create a second independent scheduler or let public requests
   write directly to Liquidsoap.
3. **Current programming and audio behavior by default.** Preserve Straight order,
   continuous Random cycles, recurrence/DST behavior, finish-current-song/event
   semantics, durable Cue and mode-switch acknowledgments. New rules should not
   silently reschedule an existing station after upgrade.
4. **Separation of web, ingest, automation, playout and root helpers.** Preserve
   filesystem privileges, private sockets/backends, CSRF and session revocation.
   Extend authorization inside this structure rather than granting browser code
   wider host access.
5. **Existing listener analytics and player UI.** Keep aggregate history,
   freshness/unknown semantics, privacy-minimized geography, public schedule
   snapshots, feedback moderation and CSV. Do not rebuild analytics from zero.
6. **Signed release and recovery pipeline.** Retain exact artifacts/wheels,
   immutable version identity, full preservation verification, maintenance
   guards, journals and isolated restores. No live schema reset or fresh-install
   shortcut for upgrades.
7. **Current UI interactions and tests.** Extend Music/Playlists/Scheduling/Live/
   Statistics; preserve workspace navigation, polling cleanup, autosave revisions,
   undo and live microphone departure. Reuse the real-engine/browser/PostgreSQL
   test harnesses and retain old compatibility fixtures.

## 4. What needs extending

| Existing subsystem | Focused extension |
| --- | --- |
| Updater/release manifest | Tested source-version/schema/engine compatibility, validated template/service migration, new-root inventory, richer health evidence and explicit recovery playbook for each release. |
| Admin auth and availability | Customer/station membership and DJ permissions; customer-bounded sharing and aggregate statistics; preserve installation-admin operations. |
| Playlist/visual selection | Shared opt-in eligibility/separation/weight policy, dynamic rules, explicit leader occurrence state without erasing existing cursor semantics. |
| Track editor/playout annotations | Validated nondestructive cue/fade/trim/effective-duration contract and preview/rendered-audio parity. |
| Analytics collector/dashboard | Device aggregates and clearly named sampled-session metrics; access-log ingestion only for separately defined accuracy needs. |
| Existing HTTP services | Stable versioned public projections, token scopes and consistent visibility/pagination/errors while preserving existing public-player contracts. |
| Worker confirmed events | Reliable, transactionally coupled event publication for request fulfillment and later webhook delivery. |
| Media job pipeline and inserts | Future recording/generated-asset approval and reuse through STATION audio, carts/events/leaders. |

## 5. What is genuinely missing

- Playlist leader configuration and restart-safe leader-first occurrence handling.
- General dynamic smart-playlist rules/weights; common separation across modern
  visual sources and ordinary playlists; general playlist-priority policy.
- Per-track effective broadcast cue/fade controls and manual gain trim (cue fields
  exist but are not consumed).
- Restricted DJ/customer roles and tenant-bounded sharing; service-account API tokens.
- Listener song requests with durable moderation/queue lifecycle and public embed.
- Public webhook subscription/delivery/outbox machinery.
- External encoder ingest, managed upstream/downstream relays and their operational UI.
- Durable show recording, voice-track authoring and TTS/AI generation.
- Exact listener session ledger/access-log ingestion and device-class dashboards.

These are missing capabilities, not a requirement to ship all of them in 1.0.

## 6. Technical debt and blockers

| Priority | Finding | Consequence and recommended action |
| --- | --- | --- |
| **Release gate** | Updater rejects changed files under candidate `deploy/liquidsoap`, `icecast`, `nginx` (`upgrade.py` preflight). | Cue/fade, encoder/relay or proxy changes cannot use today's generic updater unchanged. Add a narrow, rehearsed config migration/validation/rollback path first; never just remove the guard. |
| **Release gate** | Updater rewrites only managed unit files already present; new services/accounts/directories/credentials are not generally provisioned on upgrade. | Fresh installer success does not prove upgrade success. Add explicit idempotent provisioning steps, service-user privileges, failure cleanup and restore tests for any new component. |
| **Release gate** | `releases.py` hardcodes supported source revisions through `c83d4e5f9012`. | V1.x must list/test actual supported prior heads, including its own head for repeat application. Document direct versus bridge upgrade paths; do not infer compatibility from a higher version alone. |
| **Release gate** | `verify_preservation()` requires every old row's old columns and monotonic sequences to survive; only narrow historical primary-admin transformation is special-cased. | Renames/drops/rewrites and imaging identity conversion can fail after migration. Prefer additive transitions; for deliberate transforms use explicit reviewed expected mappings and fixtures, not broad exclusions. |
| **Release gate** | Full backup/restore stages several dataset copies; updater free-space check only budgets roughly 3× extracted release size. | Large media libraries can exhaust backup/temp/restore volumes despite passing preflight. Add per-volume capacity/time estimates and representative library rehearsals. No low-downtime guarantee. |
| **Release gate** | Source-code/schema pair validation is not comprehensive across all upgrade cases. | Current explicit mismatch refusal focuses on same-version/different-schema; supported DB revision alone is insufficient. Verify installed manifest, actual code hashes/head and live revision as a matched source before any V1 mutation. |
| **Security gate for hosting/DJ/API** | Global-admin permission helpers, installation-global sharing and scope-zero statistics. | Do not label existing station IDs as tenant isolation. Introduce membership/scoped queries and adversarial cross-customer tests before reseller or restricted credentials. |
| **Correctness gate for smart playlists** | Category selector, ordinary playlist cursor, visual selector and timed-event snapshots have different selection semantics. | Extend a common policy layer selectively, preserve occurrence/cursor adapters and test all entry paths. Do not replace the schedule resolver. |
| **Correctness gate for editing** | Cue values are stored but ineffective; individual bounds do not validate a playable range. | Audit existing values; enable new behavior deliberately. Update effective duration, safety validators, previews, timing assumptions, engine annotations and tests together. |
| **Compatibility debt** | Modern classified Track audio coexists with legacy Imaging/history refs. | Inventory actual legacy rows before migration. Keep compatibility until a separately tested conversion can preserve references and files; do not mass-convert as an incidental V1 cleanup. |
| **API debt** | Unversioned routes, inconsistent publication visibility and legacy clock serialization. | Define supported read/write projections, visibility and pagination. Preserve current player URLs; test that private/unpublished customer content is not exposed. |
| **Operational debt** | `/etc/freo/release` was recorded stale; old docs use legacy paths/version examples. | Use installed manifest + app version + exact schema as authority. Update V1 diagnostics/docs deliberately without rewriting frozen artifacts. |
| **Maintainability** | `app/models/__init__.py` is 1,242 lines; `automation_worker.py` 1,127; dense service code and several scheduling representations. | Extract only targeted policy/validation boundaries under characterization tests. A broad framework/model/worker rewrite would increase upgrade and audio risk without unlocking the roadmap. |
| **Validation debt** | Historical acceptance is strong but not a V1 run; audio sensitivity under host load documented. | Run exact-artifact PostgreSQL/browser/audio/soak/reboot/recovery gates on isolated hosts; avoid concurrent heavy backup/build load during audio acceptance. Bound scale claims to measured station/library/listener sizes. |

Documentation conflicts to resolve in future documentation work: early
`docs/architecture.md` calls implemented workers “future”; `docs/playlists.md`
describes two starters and per-occurrence shuffle reset, while current code has
four default collections and persistent Random progress; old Imaging docs describe
a UI now redirected; `docs/recovery-and-upgrades.md` contains old version examples
and pending acceptance language superseded by 0.3.2 records. Code, current tests
and exact release acceptance take precedence over historical plans. No existing
documentation besides this audit was changed.

## 7. Recommended V1 implementation order and dependencies

1. **Upgrade/readiness contract first.** Create an isolated 0.3.2 fixture from the
   frozen signed archive; inventory representative data/config; define source
   compatibility and recovery gates. Extend only updater capabilities required
   by selected 1.0 changes. Preserve immutable migrations and old artifacts.
2. **Authorization/scoping foundation before new audiences.** If V1 includes
   restricted DJs/resellers/API credentials, add customer/station membership,
   scoped availability/statistics and token boundaries before exposing features.
   If hosting is deferred, keep the installation single-owner explicitly.
3. **Characterize selection and playback contracts.** Lock down legacy/visual/
   playlist/event behavior, confirmed starts, priority and occurrence state.
   Establish shared opt-in selection policy and effective-audio metadata contract.
4. **Ship focused scheduling/editor improvements.** Leader-first playback,
   optional separation/weights/smart rules, and nondestructive cue/fade/gain only
   after their upgrade/engine-contract gates pass. Extend current screens.
5. **Stabilize external API and listener requests.** Build versioned read
   projections and scoped credentials; request moderation/expiry/fairness uses
   established eligibility and worker queueing. Durable confirmed request outcome
   precedes webhook notifications about fulfillment.
6. **Extend analytics incrementally.** Device classes/sampled sessions can be
   developed independently after scoping and privacy semantics; exact-log
   ingestion is a separate effort, not a dependency of basic V1 scheduling.
7. **Add external live/recording and relays.** These depend on config/service
   upgrade support, authorization, safe network inputs and fallback priority.
   Recordings also depend on storage quotas, retention, backup and approved-media
   ingest. Do not couple every live feature into one engine rewrite.
8. **Voice tracking/AI later.** Build recording/take editing and approved insertion
   first; provider generation can then supply assets through the same workflow.

| Feature | Hard dependencies |
| --- | --- |
| Playlist leader | Approved Track/STATION asset, shared occurrence identity, cursor reconciliation, confirmed start, fallback policy; editor/delete/signature integration |
| Smart selection | Availability/scoping, selection history, shared opt-in rules, cursor semantics, rule explainability and exhaustion tests |
| Audible cue/fade/trim | Validated metadata/effective duration, allowlisted protocol, preview/engine parity, template-upgrade support |
| Listener requests | Public eligibility, abuse/moderation lifecycle, station permissions, existing selector/event precedence and restart-safe insertion |
| Webhooks | Stable API event semantics, tenant ownership, transactional event capture, independent retry worker and safe egress |
| Restricted DJs/resellers | Membership and station/customer query boundaries across all routes/workers/shared media/statistics, not just login UI |
| External live / relays | Engine/runtime capability version, input credentials/network policy, fallback/priority, upgrade and audio acceptance |
| Recordings / voice tracks / AI IDs | Storage lifecycle/inventory, job and review flow, approved ingest and existing station-audio insertion |

## 8. Proposed release breakdown

This is a proposed sequencing recommendation, not committed scope or release
dates. Each release must pass the upgrade gates below; defer features rather than
advertise unsupported behavior.

| Release | Recommended content | Required exit evidence |
| --- | --- | --- |
| **1.0** | Stable foundation plus playlist leaders and opt-in scheduling improvements; focused nondestructive editor completion if engine/template upgrade gate passes. Preserve current analytics/player/booth. Establish authorization/scoping needed for any included restricted DJ/customer access. Do not claim a finished reseller platform. | Exact signed 0.3.2 → 1.0 upgrade, matched restore, unchanged defaults/history/media, real leader/order/cue audio, migration and boundary tests, fresh install/reboot. If editor engine changes fail the gate, defer them explicitly. |
| **1.1** | Versioned public read API/scoped credentials, listener requests and moderation, common priority/eligibility, incremental device/sampled-session analytics. Complete deferred editor capabilities before request/leader audio relies on them. | Cross-station/customer auth, abusive/duplicate requests, restart-safe fulfillment, API compatibility, privacy/retention and 1.0 → 1.1 upgrade. |
| **1.2** | Webhooks, restricted/external DJ ingest as separately scoped, durable show recording. Relays may enter only with their own input/output scope and fault tests. | Durable retry/idempotence, safe egress, network drop/quiet-source fallback, recording disk-full/retention/restore, 1.1 → 1.2 upgrade with new services/roots. |
| **1.3** | Managed relay expansion and recording/take-based voice tracking; optional TTS/AI station-ID generation into the established media pipeline. | Asset provenance/review, restart/disk/quota failure tests, correct insertion/preview, supported prior-release upgrades. |
| **1.x patches** | Separate fixes/backports, no surprise destructive schema or behavioral changes. | Exact artifact validation and relevant regression/upgrade/reapply checks. Main remains the current stable production line until a separately approved V1 promotion. |

Do not make listener requests wait for AI, or replace the existing analytics
dashboard as a prerequisite for device metrics. Conversely, do not publish tenant
credentials before isolation or alter engine templates before upgrade support.

## 9. Upgrade strategy: 0.3.2 → V1 and future V1.x

### Required supported-source contract

Use the frozen 0.3.2 archive/source and `c83d4e5f9012` as the initial supported
pair. The actual production installation has a versioned runtime already; do not
repeat legacy adoption or fresh install. Record installed manifest/commit/schema,
settings revision, configured roots, service/engine versions and customization
inventory immediately before a future upgrade. Record the exact Liquidsoap,
Icecast, FFmpeg, PostgreSQL and OS package versions used in release qualification;
the Python wheelhouse alone does not reproduce host audio/system packages.

Use candidate updater code only after independent publisher-signature verification
and installation of its bundled dependencies into isolated tools storage. The
0.3.2 root web runner executes its own updater implementation; preparing a plan
with new tools does not automatically teach that old runner new migration or
template rules. For the first V1 transition, use the verified V1 tools in a
reviewed operator maintenance procedure, or ship/test an explicit bridge before
offering browser-driven upgrade. Do not overwrite active code to obtain tooling.

Before calling the path “supported,” implement and validate:

1. **Matched source and target checks.** Verify original artifact and actual
   installed file identity, live Alembic revision, platform/dependencies and
   stable env consistency; refuse unsupported/custom layouts with useful
   diagnostics. Reapply of identical code/schema must be a no-op; same version
   with different contents remains forbidden.
2. **Additive schema and preserved behavior.** Append revisions after
   `c83d4e5f9012`; keep one head. Prefer new nullable columns/tables and defaults
   that reproduce 0.3.2. Preserve station/track IDs, storage keys/checksums,
   accounts/sessions/license, central identity, schedules/cursors, playlists,
   settings, comments/analytics/history and uploads. For intentional data
   transformations, update expected-preservation logic with explicit mappings
   and migration fixtures before running the migration. No generic checker bypass.
3. **Runtime/protocol capability transition.** For changed engine/proxy templates,
   validate generated configs offline, preserve previous configs/credentials,
   define engine capability/command compatibility and affected-station restart
   order, then validate output. Install new service users/units/roots/credentials
   explicitly. Preserve stopped-station intent and customizations or refuse
   clearly. The current unit-rewrite loop is insufficient for adding services.
4. **Complete backup inventory and capacity.** Include every newly persistent
   recording/generated asset/state directory and ACL; budget code/venv, encrypted
   backup, temporary copies, isolated restored files and database on their actual
   volumes. Establish measured maintenance duration for representative media
   libraries and keep the passphrase separately recoverable/off-host backup.
5. **Exact release packaging.** Set V1 version and matching immutable source tag,
   build/sign once with locked wheels, include operator docs and support matrix,
   test the exact archive and publish unchanged bytes. Update
   `supported_source_revisions` for tested sources and target schema. Maintain
   previous trusted keys and define a reviewed key-rotation path if ever needed.

### Rehearsal and acceptance matrix

| Scenario | Required assertion |
| --- | --- |
| Representative 0.3.2 fixture | Multiple running/stopped stations; Music/STATION/COMMERCIALS and retained legacy imaging; playlists/Random progress, all scheduling modes, events/traffic, sharing, imports, admin sessions/license/central identity, analytics and custom roots survive. Use synthetic or explicitly authorized sanitized data. |
| Schema/data preservation | Upgrade to exact V1 head; compare old-row values/expected transforms, sequences and identities. Validate backfills, constraints, settings revision/import idempotence, original hashes and filesystem ACLs. |
| Backup and recovery | Encrypted bundle verifies and actually restores into a separate DB/filesystem; matching old release works against that restored state. Verify Unicode, custom roots, ownership and unresolved links. No live dump overwrite. |
| Preflight/early failure | Bad signature, unsupported source/platform, dirty/tampered installed payload, disk shortage, custom units and invalid rendered config fail before live mutation wherever feasible. Dependency failure must not stop broadcasting. |
| Mid-upgrade failure | Stop/backup/restore/migration/preservation/pointer/start/readiness/audio failures plus process kill/reboot leave honest journal and maintenance state; no automatic replay of unfinished root plans. |
| Playback regression | Existing AUTO/DJ/Cue/events, muted/quiet live microphone, abrupt mic loss, intentional exit, random continuity, leader exactly-once ordering, cues/fades/effective durations, future-queue refresh and worker/engine restarts validated with actual audio. |
| UI/API/security | Existing public player and schedule clients still work; navigation/autosave/login/CSRF/revocation and first setup work; new customer/DJ/token scopes cannot access other customers or installation controls. |
| Fresh installation and reboot | Exact V1 kit installs without upgrading an existing installation; after reboot desired broadcasts/workers/timers resume automatically. Test HTTP and configured HTTPS, plus separate remote mic/TURN and certificate renewal acceptance where claimed. |
| Scale/soak | Measured station/library/listener scale, backup downtime and storage growth; real audio under realistic worker/ingest/stats load, with test-only isolation from production. |
| Repeat/next release | Reapplying same V1 artifact is a no-op; V1 → next V1.x works from every advertised source; unsupported skipped-version paths fail with a required bridge version. |

Existing harnesses to extend: `tests/test_upgrade.py`, `test_recovery.py`,
`test_release_bundles.py`, `test_installation_settings_postgres.py`,
`scripts/test-recovery-postgres.sh`, `scripts/test-install-postgres.py`,
`scripts/test-candidate.py`, `tests/system_harness.py`, the scheduling/browser/
audio suites cited above, and `.github/workflows/{recovery,python-install,
candidate-acceptance,release}.yml`. Recovery CI already runs on pushes; candidate
acceptance branch filters cover RC-named branches, not all `develop/v1` pushes.
Before feature development relies on it, deliberately extend the V1 CI trigger
policy or require explicit workflow dispatch/PR gates; do not assume the entire
audio acceptance suite runs automatically on every development push.

### Production execution and rollback boundaries

A future production upgrade remains a separately approved maintenance operation.
Announce interruption, exclude other writers, stop active Freo units/timers with
the established guards, create and restore-verify a current matched backup, run
candidate migrations/preservation checks, activate validated runtime/configs,
then verify service/schema/audio/UI and record completion. The existing October 1
backup is historical, not a current user-data recovery point.

Before migration, resume old units on failure when safe. After migration or new
writes, retain failed DB, release, journals and files; restore the matched backup
into new locations and deliberately attach the matching old release only after
validation and any write reconciliation. A symlink rollback alone, `git reset`,
or `flask db downgrade` is not a complete rollback. Measure/document restore time
and the recovery point; no zero-data-loss-after-new-writes promise.

For future V1.x releases, maintain a tested version/schema/runtime compatibility
matrix, additive transitions where practical, explicit data-transform verifiers,
and required bridge releases when needed. Retain previous signed kits and recovery
material until retention and restore tests permit cleanup. Every release repeats
the applicable exact-artifact upgrade/recovery gates; passing 0.3.2 → 1.0 does
not automatically certify 1.0 → 1.1.

## Audit conclusion

Freo already contains the core of V1: durable scheduling/playlists, a substantial
DJ/live engine, classified media and nondestructive analysis, listener analytics,
public-player APIs, and signed upgrade/recovery tooling. The highest-value work
is targeted extension of these systems. The first release blockers are upgrade
compatibility for engine/service changes, real authorization before new customer
or DJ access, consistent selection policy across existing paths, and making
stored audio-edit values match actual playback. No V1 feature implementation is
included in this audit.
