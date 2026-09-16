# Shows and scheduling redesign

Status: deployed on the current installation, September 16, 2026. Scheduling mode activation remains an explicit operator action. This document covers the nine requested changes and the three-mode update, and supersedes conflicting product direction in `programming-harmonization-plan.md`. See [implementation, validation, and rollout](shows-and-scheduling-rollout.md) for delivered behavior, deployment order, and remaining design refinements. The detailed proposal below records the broader design, including refinements beyond this v1 implementation.

## Product direction

Make scheduling a visual composition workspace with exactly three mutually exclusive operating modes: **Calendar**, **Blocks**, and **Simple**. The user chooses which mode runs the channel. Shows are reusable content used by these modes, not a fourth mode. Calendar and Blocks share timeline interactions; Simple uses the same source browser with a focused pick-and-play interface. Events remain an independent layer for hourly IDs, announcements, and commercials in all three modes.

| Mode | User-facing promise | How it runs the channel |
| --- | --- | --- |
| Calendar | “I want precise control.” | Visual day/week/month scheduling. Drag a Show, Category, Artist, Album, or Song onto a time; move, stretch, and repeat it. Best for programming that varies by day/time. |
| Blocks | “I have repeatable daily formats.” | Build reusable 24-hour schedules such as Weekday, Weekend, Friday Night, or Study Day, then assign them to days. Rotate seven different daily Blocks, or any number, in any order. |
| Simple | “Just play this.” | Pick a Show, Category, Artist, Album, or Song and play continuously until changed. |

Use the visual language of a modern audio console: clear time rulers, source strips, artwork, precise handles, and restrained motion. These strips represent sequential audio, not simultaneous mixing. Avoid decorative knobs that imply unavailable audio controls.

### Navigation

Replace the Scheduling disclosure with a normal **Schedule** link that opens the currently active mode's workspace. Its child links remain visible, without a chevron:

```text
Schedule
  Calendar
  Shows
  Blocks
  Simple
  Events
```

Shows sits immediately below Calendar. The Schedule header presents **Calendar / Blocks / Simple** with the descriptions above. Viewing or editing a workspace never activates it. Blocks contains its own library, editor, and date-assignment view; its assignments do not belong to Calendar mode.

Show **Active mode: Calendar / Blocks / Simple** persistently in the Schedule header and the channel's now-playing/status area, using text and a selected indicator rather than color alone. A workspace being viewed has a separate navigation highlight. Inactive workspaces say, for example, **Editing Blocks · Calendar is active**, with a **Use Blocks** action. Keep all three modes' saved configurations when switching.

Remove Templates, Commercials, and Defaults from everyday navigation. Move **Default playlist — what plays when the active mode has nothing playable?** into Station settings → Playback. This is one explicit playlist used by all three modes, including empty scheduled intervals. Settings contains fallback selection, not weekday or time assignment controls. Existing sequences remain reachable in Events → Sequences. Existing music patterns need a compatibility path during migration, not an orphaned menu.

### Core objects

| Object | Meaning | Duration / scheduling |
| --- | --- | --- |
| Source | Category, playlist, artist, album, or song | Reusable content reference |
| Show | Named, described composition of sources | 15 minutes–24 hours; scheduled separately |
| Block | Named, reusable whole-day plan containing Shows or sources | Always 00:00–24:00, with visible station-fallback gaps |
| Calendar placement | A Show or source assigned to an interval | Once or recurring; repeats to fill its interval |
| Block assignment | A saved Block assigned to dates | Weekdays, selected dates, or a repeating date pattern |
| Simple selection | One selected Show or source | Repeats indefinitely until changed |
| Channel scheduling mode | Calendar, Blocks, or Simple | Exactly one effective mode per channel |
| Mode-change request | Confirmed transition from one mode to another | Immediate fade with durable status and acknowledgement |
| Event | Approved audio or an ordered audio sequence at a target time | Overlays all three modes |

Playlists remain available through the shared source browser alongside the five primary choices, and are the required Settings fallback type. Shows cannot contain other Shows in v1; Blocks and Simple can select Shows. This keeps duration and recursion understandable.

## What the checkout actually supports

| Area | Evidence | Consequence |
| --- | --- | --- |
| Events picker | `admin_events.py` loads all eligible songs, imaging, and sequences with `.all()`; `event_fields.html` puts them in one select; `events.js` hides/disables options by type | Replace the unbounded native picker. The reported interaction failure has not been reproduced in a browser; do not claim a confirmed root cause yet. |
| Calendar | `calendar.html` renders stacked cards; `calendar.js` drops categories onto a day and opens a time form | Build a time-positioned grid, pointer-to-time mapping, movement, and resizing. |
| Recurrence | `calendar.py` supports weekdays or one date; TimedEvent constrains recurrence to ONE_TIME/WEEKLY | Add explicit daily intervals and monthly rules. Monthly scheduling is not implemented in this checkout. |
| Templates | Clock stores ordered selection slots; playlist-backed calendar clocks already exist | Preserve the proven selection machinery, but add timed Show composition and direct artist/album/song selection. |
| Defaults | `_station_default.html` combines fallback selection with weekly baseline conversion | Separate fallback settings from schedule migration and editing. |
| Catalog | Artist and Album identities and shared-content availability services already exist | Reuse stable IDs and availability rules; do not identify sources by display name or duplicate audio. |
| Playback | The existing worker owns selection, queue reconciliation, Events, and confirmed-start history | Extend the resolver and selection contract; keep one playback executor. |

## Shared source browser

The right-hand library is always available while composing. Tabs: **Shows, Categories, Playlists, Artists, Albums, Songs**. Hide Shows when editing a Show to prevent nesting. Events uses the same browser shell with **IDs & imaging, Songs, Sequences**, filtered to approved playable content.

- Search by title, artist, album, category, tag, and cart code where relevant. Search within the active tab, with an explicit All results option.
- Debounce queries, cancel stale requests, paginate on the server, and render a bounded list. Never download the entire catalog to populate a control. Keep the selected result visible even when it is outside the current result page.
- Show artwork or a source icon, name, type, playable song count, and duration when known. Distinguish a collection's current total duration from guaranteed schedule coverage.
- Include Recent and Favorites. Category/tag filters, sorting, and artist/album drill-down help users browse when they do not know a title.
- Offer audio preview through the existing preview player. A drag ghost shows the source and proposed duration; Enter or Add opens an equivalent placement action.
- Preserve query, scroll, and selection when switching tabs or opening an inspector. Provide real loading, empty, unavailable, and retry states.
- Apply station access and approval rules to search and revalidate on save and playback. Include legitimately shared music through `availability.py`; filter inaccessible items out of counts as well as results.

For Events, replace **Approved content** with **Choose audio** and a selected-content card with Preview and Replace. Switching content type clears an incompatible selection explicitly. A saved unavailable item remains identifiable with a reason instead of silently becoming another item.

First implementation task: reproduce create/edit picker behavior with songs, imaging, and sequences, including switching types and an empty library. Inspect console errors and actual rendered eligibility. Repair the immediate failure while replacing the scalability bottleneck; a search box layered over thousands of hidden options is insufficient.

## Shows: the composition console

The Show header contains name, description, duration, save state, Preview, and Save. The composition takes roughly two-thirds of the width; the library takes the remainder. A compact inspector opens for the selected section.

```text
Morning Study Monday     [Description…]       Duration [03:00]   Save
┌─────────────────────────────────────────────┬──────────────────────────┐
│ 00:00–03:00 overview / focus window         │ Search your library      │
│                                            │ Categories Playlists …   │
│ 00:00 ┌ Study music playlist ────────────┐  │                          │
│       │ Straight · repeat to fill        │  │ [art] Study music    +   │
│ 00:45 │ ◆ Special song · play once       │  │ [art] Quiet piano    +   │
│       │                                 │  │ [art] Special song   +   │
│ 02:00 │ ◆ Second special song           │  │                          │
│ 03:00 └──────── duration handle ─────────┘  │ Preview · drag · add     │
└─────────────────────────────────────────────┴──────────────────────────┘
```

Use elapsed time inside Shows, wall-clock time in Calendar and Blocks. Users can:

1. Drop a playlist, category, artist, album, or song into an empty Show to cover its duration.
2. Drag a section boundary to change its allocation; drag the body to move it. Drop another source into open time, or choose an explicit split/replace action over occupied time.
3. Add multiple artists to one section, forming a union of their available songs with duplicate song IDs removed.
4. Drop a song inside a collection section and choose **Play once here** or **Loop for a section**. Play-once inserts run at the first song boundary at or after their relative target; the collection then continues. This makes “study playlist plus two special songs” easy without creating global Events.
5. Reorder, duplicate, split, delete, or enter exact time values from the inspector. Blank time visibly uses Station fallback.

A Show's ordinary sections do not overlap. Play-once inserts are children of a section and visibly distinct from looping sections. Inserts consume airtime, not extra duration: the Show still ends at its scheduled boundary. Inserts not reached before the section ends are reported as skipped, not played later in another Show. Station Events take precedence over pending inserts.

### The accordion interaction

Combine an always-visible overview with expandable hour bands. Long Shows open in a compact overview; clicking or briefly hovering a dragged item over an hour expands that hour to minute-level editing. Neighboring hours collapse into labeled summaries. Multiple adjacent hours may stay open.

- A focus window in the overview moves the expanded range. Wheel scrolling moves through time; an explicit zoom control changes detail. Keep the source browser fixed.
- A large end handle changes the Show duration from 15 minutes to 24 hours. Offer 15m, 30m, 1h, 2h, 4h, 8h, 12h, and 24h presets plus direct entry.
- Duration growth exposes fallback space; extending a selected section fills that space with its source. Shrinking across occupied content previews the affected sections and requires an explicit trim action; never silently delete them.
- Snap to 15 minutes by default; expose 5-minute and 1-minute precision. Songs and play-once inserts keep their real audio durations.
- Expanding a band changes display scale only. Show duration changes only through its duration controls. During a drag, stabilize the ruler around the pointer and update the time mapping after expansion so content cannot jump unexpectedly.
- Always show a live proposed start, end, and duration. Escape cancels. Drop creates one undoable operation.
- Keyboard users can select, move, and resize through labeled controls; touch uses generous handles and tap-to-place. Respect reduced motion.

Prototype and validate this interaction before building every editor around it. The standard linear ruler remains available if users prefer it.

## Calendar scheduling

Build Day, Week, Month, and Agenda views. Day/Week use a fixed time ruler on the left, sticky date headers, correctly positioned intervals, a now line, and visible fallback coverage. Month is for date assignment and recurrence; clicking a date opens its time editor. Agenda is the compact accessible alternative.

- Drag any source or Show from the right tabs to a day and time. Default duration: Show's saved duration, song's known duration, or one hour for a collection. All can be resized afterward, including a song stretched to a full day.
- Drag the body to move. Drag the top to change start; bottom to change end. Edge scrolling allows full-day placement. Changing a Show's placement length does not edit the saved Show.
- The placement loops until its end. For a Show, repeat its composition cycle; a shorter placement uses only the beginning of that cycle. Show the relationship, e.g. “3-hour Show · 6-hour placement · repeats twice.”
- Clicking opens a small inspector for source, exact times, recurrence, and playback order. Replace “Schedule a program” with **Add to schedule** and name the chosen source directly.
- Support copy/paste, duplicate to selected days, multi-select, and undo/redo. A drag edits a local draft; **Save schedule** publishes the atomic change set. Show “Unsaved changes” and preserve recoverable drafts.
- Recurring edits offer **This occurrence**, **This and following**, or **Entire series**. One-off moves create exceptions rather than rewriting the weekday series.
- Dropping onto occupied time previews the conflict. Allow Cancel, Move to available time, or Replace affected interval. Replacement splits surrounding content predictably. Never resolve same-level overlaps silently by record ID.
- Put Events in a narrow separate lane with timed markers. Events do not inflate the height or shift the times of music blocks. Clicking a marker reveals scheduled time, timing policy, and actual result when available.

Daily means every N days from an anchor date, not merely seven checked weekdays. Weekly supports chosen weekdays and every N weeks. Monthly supports day-of-month and nth/last weekday, with start and optional end dates. Day 31 skips months without that day; explain this in the recurrence preview. Show the next occurrences before saving.

## Blocks: whole days users can reuse

A Block is always a 24-hour local-day canvas. It uses the same editor with duration fixed at 24 hours and supports Shows plus every source type. Gaps display **Station fallback** and remain intentional; no need to draw 24 hours of music manually.

Workflow: **Blocks → New Block → name it WEEKDAY SCHEDULE → fill it → Save → Assign days → select M T W Th F**. Assignments stay inside Blocks mode. Its date grid uses the shared date components without creating Calendar placements or activating Calendar mode.

Support weekday assignment, selecting arbitrary dates in Month view, and **Repeat a pattern**. The pattern editor accepts an ordered list such as A, B or ten different Blocks, an anchor date, and an end date or ongoing repetition. A/B advances by local calendar date, not every 48 elapsed hours. Show the resulting month before publishing.

Only one Block applies to a date. Conflicting Block assignments must be resolved explicitly. Calendar placements do not override Blocks: only the active mode supplies music. To customize one day in Blocks mode, duplicate its Block, edit it, and assign that version to the date. An unassigned date or empty Block interval uses the Settings default playlist.

Saved revisions separate editing from use. Editing a Block or Show creates a new revision; **Apply to future uses** shows affected assignments before updating them. Current playback completes under its existing occurrence snapshot. Allow copying one assigned day into an independent Block without changing the original.

## Simple: just play this

Choose a Show, Category, Artist, Album, or Song through the shared source browser. Display its artwork/name, source type, preview, and **Play continuously until I change it**. No dates, recurrence form, or duration editor is needed. To compose several sources, create a Show and select it here.

The selection repeats indefinitely while Simple is active. A Show repeats its saved composition; a song repeats itself; collections cycle according to their playback order. Preserve Calendar and Blocks configurations while Simple runs. Replacing the active Simple selection uses the same preview-and-confirm fade interaction as a mode change, with copy saying **Change what Simple plays?**

Each newly activated Simple selection starts from its beginning. A worker restart within that activation preserves progress. Activating Calendar or Blocks resolves its current station-local date/time, rather than replaying intervals that elapsed while another mode was active.

## Confirmed mode changes and immediate fade

Every actual mode change requires a confirmation pop-up. Selecting a mode card or visiting another workspace only opens it for inspection. **Use this mode** opens the pop-up; choosing the already-active mode does not restart playback.

Example:

```text
Switch from Calendar to Blocks?

Current mode: Calendar
New mode: Blocks
Will play now: Weekday → Morning Study

Confirming fades the current audio now and starts Blocks.
Your Calendar schedule stays saved. Events remain enabled.

[Cancel]                         [Confirm & switch now]
```

If there is no playable content at the current position, substitute **Will play now: Default playlist — [name]**, with the reason (no Block assigned, empty interval, no Simple selection, or unavailable source). Show current playback interruption, including an active Event or live/manual handoff when applicable, in the confirmation. Cancel/Escape makes no playback or mode change. An unsaved draft is not activated implicitly: save it first or explicitly select the saved configuration.

On confirmation:

1. Revalidate the target revision, source availability, expected current mode, and default playlist. Resolve the target using the channel's current local time, including any Event due now. A missing first candidate is not an empty source: try the remaining eligible candidates within bounded selection rules.
2. Send one authenticated, durable, idempotent command to the existing worker. Begin the fade as soon as the engine can accept the prepared target; do not wait for the current song, Event, Show, or day to finish. Proposed default fade duration: two seconds, to validate in the engine prototype. Immediate means start the transition now, subject to measured command/engine latency.
3. Remove stale automatic lookahead from the outgoing mode and start the incoming mode at its current position; Simple begins a new cycle. Scheduled Events retain their independent identities and future execution. If this explicit handoff interrupts an active Event/sequence, record it as interrupted and do not replay it automatically or claim it completed. Use an explicit worker-owned handoff for DJ/manual audio so it cannot remain audible underneath the new mode. Ordinary scheduling edits retain existing playback protections.
4. Show **Switching Calendar → Blocks…** until the worker/engine acknowledges the transition. Then show **Active mode: Blocks**. Persist requested/effective mode and command status separately so the UI cannot report a successful switch from an HTTP response alone. Show fallback use separately from the active mode.
5. Reject stale confirmations from another editor with refreshed details. Retries or double clicks must not cause a second fade. If the transition fails, retain the last confirmed mode, report the failure, and reconcile actual audio before retrying; do not claim the target is on air.

### Default playlist when there is truly nothing

All three resolvers use the single **Default playlist** in Station settings when the active mode has no usable content. Do not consult an inactive mode's schedule or treat temporary search/queue loading as an empty source. While fallback plays, show both **Active mode: Blocks** and **Playing default playlist: [name] — no Block assigned today**, for example.

Continue evaluating the active mode so Calendar/Blocks coverage resumes when its next interval becomes available, and retry a repaired Simple source at an eligible boundary. Mode activation still fades immediately even when its resolved destination is the default playlist. Require a playable default playlist during setup; existing channels with an unavailable default need an explicit setup issue. If neither the target nor default is playable at confirmation, do not fade working audio into silence: leave the current mode/audio in place and explain what must be configured. If audio becomes unavailable after activation, report degraded playback and retain the existing engine recovery path without pretending a playlist is playing.

## Events and removal of Commercials

Keep once/weekly Events and add **Every hour**, with minute/second offset, selected weekdays, active hour range, start/end dates, and a preview. “Hourly ID, :00, every day” is one series, not 168 separately edited records. Keep durable occurrence identities and bounded generation so restart cannot duplicate an ID.

Expose After current song, At scheduled time, and When queue is clear using existing timing policies; the exact-time option explains its music interruption behavior. Preserve protected DJ/manual audio and active sequences during ordinary Event execution. A confirmed immediate mode handoff is a separate explicit interruption, as defined above. Existing event timing and lateness settings retain their values.

For v1, commercials are approved imaging audio or ordered Event sequences. Remove campaign/traffic creation from the normal product flow. Existing finalized commercial Events and airplay history must remain intact: inspect existing data before disabling legacy routes. If records exist, retain an administrator compatibility/archive route with existing edit locks until a supported conversion is available. Do not make finalized campaign events editable as ordinary Events by removing their lock checks.

## Playback contract

The editor, read-only preview, worker, and public schedule must share one resolver that dispatches exclusively by the channel's effective mode:

- **Calendar:** dated placement exception → recurring placement → Settings default playlist.
- **Blocks:** Block assigned to the current local date → current section → Settings default playlist for unassigned days or gaps.
- **Simple:** selected Show/source repeating continuously → Settings default playlist if nothing is playable.

Never combine music from inactive modes. Events overlay all three modes. Existing DJ ownership protections apply to routine automation; the confirmed mode-change action performs the explicit immediate handoff described above.

| Situation | Proposed behavior |
| --- | --- |
| Source ends before allocated time | Loop within that source until the interval ends. |
| Single song fills 24 hours | Repeat that song, with Events taking their turns; deliberate repetition bypasses ordinary music-separation preferences, not availability restrictions. |
| Artist-only section | Stay within the chosen artist set. Artist separation must not push selection outside the requested source. Relax repeat preferences within the eligible pool when necessary and explain the behavior. |
| Playlist / album | Playlist honors saved Straight/Random mode; album defaults to disc/track order. Offer explicit shuffle. |
| Category / artist | Default to shuffle cycles without repeats until the eligible pool is exhausted; preserve compatible station selection preferences within that pool. |
| New collection songs | Category/artist/album membership is dynamic; re-evaluate safely at selection/cycle boundaries. Persist stable IDs and progress, not a giant copied playlist. |
| Event completes | Resolve the currently active interval; resume its cursor if still active. Events do not advance source cursors or extend the scheduled end. |
| Interval changes during an Event | After the Event, use the interval active now. Do not resume stale music. |
| Song crosses a music boundary | Finish it by default, then use the interval active now. Explicit mode changes fade immediately; explicitly interrupting Events retain their timing policy. |
| User confirms a different mode | Fade immediately into that mode's current resolved content, or the Settings default playlist if it has nothing playable. |
| Source becomes empty/unavailable | Explain the condition, use the Settings default playlist, and retain the selection/placement for repair. Prevent fallback self-reference and bound failed selections. |
| Worker restart | Resume occurrence and cycle state without duplicate Event delivery or re-running completed inserts. |

Show and Block section positions follow elapsed scheduled time, not the number of songs selected. Prefetched music must be attributed to its interval and reconsidered at transitions without removing protected Event/manual requests. Durable selected/submitted/started state must prevent discarded lookahead from incorrectly consuming committed playlist or insert progress.

Use station-local recurrence and UTC execution. Blocks describe 00:00–24:00 local wall time; DST dates may contain 23 or 25 elapsed hours. Mark missing/repeated hours in the ruler. Preserve the existing skip-gap shift and first-fold Event behavior unless deliberately migrated. For music, evaluate repeated-hour sections by wall time without duplicating occurrence cursors; validate collapsed or conflicting spring-forward windows before publishing. Preview and execution must use the same conversion.

## Technical implementation

Retain Flask, SQLAlchemy, existing media storage, and the worker/engine boundary. Use shared browser modules for source browsing, timeline geometry, accordion zoom, inspector, drag/resize, recurrence, and draft state. No frontend framework migration is required to deliver this design.

Add explicit station-scoped entities for Show/ShowRevision, timed sections and inserts, Block/BlockRevision, Calendar series/exceptions, separate Block assignments/patterns, Simple selection/revision, and Station playback policy with default_playlist_id and the CALENDAR/BLOCKS/SIMPLE mode enum. Store requested/effective mode, activation identity, expected revision, and durable transition command status. Keep source type plus validated target identity and options consistent across editors. Enforce valid durations, acyclic references, revision ownership, and source access on the server. Preserve mode, source, and revision attribution in selection and confirmed-start records.

Introduce authenticated paginated source search, revisioned composition CRUD, interval schedule queries, recurrence preview, atomic schedule-save endpoints, and a confirmed mode-transition endpoint with status observation. Save and transition operations require CSRF, permissions, expected revisions, and retry-safe operation IDs. Reject stale edits with a usable conflict response. Preview is read-only and never generates real execution records or advances cursors. The web process never accesses engine sockets; extend the worker's allowlisted control commands for the immediate fade and reconcile them against engine acknowledgements.

Do not flatten a Show into the current Clock slot list: a slot requests an item, whereas a Show section owns time. Add a resolver result carrying source, section, occurrence, cycle, and next boundary; adapt existing selectors where possible. Keep legacy clocks behind an adapter while new scheduling becomes authoritative.

Primary change areas: `models/__init__.py`; `services/calendar.py`, `schedule.py`, `planning.py`, `clocks.py`, `playlists.py`, `timed_events.py`, and `automation.py`; `automation_worker.py`; Calendar/Events/Station settings routes and templates; `base.html` and `_scheduling_tabs.html`; shared timeline/browser JS and CSS; public schedule serialization and operator documentation.

### Migration

1. Inventory existing clocks, rotations, weekly assignments, Calendar programs, defaults, playlists, Event sequences, and finalized traffic Events. Capture resolved coverage and playback attribution before conversion.
2. Convert timed Calendar uses without changing their intervals. Adapt untimed legacy clocks as explicit legacy sequences until a duration is supplied; do not silently call a per-song clock a one-hour Show. Preserve imaging/sequence slots, rotation behavior, and cursor identity through compatibility playback.
3. Move the default playlist control to Station settings. Convert legacy baseline assignments into visible Calendar definitions, retaining Sunday wrap, overnight behavior, and occurrence continuity. Preserve non-playlist legacy fallback through a temporary compatibility adapter until the operator selects a valid default playlist; do not silently flatten dynamic rotations into a playlist. Settings must not become another scheduler. Existing scheduled channels migrate into Calendar mode without an audible switch; new channels explicitly choose one of the three modes during setup.
4. Compare old/new resolved coverage and occurrence identity across at least the existing 370-day verification window, including relevant DST transitions. Change active definitions atomically so two schedulers cannot compete.
5. Preserve source records and reversible mappings. Disable old scheduling mutation paths after migration; redirect normal users to Calendar. Roll back definitions and resolver activation together if verification fails.

## Delivery sequence and acceptance

| Phase | Deliverable | Completion evidence |
| --- | --- | --- |
| 1. Repair and simplify | Reproduce/fix Events picker; scalable search; ordinary Schedule navigation; fallback moved; Commercials removed from v1 flow | Create/edit an Event across all content types; correct station access; navigation and existing scheduled playback preserved |
| 2. Interaction prototype | Three-mode selector/status, confirmation dialog, source library, time ruler, accordion, drag/resize, exact inspector, keyboard path | Build the study Show and stretch a song across a day; distinguish viewed versus active mode; Cancel leaves playback unchanged |
| 3. Playback foundation + Shows | Revisions, timed sections/inserts, source adapters, repeat contract, Show library/editor | Preview and deterministic worker tests agree for playlists, multiple artists, album order, song loops, transitions, and Events |
| 4. Calendar | Day/Week/Month/Agenda; all source tabs; drag/resize; drafts; recurrence and exceptions | Save a weekday Show; move one occurrence; edit following occurrences; resize to 24 hours; resolve overlap predictably |
| 5. Blocks + Simple + immediate transitions | Fixed-day editor, independent Block assignments, Simple picker, durable confirmed mode changes and engine fades | Assign Weekday Schedule to M–F; alternate two or seven Blocks; arrange ten across a month; run Simple indefinitely; verify all six directed mode changes, fallback, and hourly Events |
| 6. Migration and rollout | Legacy conversion, public schedule parity, documentation, browser/performance/engine verification | Coverage preserved, recovery tested, actual-start history correct, and no duplicate execution paths |

Prototype gates validate usability; each later phase also needs service and browser verification. Do not ship the full visual scheduler against an engine that cannot honor its repeat and timing contract.

Test the source browser with a seeded 100,000-song catalog and thousands of collections: bounded response/DOM sizes, indexed queries, pagination, stale-search cancellation, shared-content access, and selected-item persistence. Proposed performance targets on an agreed reference environment: usable first results under 500 ms at p95 and smooth dragging without network requests on each pointer movement. Measure before claiming these targets are achieved.

Required behavior checks: 15-minute and 24-hour Shows; play-once inserts around Events; one-song loops despite separation settings; overlapping edits; series exceptions and monthly edge dates; A/B pattern anchoring; empty collections; removed/shared content; revision conflicts; midnight and Sunday wrap; both DST changes; Event lateness/collisions; protected DJ takeover during routine automation; queue transitions; restart during submission; and migration rollback. For mode changes, cover all six directions, Cancel/Escape, viewing without activating, already-active mode, draft versus saved configuration, immediate fade rather than song-end waiting, Event/sequence interruption attribution, explicit DJ handoff, due Events at activation, absent content using the configured default playlist, unavailable default, stale confirmations, repeated submissions, delayed acknowledgements, engine failures, and restart during a fade. Verify inactive-mode content never leaks into playback and inactive configurations survive switching. Run isolated installed-engine proofs for fade latency, interruption, and queue behavior, beyond browser mocks.

## Decisions adopted for this proposal

- The user chooses exactly one of Calendar, Blocks, or Simple to run the channel. Shows and Events are shared tools, not operating modes.
- Active mode is always identified in text; viewing another workspace does not activate it.
- Every mode change requires a confirmation pop-up, then immediately fades to the newly selected mode. The UI reports success only after worker/engine acknowledgement.
- Normal music boundaries finish the current song; confirmed mode changes and explicitly interrupting Events are deliberate exceptions.
- Shows are saved compositions; Calendar placement length is independent and may repeat them.
- A Block is a full local day with its own date assignments, independent of Calendar mode.
- All three modes use the Settings default playlist when their active selection or current interval has nothing playable; inactive modes never act as fallback.
- Playlist sources are available everywhere. Multiple artists form one selectable pool.
- Saving a Show does not silently rewrite all existing scheduled uses; applying a new revision is explicit.
- Timeline edits publish together through Save schedule; saved drafts do not alter on-air playback.

These choices make implementation concrete and can be adjusted during prototype review without changing the overall model.
