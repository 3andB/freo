Scheduling and Events review and implementation plan — 18 September 2026

Implementation and final verification: [activation guide](events-station-commercials-release.md). The review and baseline below describe the pre-implementation state.

This is a repository review and proposed implementation plan. Application code, database records, media files, and running station configuration have not been changed. The intended result is four starter playlists—Playlist 1, Playlist 2, STATION, and COMMERCIALS—and Events that play the selected audio after the current song ends, using the station timezone from Settings.

The proposal interprets “STATION prompts, station_id” as station promos, announcements, IDs, jingles, sweepers, and similar audio, identified by a STATION classification and searchable subtype labels such as `station_id`. This subtype must remain distinct from the database `station_id` ownership field. Playlist playback defaults and treatment of live microphones are proposed below; clarification questions were sent during the review.

The existing implementation has useful foundations, but this requires coordinated changes to the media model, event recurrence, worker, and audio engine. Adding playlist names and recurrence controls alone will not deliver the requested behavior.

| Requirement | Current implementation | Work required |
| --- | --- | --- |
| Remove Imaging | Separate assets, storage, ingest, groups, cart references, clock slots, traffic references, and event targets | Migrate audio and references before retiring the feature |
| Third and fourth defaults | Only Playlist 1 and Playlist 2 are seeded | Add stable STATION and COMMERCIALS identities and backfill existing stations |
| Identify station audio and commercials | Imaging has STATION_ID, PROMO, COMMERCIAL, and other classifications; ordinary audio has no equivalent content classification | Unified classification, upload/edit controls, bulk assignment, and search |
| Schedule playlists with Events | Targets are Track, ImagingAsset, or EventBlock | Add playlist target and finite playlist execution |
| One-time | Supported | Preserve and improve validation and editing |
| Every 15 minutes | Unsupported | Local wall-clock interval recurrence |
| Hourly | Supported through weekly days plus selected hours | First-class hourly choice, clearer summaries, consistent preview |
| Daily | Possible by selecting all weekly days | First-class daily choice |
| Weekly | Supported, including multiple weekdays | Preserve and integrate into the common recurrence model |
| Monthly | Unsupported in Events; calendar programming has monthly helpers | Add day-of-month and ordinal-weekday rules |
| After current song | SOFT mode inserts ahead of automatic lookahead | Close deadline, queue ownership, cancellation, and DJ gaps |
| INTERRUPT DJ: YES/NO, default NO | No event-level option; active DJ mode bypasses execution | Add policy plus controlled boundary handoff and return |
| Settings local time everywhere | Station-local form conversion and most browser formatting exist | Invalidate future occurrences on timezone change; unify displays, previews, and exports |
| Full audio search, playlists first | Paginated source search exists; Events only exposes song/imaging/sequence | Playlist-first browser with classification filters, metadata, and previews |

Review findings are grounded in these code paths:

- `app/models/__init__.py:685`, `app/services/timed_events.py:19`, and `app/templates/admin/event_fields.html:4` restrict Events to ONE_TIME and WEEKLY. Hourly uses `repeat_hours`; it is not a separate recurrence. The Events list omits selected hours from its weekly summary.
- `app/models/__init__.py:892` and `app/services/playlists.py:13` define ordinary track playlists and seed two names. STRAIGHT/RANDOM are playback modes, not content types. Event playlist cursors cannot directly reuse `PlaylistCursor`, which is tied to clock slots.
- `app/services/timed_events.py:33` accepts no playlist target. Its content validation and preparation also distinguish tracks from Imaging assets.
- `app/automation_worker.py:489` already supports SOFT insertion, collision priority, durable occurrences, and confirmed starts. It also declines an event when the estimated current-track end exceeds its deadline. The browser default is 300 seconds; service and CLI defaults are 10 seconds. A long song can therefore cause a missed event instead of the requested next-boundary playback.
- `app/automation_worker.py:650` onward bypasses normal event execution during active microphone use and during DJ_BOOTH without standby. DJ control also aborts active event blocks. A new checkbox will need worker and engine behavior, not just a saved boolean.
- `app/services/playout_queue.py:158` chooses the special insert operation for SOFT event items. `deploy/liquidsoap/station.liq.template:25` preserves future requests when inserting. Retain this behavior and prove multi-item events cannot allow ordinary music between items.
- `app/services/timed_events.py:100` cancels PENDING/READY occurrences on edit, but preserves their prepared selection decisions. `generate_occurrences` can reactivate the same cancelled occurrence at the same instant. A content edit after preparation risks using the old audio. Add a regression and invalidate stale preparation.
- `set_enabled` cancels PENDING/READY occurrences only. A queued event can remain in the engine after disabling or editing. Define and implement removal of that event's future requests without cutting current audio or flushing unrelated music.
- `app/services/stations.py:89` changes the station timezone without cancelling/regenerating materialized event occurrences. Existing future UTC occurrences can coexist with newly generated times. One-time definitions currently retain only their converted UTC instant, so their intended original wall time is not independently stored.
- `conflict_warnings` compares a limited set of same-type rules and does not expand selected hourly times or duration overlap. Mixed recurrence collisions need occurrence-based checking.
- `generate_occurrences` scans an eight-day horizon, including a one-day lookback, and commits occurrences individually on repeated worker calls. A 15-minute rule produces 768 occurrences per eight normal days. More frequent recurrence needs batched generation, indexed due queries, and incremental replenishment; the worker's 20-row upcoming limit must not become a correctness limit.
- The worker does not distinguish SKIP and PLAY_LATE in its execution branches, despite exposing both settings. Replace ambiguous controls with explicit, tested waiting and expiry behavior.
- `app/services/event_blocks.py` has reusable execution snapshots and failure policies. Final-item completion in `process_block` uses duration and active-request disappearance; skipped trailing items and restart paths need explicit coverage before using this for playlist runs.
- `app/services/visual_schedule.py:88` already supplies station-scoped search and pagination, including playlist search. Events does not expose that playlist source. Current results lack the requested priority grouping and full classification filters.
- Imaging dependencies include `CommercialCreative`, traffic stopsets/placements, event block definitions and executions, clock slots, selection history, LiveCartSlot, ingest jobs, preview routes, CLI commands, and storage validation. `app/services/traffic.py:47` explicitly requires COMMERCIAL Imaging today.
- `app/services/media.py:173` treats all enabled, accepted tracks as fallback candidates. Migrating IDs and ads into Track without changing selectors could broadcast them as ordinary music. Track availability can also inherit sharing from artists/albums, so migrated station assets need deliberate ownership and sharing rules.

Implement the work in this order:

1. Establish the shared audio and playlist contract.

   Add explicit audio classification `MUSIC`, `STATION`, or `COMMERCIALS` to the existing Track-backed audio catalog. Existing music defaults to MUSIC. Add a station-audio subtype/tag for `station_id`, `promo`, `announcement`, `jingle`, `sweeper`, `liner`, and generic station material; preserve cart codes and useful existing metadata. Classification must be structured data rather than a filename convention. Users can set it during upload, on the audio editor, and through a bulk action.

   Add playlist purpose `GENERAL`, `STATION`, or `COMMERCIALS`, separate from STRAIGHT/RANDOM mode. Create the STATION and COMMERCIALS starter playlists for existing and new stations. Identify system starters with stable keys and a per-station uniqueness rule, rather than detecting their display names. Existing user playlists with matching names must not be silently overwritten or adopted. Preserve their contents and resolve display-name collisions explicitly during migration.

   Proposed behavior: STATION and COMMERCIALS are persistent system collections containing all audio classified that way for their station. Classification changes update membership atomically; users can order the collections and create ordinary subsets for particular campaigns or announcements. Removing an item from a system collection must explicitly reclassify it rather than silently making “all station audio” incomplete. Existing Playlist 1/2 remain ordinary editable playlists. Display the four starters in the requested order, then other playlists.

   Keep ownership (`station_id`) independent from the `station_id` audio subtype. Station material and commercials are private to their station by default and must not become shared through generic artist/album inheritance. Preserve existing music-sharing behavior. Keep STATION and COMMERCIALS out of automatic music/category/fallback selection unless explicitly selected for that purpose. Their confirmed playback must not pollute music/artist separation history.

2. Migrate Imaging completely, with a recoverable transition.

   Provide an inventory/dry-run report covering assets, files, groups, active/queued requests, clock references, blocks, events, traffic, carts, pending jobs, and historical references. Record missing files, rejected/disabled assets, checksum collisions with existing tracks, and names/cart codes that need resolution. Back up database and media together before applying migration.

   Map COMMERCIAL assets to COMMERCIALS; map remaining Imaging types to STATION with their original subtype retained. Preserve enabled, rejected, and decommissioned status; migration must not activate previously unavailable audio. Build a durable old-asset-to-new-audio identity map. Resolve same-checksum music/Imaging collisions without accidentally reclassifying an existing song or losing its references; use an explicit reviewed mapping for ambiguous cases.

   Copy approved files into the unified private storage layout using a resumable worker/administrative migration, with checksum verification, correct ownership, and atomic completion. Keep database schema changes separate from large filesystem work. Preserve original files until all references and playback have been verified. Generate new required catalog identities without losing the old UUID mapping, labels, cart codes, or audit links.

   Convert event targets, block items and snapshots, traffic creatives and fixed stopset items, Live Assist carts, clocks, selection history, and ingest-job references. Preserve Imaging groups as equivalent named collections with any existing repeat-separation rules; do not silently replace group rotation with different behavior. Maintain the current traffic scheduling, finalized-log protections, and confirmed-airplay reconciliation. A COMMERCIALS playlist is an audio collection, not a replacement for advertiser/campaign records.

   Stop new Imaging writes at cutover; drain or explicitly map in-flight jobs and queue identities. Remove Imaging navigation, forms, route registration, CLI entry points, ingest paths, and active runtime branches once all consumers use unified audio. Redirect useful old URLs through the identity map. Remove obsolete runtime schema only after validating historical references and migration counts; preserve old migration scripts for existing installation upgrade paths. Update installation, backup, recovery, and user documentation.

3. Give Events one recurrence model and one station-local clock.

   Reuse or extract the calendar's date-matching primitives where appropriate, with a single pure occurrence expansion function used by the worker, next-occurrence preview, calendar, conflict checks, and CLI. Keep Events distinct from duration-based calendar programming.

   | Choice | User controls and proposed behavior |
   | --- | --- |
   | One-time | Local date and time |
   | Every 15 minutes | Local start time anchors the quarter-hour pattern; 00:00 gives :00/:15/:30/:45; optional selected days/hours and end date |
   | Hourly | Minute/second each selected local hour, optional selected weekdays and date range |
   | Daily | One local time each day, optional end date |
   | Weekly | One or more weekdays and local time, optional end date |
   | Monthly | Date 1–31, last day, or ordinal weekday such as first Monday/last Friday, plus local time; dates absent from a month are skipped, as shown in preview |

   Store local recurrence intent, a revision, and the effective station timezone revision; retain UTC for execution and immutable history. Generate from the recurrence anchor, never from the previous actual start: an event played late must not shift the next quarter-hour or hourly target. Validate local inputs strictly, date ranges, required days/hours, and empty recurrence rules. Migrate existing weekly/hourly definitions without changing their intended times.

   Every browser label, date field, calendar, next-run preview, countdown target, history display, CLI display, and commercial export should use Settings → station timezone. Include the zone/UTC offset where repeated local hours would be ambiguous; machine timestamps may remain UTC. A browser or server in another timezone must not change the schedule.

   Retain the existing daylight-saving policy as the proposed default: shift nonexistent local times forward by the gap; execute an ambiguous local time once using the first occurrence. Deduplicate shifted interval occurrences that land on the same UTC instant. Show affected upcoming times in preview. Test full-hour and half-hour DST transitions as well as fractional-offset timezones.

   Proposed timezone-change behavior: preserve the configured local wall time for future events, including one-time events, and recalculate their UTC instants. Rebuild only unstarted occurrences; never rewrite historical starts. Serialize timezone changes with queue submission and remove superseded queued requests safely. Already playing audio finishes. Backfill the local intent of existing one-time events using the station timezone at migration and surface the limitation that the original historical input timezone is not stored.

4. Make playlist events finite and durable.

   Add PLAYLIST as a valid event target. Offer “one next item” and “play entire playlist once.” Proposed defaults: one rotating item for STATION, the complete ordered playlist for COMMERCIALS. Show the choice, item count, and estimated duration before saving. These are proposed defaults pending user preference.

   For one-item events, maintain a durable per-event playlist cursor independent of music clocks. STRAIGHT advances in saved order; RANDOM uses a persisted shuffle cycle. Reserve the selection idempotently and advance on confirmed play according to a documented failure policy, avoiding duplicate selection after restart. For full-playlist events, snapshot playable item identities, order, labels, playlist revision, and failure policy into an execution; STRAIGHT plays the saved order, RANDOM snapshots one shuffle. Never loop a playlist inside one occurrence.

   Reuse the existing block execution mechanism after making playlist-origin executions explicit. Freeze each run at preparation; playlist changes apply to later runs. Revalidate availability before queue submission. Empty/unplayable collections produce a clear validation or execution error while ordinary programming continues. Do not delete referenced playlists without resolving their event references. Preserve in-flight snapshots and history when a playlist changes.

5. Enforce “after the current song” and explicit DJ behavior.

   New events use the SOFT insertion path with no early playback and no hard skip. At the target, reserve the first available song boundary, put the event before ordinary future music, play its finite sequence contiguously, then continue normal programming. Preserve queued music order and rotation positions. If a calendar program changes while the event runs, resolve the current program on return and reconcile only automatic future audio belonging to the old program.

   Replace the fixed five-minute default as the sole eligibility test. An event due during a legitimate current song must remain eligible until that song ends, even if more than five minutes remain. Separate this waiting state from queue/engine failure, DJ protection, and stale catch-up policy. Do not estimate a boundary solely from duration plus start time, because decks can pause and rendered audio can differ. Use authoritative engine boundary information and observed request identity.

   Add `interrupt_dj`, default false, labelled “INTERRUPT DJ — Yes / No.” It controls permission to take over between DJ songs; it does not mean cutting the current song. With NO, protect the DJ and use an explicit bounded wait/skip policy with a visible reason. With YES, wait for the current audible DJ song boundary, reserve the event over AUTO_CUE/deck-repeat advancement, play the event, and restore DJ mode and appropriate deck/cue state afterward. Handle both A/B decks, crossfades, carts, standby, operator changes during the event, and failure to resume without replaying the finished song.

   Proposed microphone policy: a live microphone remains protected even with YES. Display that distinction in the form; an optional immediate live-source interruption would be a different behavior requiring an explicit contract. This preference was asked during review.

   Add a worker-mediated, idempotent engine handoff with an occurrence token and observable state. Never let the web process issue socket commands. Existing deck END callbacks provide useful groundwork, but event insertion and reliable return need their own integration and recorded-audio tests. Extend authoritative end reporting to event/program audio if needed; do not claim completion from a UI timer.

   Preserve existing HARD definitions as explicitly marked legacy behavior until migrated intentionally; the new form should not quietly create song-cutting events. Review legacy HARD policies separately, including protecting an active event sequence. On completion or failure, release the event's queue ownership and restore the applicable automation hold/DJ state.

6. Harden event lifecycle, collisions, and scale.

   Define observable scheduled, waiting-for-song, waiting-for-DJ, queued, playing, completed, missed, cancelled, and failed states, with reason codes and confirmed timestamps. Preserve actual-start evidence when a delayed engine confirmation arrives. Ensure the event owns the queue for its entire execution, including the final item and skipped trailing items.

   Serialize definition edits, enable/disable, occurrence creation, and queue handoff under the existing station/worker locking boundary. Add event revisions and stale-edit rejection. Reusing an occurrence after edit must clear obsolete decisions and execution preparation. Cancelling/disabling removes only the event's pending engine requests; current audio may finish. Define the same behavior for cancelling a single future occurrence, with a durable exception so generation does not recreate it. Definition changes otherwise apply to future occurrences while preserving history.

   Keep unique event/occurrence identity and durable submission recovery. Exercise crashes before submission, after engine acceptance, before database acknowledgement, and after confirmed start; reuse the matching request rather than submitting twice. Never silently replay completed occurrences after a restart or time change.

   Order collisions by scheduled instant, then descending priority, then stable ID. Finish an active event before starting another. Default to no overlapping execution of the same recurring series; coalesce stale repeats rather than playing a backlog of quarter-hour IDs or ads after a long outage/DJ session. Make explicit expiry or skip choices visible and record why they applied. Already-reserved song-boundary waits remain distinct from outage catch-up.

   Replace pairwise rule comparisons with bounded occurrence and duration overlap checks across all recurrence types, including traffic-generated events. Warn when a sequence is longer than its repeat interval. Batch generation and replenish the horizon incrementally, with indexed station/state/time queries and pagination for both history and search. Process all overdue rows in bounded batches; do not allow old entries or a display limit to starve eligible events.

7. Rebuild the Event editor and audio search around this workflow.

   Keep the main form focused on name, audio/playlist, playback quantity, recurrence, station-local time, date bounds, and INTERRUPT DJ default NO. Show a plain-language summary, estimated duration, and the next 10 run times before save. Keep failed form submissions populated and show field-level errors. Put priority and failure/expiry choices under advanced options with concrete descriptions.

   Make the audio picker a full panel: pinned STATION and COMMERCIALS collections first, then other playlists, then individual audio. Provide All audio, STATION, COMMERCIALS, Music, and Playlists filters, plus “search within this playlist.” Search playlist name, title, artist, filename, cart code, tags, and station-audio subtype, including `station_id`. A matched playlist can be selected as an event target or opened to choose particular items; selection must be unambiguous.

   Show type, duration, playlist count/total duration, enabled/playable status, and private preview controls. Expose unavailable items with a reason when requested, but prevent invalid selection. Keep server-side pagination and deterministic relevance ordering, with exact name/code matches and playlist priority within relevant results. Retain debounced search, cancellation of stale requests, keyboard navigation, accessible announcements, empty/error states, and responsive layout. All results, previews, and mutations enforce station access and existing CSRF permissions.

   Update Events list/detail, Day/Week/Month/Agenda views, Live Assist next-event state, CLI, and commercial exports together. Show full recurrence summaries, DJ policy, planned versus confirmed local time, offset, and waiting/missed reason. Preserve links from traffic-managed events to their finalized commercial logs and their edit protections.

8. Validate and release in dependency order.

   Deliver schema and classification first; then migration tools and converted consumers; then recurrence and playlist execution; then worker/engine handoff; then the editor/search; finally retire Imaging runtime paths after migration verification. Test migration against PostgreSQL, not just SQLite. Use a database-and-media backup as the rollback basis once old references have been converted.

   Required acceptance checks:

   - Existing/new stations have exactly the four intended starters; duplicate names, repeated upgrades, concurrent station creation, and existing deleted starters are handled deliberately.
   - All legacy Imaging audio, groups, carts, clocks, events, traffic, and historical links survive migration. Missing/corrupt files and checksum collisions produce actionable reports. Disabled/rejected/decommissioned audio stays unavailable.
   - STATION and COMMERCIALS are searchable by their classification and subtype, work through upload and bulk edits, and never enter ordinary fallback music accidentally or cross station boundaries.
   - Each requested recurrence works across local midnight, year/month boundaries, February/leap years, short months, DST gaps/folds, fractional offsets, start/end dates, and a different browser timezone. Forecast and worker instants match exactly.
   - Settings timezone changes invalidate obsolete future requests without changing history, duplicate playback, or unexpected changes to the configured local time.
   - Recorded engine output proves a song finishes, event items play in order with no ordinary music between them, then programming resumes. Include songs longer than five minutes, targets near EOF, empty queues, fallback output, paused decks, and partial content failures.
   - INTERRUPT DJ defaults to NO and protects DJ audio; YES performs a boundary handoff and return on both decks, with AUTO_CUE, repeat, standby, carts, crossfades, hold, and microphone cases matching the chosen policy.
   - One-item playlist rotation and whole-playlist snapshots behave correctly across edits, unavailable content, duplicates, worker/engine restarts, disable/cancel, same-time priorities, and recurrence overlap.
   - Finalized commercial events remain protected and commercial airplay is credited only on confirmed starts.
   - Browser coverage includes every recurrence, playlist search/preview/selection, station_id filtering, validation errors, local-time summaries, mobile layout, and keyboard use.
   - Load coverage includes many 15-minute series, horizon replenishment, large catalogs, due-event batches larger than 20, and multiple stations.

Repository verification for this review:

- `venv/bin/pytest -q tests/test_timed_events.py tests/test_event_blocks.py tests/test_playlists.py tests/test_schedule_regressions.py`: 41 passed. One existing SQLAlchemy fixture warning in a playlist fallback test.
- `venv/bin/pytest -q tests/test_visual_schedule.py tests/test_programming_harmonization.py tests/test_traffic.py tests/test_programming_refresh.py`: 49 passed.
- `FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_deck_engine.py -k soft_insert_preserves_current_song`: 2 passed, 7 deselected. The first attempt stopped at startup because the sandbox denied `setsockopt()`; the approved isolated retry outside the sandbox passed. These checks use temporary audio, SQLite, and local sockets, and prove current-song completion followed by event insertion with two or six future requests preserved. They do not test the proposed DJ handoff or playlist events.
- Browser interaction, production data inventory, PostgreSQL upgrade/backfill, and live-station playback were not exercised in this planning review. The migration and acceptance checks above are implementation/release requirements.

Total: 92 targeted tests passed. Passing existing tests establishes the current baseline; it does not establish that the proposed features exist. Only this review document was added to the repository.
