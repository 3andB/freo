Scheduling and Events: current-code review and completion plan

Reviewed 19 September 2026 against commit `ce66f6d`. Scope: planning only. No application code, station database, media, engine configuration, or running services were changed. This document supplements the [original plan](events-station-commercials-plan.md) and [implementation/release notes](events-station-commercials-release.md). Those notes describe an earlier deployment; this review did not independently verify live deployment state.

Subsequent implementation authorized by the user is documented in the [completion and activation notes](events-completion-2026-09-19.md). The findings below describe the code at review time.

Most requested functionality already exists. The remaining work is to finish Imaging retirement, correct editor and display gaps, and prove scheduling and playback behavior across lifecycle and DJ transitions. Reimplementing the existing feature would introduce unnecessary migration and playback risk.

The review covered models and migrations, event routes/templates/JavaScript, recurrence expansion, Settings timezone changes, playlists and classification, audio discovery, Imaging conversion and remaining consumers, event/block execution, worker queue control, the Liquidsoap event protocol, CLI, calendar projections, commercial integration, and the relevant tests.

**Requirement assessment**

| Requested behavior | Current code | Completion work |
| --- | --- | --- |
| Remove Imaging | Navigation/management routes retired; conversion maps legacy audio to Track | Remove remaining live selectors and write paths; retain migration/history access deliberately |
| Third default: STATION | Stable system collection and purpose exist; new and existing stations are seeded | Guarantee third position even when custom playlists already exist |
| Identify station audio and `station_id` | `audio_kind=STATION`, subtype labels, upload/editor/bulk classification, automatic membership | Finish consistent naming and verify every import/edit path; keep subtype separate from station ownership |
| Fourth default: COMMERCIALS | Stable system collection and automatic membership exist | Guarantee fourth position and verify defaults/backfill/name collisions |
| Identify all station commercial audio | `audio_kind=COMMERCIALS`; station-private availability | Verify classification, search, disabled/deleted state, and traffic references together |
| Schedule both collections through Events | PLAYLIST targets, one-item rotation and finite full-playlist execution exist | Verify selection defaults, snapshots, failure recovery, and contiguous playback |
| One-time, 15-minute, hourly, daily, weekly, monthly | All six are implemented in recurrence expansion and the editor | Fix irrelevant-field validation; improve previews and summaries; expand edit-path coverage |
| Play after current song | New browser events use SOFT insertion; reserved boundaries survive long songs | Exercise DJ standby, source changes, cancellation races, restart, and simultaneous events in the real engine |
| INTERRUPT DJ: Yes/No, default No | Form, model and service default No; a dedicated DJ event bus exists | Verify transition cases and make blocked/waiting outcomes clear |
| Settings local time everywhere | Inputs and expansion use station timezone; UTC retained for execution | Display dates, seconds and offsets where needed; verify timezone changes with queued/playing events |
| Full audio search, priority to STATION/COMMERCIALS | Paginated Events browser, classification filters, playlist-first results, item previews | Improve search-within behavior, validation consistency, metadata coverage and large-library performance |

**Confirmed findings**

1. Imaging is not fully retired from active workflows. `app/routes/admin_live.py:38` still loads legacy assets, and its action handler accepts `queue-imaging`. `app/templates/admin/live.html:26` exposes Imaging in the cart picker. `app/services/live_assist.py` can assign and queue legacy assets. `app/services/timed_events.py:45` and `app/services/event_blocks.py` still accept new legacy references; traffic and schedule discovery retain compatibility branches too. Removing the Imaging navigation does not satisfy complete feature retirement. Once migration has been verified, new writes must resolve to unified audio or reject legacy targets.

2. Daily/Monthly saving can be blocked by invisible weekday choices. `app/static/events.js` hides recurrence-inapplicable controls without disabling them; `app/services/timed_events.py:125` requires weekdays for every repeating recurrence even though Daily/Monthly expansion ignores weekdays. Reproduced with isolated service calls and an authenticated form POST: both reject empty weekday selections with “Choose at least one repeat day.” A user can reach this by clearing weekly days and changing recurrence. Hidden hourly controls also require normalization when changing recurrence. Preview and save currently validate independently and can disagree.

3. STATION and COMMERCIALS are not guaranteed to appear third and fourth for existing stations. `app/services/playlists.py:21` sorts by database ID. Reproduced order: Playlist 1, Playlist 2, Existing custom playlist, STATION, COMMERCIALS. Events search has its own correct system-collection priority, so this is a playlist-list ordering gap.

4. “Preview next 10 runs” is bounded to 370 days. `app/routes/admin_events.py:154` expands a year and slices ten values. Reproduced: monthly day 31 starting February 2028 returns seven dates despite having no end date. One-time dates beyond that horizon also need direct handling. Preview should return ten actual future runs when possible, or explain that the rule ends sooner.

5. Event lists and occurrence history omit the date. Both event templates call `format_station_time(..., true)`, which in `app/services/admin_view.py:28` produces only `HH:MM`. Multiple days, one-time dates and second-level targets are indistinguishable. Timezone conversion exists, but these displays do not provide enough local-time information to operate the schedule reliably.

6. Existing tests do not establish the complete user workflow. `tests/test_events_browser.py` cycles through all recurrence controls but saves only a quarter-hour event. It does not save/edit all six types or test transitions between them. Dedicated engine tests cover SOFT insertion and DJ decks A/B, but those were not rerun in this planning review.

**Playback and lifecycle questions to resolve with targeted tests**

These are code-review risks, not claims of reproduced live failures:

- The DJ event arm logic in `deploy/liquidsoap/station.liq.template:380` checks audible A/B deck state. DJ standby can still have an audible automatic source. Verify that an event allowed to interrupt DJ waits for that source to finish too; otherwise arming can select immediate event playback when neither DJ deck is active.
- Exercise pause, clear, crossfade, deck replacement, repeat, AUTO_CUE, cart takeover, microphone activation and mode changes after an event reserves a boundary. Reservation must follow the actual audible source and cannot become a permanent wait or cut a song.
- `process_timed_events` and `process_dj_events` fetch up to 500 occurrences. Prove that stale backlog, many quarter-hour events and concurrent workers cannot delay a due event indefinitely or defeat stale-repeat coalescing. A larger query limit alone is not a correctness guarantee.
- Cancellation/edit/timezone changes and queue submission span database commits and engine commands. Verify acceptance immediately before/after cancellation, worker failure after engine acceptance, delayed START/END evidence and engine identity changes. Only the occurrence's future requests should be removed.
- Full sequences are submitted together. Verify item failure before submission, decoder failure after submission, trailing failed items, operator abort and return to programming. Distinguish partial/failed playback from complete success; do not leave future failed-sequence audio orphaned in the queue.
- Confirmed END handling exists, but block completion also retains a duration/active-request fallback. Verify that pauses, stream interruptions and engine restarts cannot create false completion.
- Settings changes invalidate event definitions, including commercial-generated events. Verify future commercial log dates, placement history and finalized-log protection remain consistent. Started/completed occurrences must remain historical facts.
- Retained HARD and NON_INTERRUPTING definitions, CLI creation and traffic-generated events need an explicit compatibility policy. Existing HARD behavior still permits cutting audio; it must not be mistaken for the requested after-song behavior.

**Proposed product behavior**

Keep four starter playlists in this order: Playlist 1, Playlist 2, STATION, COMMERCIALS, followed by custom playlists. Preserve the existing separation between playlist purpose and playback mode: STATION/COMMERCIALS describe content; STRAIGHT/RANDOM describe order.

STATION and COMMERCIALS remain persistent system collections containing every item classified that way for the owning station. Classification changes update collection membership atomically. Users can order these collections and create custom subsets. Unavailable audio remains identifiable but cannot be scheduled for playback. Removal from a system collection requires reclassification; deleting the system collection is unavailable. Existing custom playlists named STATION or COMMERCIALS retain their identity and contents, with a clear system badge to distinguish the defaults.

Interpret “STATION prompts, station_id” as station promos, IDs and announcements. Preserve the existing labels `station_id`, `promo`, `announcement`, `jingle`, `sweeper`, `liner`, `cart`, and `generic`. The `station_id` label describes audio; the database `station_id` identifies its owning station. Do not conflate them or rely on filenames. Station/commercial material stays out of ordinary music fallback and music separation history, and private to its station.

Keep current playlist-event defaults: STATION plays one next item, rotating across occurrences; COMMERCIALS plays the selected playlist once in full. Both are explicit editable choices. A commercial campaign subset can be selected instead of the all-commercials collection. Each run is finite, with a frozen item order; later edits affect later runs. Preserve existing advertiser, campaign and proof-of-play records.

| Recurrence | Controls and expected meaning |
| --- | --- |
| One-time | Local calendar date and time |
| Every 15 minutes | Selected weekdays/hours, minute offset, seconds, optional date range; offset 0 means :00/:15/:30/:45, offset 5 means :05/:20/:35/:50 |
| Hourly | Selected weekdays/hours, minute and second, optional date range |
| Daily | Local time every day, optional date range |
| Weekly | One or more weekdays and local time, optional date range; preserve existing selected-hour rules when editing legacy definitions |
| Monthly | Day 1–31, last day, or ordinal/last weekday, local time and optional date range |

Missing monthly dates are skipped, not moved silently. Preserve the current daylight-saving policy: nonexistent local times shift forward by the gap; repeated local times run once, using the first occurrence. Deduplicate shifted quarter-hour targets. Preview explains affected dates. Recurrence is anchored to intended local targets, never the actual delayed start of the preceding run.

All input, summaries, calendars, occurrence history and operator exports use Settings → station timezone. Show local date and time, including seconds when configured and offset where needed to distinguish repeated hours. Keep UTC internal for execution. A station timezone change preserves future local wall times and rebuilds unstarted occurrences; historical actual instants stay unchanged. Show the effect before a Settings change is saved.

At the scheduled target, reserve the next eligible song boundary, play the event ahead of future normal music, keep a sequence together and return to the applicable programming source. Never start early or cut the current song for a newly created event. Preserve the queued music order. If no song is active, start when due.

INTERRUPT DJ defaults to No. No protects DJ control and uses the visible wait/recovery allowance, then records a missed event if DJ control prevents execution. Yes allows a handoff after the current audible song and returns control after the event. Keep live microphones protected, as the current implementation does. These playlist defaults and microphone behavior are planning assumptions retained from the current implementation, rather than additional explicit user requirements.

For collisions, keep target time first, then higher priority, then a stable occurrence ID. An active event sequence finishes before another event starts. Default stale-repeat handling skips superseded repeats; PLAY_LATE has a bounded recovery allowance. Waiting for an already reserved song boundary must not expire merely because that song exceeds five minutes. Display why an event is waiting, missed, failed or partially played.

**Implementation sequence**

1. Finish audio and playlist behavior.

   Add explicit starter ordering that works for upgraded stations; backfill stable identities for the original two starters only where their origin can be established, preserving ambiguous user-created playlists. Verify idempotent default creation and name collisions. Make upload, edit and bulk classification consistent, and keep privacy/fallback exclusions. Update remaining “song/imaging” language to audio where it covers all three kinds.

   Complete the Imaging reference inventory across live carts, Events, blocks, clocks, traffic, jobs and history. Convert any remaining active references using the existing resumable converter. Stop new legacy references at all write entry points; old URLs can redirect through the mapping. Remove obsolete live pickers, handlers and runtime branches once consumers use unified audio. Preserve original files, mapping evidence and upgrade migrations until conversion and historical access are verified. Physical deletion of historical data is not required to remove the user-facing feature.

2. Unify event validation, preview and presentation.

   Parse a recurrence-specific rule through one shared validator for browser save, preview and CLI. Ignore/disable irrelevant form inputs. Preserve submitted values and the chosen audio label on failed validation. Validate enabled/playable tracks, sequences and playlists consistently at save and again at execution. Generate preview incrementally to ten future runs, handling one-time dates directly and reporting exhausted date ranges. Reuse the same expansion function for worker, calendar and conflict warnings.

   Show full local dates in Events and history, clear recurrence summaries and effective hours/minute offsets. Present friendly waiting/completion labels and actual start/end evidence. Keep legacy timing conspicuous and provide an intentional conversion to after-song timing; do not silently change existing schedules. New normal Events should expose only the requested after-song behavior.

3. Complete the audio search area.

   Keep default order STATION, COMMERCIALS, other playlists, individual audio; pin/badge the two system collections in the unfiltered view. Support All, Playlists, STATION, COMMERCIALS, Music and Sequences. Search title, artist, album, filename, subtype, cart code, tags and playlist name. Distinguish the library's station ownership from its audio labels.

   Make “Search within” open a clearly named playlist scope without unexpectedly retaining the playlist-name query. Offer item preview, duration, count, availability reason and selected target summary. Show the execution duration for ONE versus ALL. Preserve pagination and keyboard/mobile operation. Avoid loading every item of every result playlist merely to compute counts/duration; use batched queries and test realistic library sizes. Discovery must not label an unavailable sequence as playable without validation.

4. Harden worker and engine execution.

   Add focused regressions for the source/queue risks above, then fix demonstrated failures. Unify boundary ownership across automatic music, DJ decks and DJ standby. Revalidate the actual source during handoff; never use a UI timer as playback evidence. Maintain idempotent submission, cancellation, completion and return-to-programming behavior across crashes and operator changes.

   Drain/paginate due occurrences independently of UI limits. Serialize edits, disabling, timezone changes and handoffs consistently. Coalesce stale repeats using database-backed due-state checks. Ensure conflicting event durations produce warnings without promising an exact start that would require cutting a song.

5. Validate migration and release readiness.

   Run service/route and browser regressions, then disposable PostgreSQL migration/concurrency checks and isolated Liquidsoap recordings. Run the broader required repository checks after fixes. Validate installation/update on a fresh test environment because database and engine protocol changes must work together. Provide a concrete upgrade/rollback procedure only for changes actually required by the final implementation. Use controlled station playback verification at deployment; do not equate passing tests or an old release note with live verification.

**Acceptance checks before calling this complete**

| Area | Required evidence |
| --- | --- |
| Recurrence editor | Create, save, reload, edit and disable all six types; switch every relevant type combination, including cleared hidden fields; preview agrees with saved runs |
| Calendar/timezone | Browser/server/station in different zones; fractional offset; full-hour and half-hour DST; leap year, day 31, fifth/last weekday; date ranges; timezone change with pending/queued/playing events |
| Automatic playout | Single audio, one playlist item and full sequence; current song longer than recovery allowance; no early start/cut; no ordinary music between sequence items; preserved future queue |
| DJ/live sources | No/Yes on decks A and B, crossfade, pause, clear, repeat, AUTO_CUE, standby automatic audio, carts, live microphone and operator mode change; correct return state |
| Lifecycle | Edit/disable/cancel before preparation, after preparation, during submission and queued; active item finishes; restart before/after engine acceptance and START/END; stale engine identities; no duplicate airing |
| Collisions and recovery | Same target with different priorities; sequence crossing another target; overdue repeated runs; >500 due occurrences; outage beyond allowance; no indefinite queue ownership |
| Audio and discovery | New/upgraded station defaults, custom name collisions, classification/reclassification, foreign-station isolation, enabled/disabled/deleted/missing audio, search filters/pagination/preview, large playlists |
| Imaging/traffic | Every active reference migrated; no new legacy references through UI/API/CLI; retained historical mapping; traffic placements and confirmed-airplay history preserved; rerun is safe |

**Verification performed in this review**

`venv/bin/pytest -q tests/test_station_events.py tests/test_timed_events.py tests/test_event_blocks.py tests/test_playlists.py tests/test_imaging.py tests/test_traffic.py`

Result: **59 passed**. One existing playlist fixture SQLAlchemy warning was reported; pytest also warned while cleaning older temporary directories. Additional isolated in-memory service/route probes reproduced the weekday validation, starter order and monthly preview findings. No application fixes or permanent tests were added. Browser, PostgreSQL concurrency and real-engine tests are completion gates in the plan, not checks claimed as performed here.
