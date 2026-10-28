# Simple, integrated programming

Status: implemented, September 15, 2026. The sections below preserve the design rationale. See [rollout instructions](programming-rollout.md) for database and station runtime activation.

## Implementation and validation

Navigation, calendar coverage, read-only future event projections, multi-day event series, the station default picker, reviewed baseline conversion/restoration, and commercial event/sequence locks are implemented. SOFT events now use an allowlisted insertion operation in the existing program queue, preserving the current song and all queued music. This replaces reliance on a fixed pre-target drain window. Baseline display splits preserve occurrence keys and do not introduce midnight playback transitions.

Validation: the broad non-browser run passed 161 tests; its two ACL tests passed outside the filesystem sandbox. The final focused programming/schedule/event/traffic run passed 37 tests. Browser regressions passed 18 tests with one optional screenshot test skipped. All seven isolated Liquidsoap tests passed, including actual song → event → queued music playback. PostgreSQL full upgrade, downgrade, and re-upgrade passed in a disposable database. Production activation uses the database backup, migration, checked station configurations, and service verification described in the rollout instructions.

## 1. Navigation

Use this order under **Programming**:

```text
Programming
  Music
  Categories
  Sound Room
  Imaging
  Scheduling
    Calendar
    Events
    Templates
    Commercials
    Defaults
```

Scheduling is an expandable subgroup inside Programming. Remove the separate top-level Schedule link. Calendar is the default scheduling destination; Day, Week, and Agenda remain views of that calendar. Use the same names and active navigation throughout.

Templates contains **Show templates**, **Music patterns**, and **Sequences**. Retain existing URLs and records; avoid exposing Clocks and Rotations as additional competing navigation destinations. Imaging remains the shared library for IDs, sweepers, announcements, and commercial audio.

## 2. A simple mental model

**Choose the music. Schedule the programs. Add events between songs.**

| Tool | Job | Example |
| --- | --- | --- |
| Music | Store and approve songs | Import a new release |
| Categories | Group songs | Power, Gold, Local |
| Sound Room | Listen and organize | Audition songs and assign categories |
| Music patterns (rotations) | Repeat a category mix | Power → Gold → Power → Local |
| Show templates (clocks) | Repeat a reusable ordered program | Three music picks, then a sweeper |
| Calendar programs | Give music a start and end | Breakfast, weekdays 06:00–10:00 |
| Events | Insert something near a wall-clock time | Station ID every Monday at 09:00 |
| Sequences | Keep several items together | Sponsor intro → announcement → outro |
| Commercials | Plan campaigns and commercial breaks | Two-minute break around 10:20 |
| Defaults | Fill otherwise uncovered time | Main music pattern |

A category or pattern can be scheduled directly. A user should only need a show template when they want a richer sequence. A clock is currently a repeating sequence, not a guarantee of a 60-minute show or exact minute marks.

## 3. How the existing tools work now

The current calendar already creates bounded weekly programs and dated overrides. Selecting a category or rotation creates a supporting clock automatically; selecting a show template references an existing clock.

In AUTO, music selection follows this order:

1. Active dated calendar program.
2. Active weekly calendar program.
3. Existing weekly assignment, currently labeled **Weekly defaults**.
4. Station default clock.
5. Active fallback rotation.
6. Engine fallback if no playable selection is available.

Weekly defaults are start-time changes that remain active until the next assignment, including across midnight and the week boundary. They do not have explicit ends. Calendar programs temporarily override them; when a program ends, the resolver returns to whichever weekly assignment is active then.

Rotations continue choosing categories in order. Clocks maintain a separate slot cursor. A new program/assignment occurrence resets its clock cursor; a worker restart within the occurrence resumes it. Timed events overlay this selection and do not consume a clock or rotation slot. Normal selection already advances cursors for queued items, so clearing future music requires careful cursor reconciliation.

The current code also supports clock imaging and event-block slots; older clock documentation describing only category/rotation slots is outdated. Calendar edits currently publish directly, and calendar event visibility depends on materialized event occurrences. A full shared draft/publish workflow is not implemented.

## 4. Harmonize defaults without changing existing stations unexpectedly

Make **Defaults** answer one question: “What plays when no program is scheduled?” Offer a category, music pattern, or show template through one picker. Map this onto existing selection services.

During transition:

- Display existing weekly assignments as a muted **Weekly baseline** layer in the calendar, with the actual effective start/end intervals.
- Display the station default underneath remaining gaps. Every time should explain what will supply music.
- Keep existing assignments editable through Defaults while migration is available.
- Offer a reviewed conversion to ordinary recurring calendar blocks. Preserve Sunday wrap, overnight intervals, clock references, timezone behavior, and existing calendar overrides. A single weekly assignment may cover the entire week and must be split into supported daily blocks.
- Compare old and proposed resolved coverage before conversion. Account explicitly for clock cursor resets introduced by splitting intervals; preserve occurrence semantics or disclose and approve that behavior change in the conversion preview.
- Switch off converted assignments atomically. Keep source records and a reversible mapping; never leave two active definitions representing the same baseline.

The eventual everyday model is dated overrides → weekly programs → one station default. Existing stations keep their current resolution order until conversion is explicitly applied.

## 5. Events: IDs, announcements, and commercials

Provide **Add event** directly on the calendar with these fields:

1. Name and approved audio or sequence.
2. Local target time.
3. Once or repeat weekly, with a multi-day picker.
4. Timing: **After the current song** by default.
5. **Play up to … late**, then mark missed.

Suggested initial late allowance: five minutes, configurable per event. Show a warning when the expected current item or an earlier break would exceed that allowance. Existing events retain their saved settings; the current service default of ten seconds is too short for many finish-the-song events.

### Default timing contract

“Play at the first available song boundary at or after the target, within the late allowance.”

Example: an announcement is scheduled for 10:15. The song ends at 10:17:20. Play the announcement, then continue music under the program active at that time. Do not cut the song or advance the music pattern for the announcement.

Use the existing SOFT event path with zero early allowance as the foundation. The present fixed 20-second queue-drain window cannot guarantee the next song boundary when several tracks are already queued. Improve preparation using current playback, durations, and queued requests so the event can own the next eligible transition. Keep changes within the existing worker and queue services.

Define and verify these behaviors:

- Do not begin early under the default policy. Keep early playback and hard interruption in advanced settings.
- Reserve the boundary without inserting silence while waiting for the target. Account for segues, prefetch, and unavailable duration estimates.
- If a song boundary falls before the target, continue music; use the first eligible boundary after it.
- Protect current audio, active sequences, and DJ ownership. Explain a delayed or missed event.
- Events sharing a target run in configured priority order, one at a time. Preview combined duration against each deadline; each event retains its own late allowance.
- A program change during a break affects the music selected after the break. Never clear a queued event when removing stale program music.
- A station ID scheduled by time and an ID inside a show template are distinct occurrences. Warn about close spacing and let the operator remove the duplication; do not silently suppress scheduled content.
- Record actual confirmed starts and lateness. Queued is not aired. Do not claim completed playback without an authoritative completion signal.

Weekly station IDs use this same event model. Multi-day recurrence must retain a shared series identity for editing; optional “every hour during these hours” can follow once series editing is reliable.

## 6. Commercials use the same event execution

Support two entry points:

- **Simple spot:** choose approved commercial audio and schedule it as an event. This alone does not promise campaign accounting.
- **Campaign break:** use existing advertiser, campaign, placement, duration, and separation rules. Review the generated log, then finalize it. Finalization creates the ordered sequence and timed event, as it does today.

Show finalized commercial breaks on the calendar as linked events, with their planned spots and duration. Draft placements are visibly drafts and cannot play. Editing finalized breaks must respect their existing locks; rescheduling and makegoods go through commercial services, not a generic event editor that bypasses them.

Default new approximate breaks to finish-the-song timing. Preserve actual-airplay reconciliation and historical misses. Commercials must never acquire a separate queue executor.

## 7. One calendar for planning and verification

Show music programs as blocks, timed events as markers in a separate lane, and baseline/default coverage as a muted background. Include commercial markers without duplicating the timed events that execute them.

The main actions are **Add program**, **Add event**, and **Preview**. Template creation is optional. Each selected item shows what plays, recurrence, timing, and its source. A future week must show projected events even if the worker has not generated durable occurrences yet; preview must not write execution records.

Preview should answer:

- What supplies music throughout the day?
- Which IDs, announcements, and breaks are due?
- Are audio, categories, and templates usable?
- Which events may collide or miss their late allowance?
- What will resume after a break or a return from DJ mode?

Use station-local time consistently and identify the timezone. Test skipped and repeated DST times against the actual conversion helpers; current prose and helper behavior are not fully aligned. Keep existing recurrence semantics during migration and explain any future policy change before applying it.

Start with existing explicit save/publish actions and a read-only day preview. A shared schedule revision system is a later improvement, not a prerequisite for reorganizing navigation or making approximate events reliable.

## 8. Delivery order and acceptance

| Phase | Deliverable | Acceptance |
| --- | --- | --- |
| 1. Organize | Requested sidebar order, Scheduling subgroup, consistent template names, contextual explanations | Every existing editor remains reachable; selected station and active navigation remain correct |
| 2. Make coverage visible | Baseline/default layers, source explanations, projected event occurrences, unified preview | A week explains all coverage and events without visiting separate schedule pages |
| 3. Make events easy and reliable | Calendar event editor, weekly series, sensible late allowance, boundary-aware queue handling | ID, announcement, and commercial sequence play after current music within policy; subsequent music follows the correct program |
| 4. Consolidate | Defaults picker, reviewed baseline conversion, linked commercial workflow | Coverage equivalence is demonstrated; finalized traffic and history remain intact |

Required runtime verification: long songs and multiple queued tracks; boundary just before/after target; simultaneous events; event plus program transition; sequence crossing a transition; missing audio; deadline expiration; restart before/after submission; DJ takeover and return; overnight/Sunday wrap; DST; and confirmed commercial reconciliation. Use deterministic service tests plus installed-engine playback checks for boundary handling and queue protection.

First-release success: an operator can choose a default music mix, schedule weekday shows, add a weekly station ID and announcement, place a commercial break, and see the resulting week in one calendar without understanding clocks or worker queues.

Defer duration-fitting music, exact-hour backtiming, complex loop policies, and a full revision editor until this workflow is dependable.
