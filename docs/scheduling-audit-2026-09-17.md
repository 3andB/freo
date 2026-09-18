# Scheduling audit and proposed repair plan

Audit date: September 17, 2026. Source revision: `c9fb54b`.

This records the pre-repair findings. See [the repair and verification notes](scheduling-testing.md) for the subsequent implementation and current test commands.

The scheduler has working selection, recurrence, fallback, and mode-switch machinery, but the editor has reproducible data-integrity and interaction defects. Passing the existing tests is insufficient to certify the complete scheduling experience. Repair the editing model and expand regression coverage before treating it as reliable for complex scheduling.

This audit inspected the Calendar, Shows, Blocks, and Simple editor; validation and persistence; legacy conversion; recurrence and timezone resolution; worker selection and queue refresh; mode switching; timed Events and sequences; and public schedule generation. Tests used isolated databases, temporary media, and a separate Liquidsoap process. This is a source and isolated-runtime audit, not certification of the currently broadcasting station. Application behavior was not changed.

## Findings

Priority P1 means possible loss or unintended change of saved programming. P2 means incorrect interaction, validation, presentation, or a reliability gap requiring follow-up. “Reproduced” identifies observed behavior; “code review” identifies a path still needing its own browser or engine regression.

| ID | Priority / evidence | Finding and reproduction | Repair target |
| --- | --- | --- | --- |
| S01 | P1 / browser reproduced | An idle editor adopts a newer server revision without adopting its document. Open a 09:00–10:00 entry, change it elsewhere to end at 11:00, wait for polling, then edit the old page. Its save succeeds and restores the stale 10:00 end. The reproduction used a separate database update as the second editor. | `app/static/schedule_studio.js:81`: bind the base revision to the exact loaded document; either refresh both atomically or retain the old revision and require conflict resolution. Apply the same rule to draft restoration. |
| S02 | P1 / browser reproduced | A no-op “Entire series” edit from October 5 changes a September 21 anchor to October 5 and clears a September 28 exception. Earlier occurrences disappear and recurrence phase can change. | `schedule_studio.js:46–49`: preserve the original rule and exceptions, changing only explicitly edited properties; implement distinct occurrence, following, and series transformations. |
| S03 | P1 / browser reproduced | A Monday 23:00–Tuesday 02:00 occurrence opens from Tuesday as 00:00–02:00 on Tuesday. Removing “This occurrence” excludes Tuesday instead of its Monday origin, leaving the target occurrence scheduled. The same clipped representation feeds edits, split, and drag. | `schedule_studio.js:33,43,47–52`: retain canonical start/end and origin separately from each visible day fragment. |
| S04 | P1 / JavaScript reproduced | Editing a recurring occurrence into an occupied once-only interval and cancelling replacement still adds the occurrence exception. The reproduction leaves no undo entry and no dirty flag. A later unrelated save can publish that hidden change. | `schedule_studio.js:48`: calculate the complete proposed mutation separately, confirm it, then commit one atomic undoable operation. Cancellation must leave document and history identical. |
| S05 | P2 / browser reproduced | At a 320px viewport, the Shows page measured 362px wide. A 00:14–00:15 section in a 15-minute Show extended about 20.6px past the timeline end: the entire timeline was 21px tall while the section had a 22px minimum visual height. | `schedule_studio.css`, `schedule_studio.js:37–42`: fix responsive containment and distinguish a short interval's accurate bounds from its accessible hit target. Do not solve this merely by hiding useful controls. The native duration slider itself stayed inside the canvas in the sampled layouts. |
| S06 | P2 / JavaScript reproduced; scrolling path reviewed | A purely horizontal drag never starts because movement detection checks only vertical distance. Auto-scroll also recalculates both the initial and current pointer offsets against the current column rectangle, losing the initial scroll position. | `schedule_studio.js:43`: use two-dimensional movement detection, a captured starting timeline coordinate, current scroll offsets, bounded snapping, and consistent cancel/pointer-capture cleanup. |
| S07 | P2 / service reproduced from editor transformation | Split copies all play-once inserts into both halves. A 45-minute insert in a one-hour section therefore lies outside the first half, and saving fails with an insert-time validation error. Moving, duplicating, trimming, and overlap replacement also copy absolute insert positions without consistently transforming them. | `schedule_studio.js:43,48,51–52`, `visual_schedule.py:141`: define insert behavior per operation; partition on split and shift or explicitly remove with confirmation as appropriate. Validate before committing the edit. |
| S08 | P2 / service reproduced | Collision validation checks 370 days from each anchor, but accepted rules can first collide later. A daily rule every 365 days from January 1, 2026 and a monthly rule on the 31st pass validation, then conflict on December 31, 2028. Runtime selects fallback with “Conflicting schedules.” | `visual_schedule.py:256–292,341–366`: make the finite validation horizon explicit and provide ongoing conflict checks, or implement an overlap algorithm covering the supported recurrence contract. |
| S09 | P2 / code review | Blocks Save uses two independent requests: save composition, then save assignments. A revision conflict on the second request leaves a partially saved operation. A new Block revision also does not automatically update existing pattern references. | `schedule_studio.js:66`, `schedule_studio.py:140–190`: decide and expose the intended composition/assignment transaction; preserve revision pinning but make the assigned revision apparent. |
| S10 | P2 / code review | Controls remain editable during Save. The response can clear dirty state and remove the draft even if another edit occurred while the request was pending. Calendar entries are not reconciled with the subsequently fetched state. | `schedule_studio.js:66`: snapshot each save and acknowledge only that edit generation; preserve later edits and serialize submissions. |
| S11 | P2 / code review | Month and Agenda do not render the loaded Events overlay. Month-to-Day navigation also renders immediately without reloading Events for the clicked day. | `schedule_studio.js:44–45,70`: establish consistent Event visibility and reload the visible date range. |
| S12 | P2 / code review | Transition socket failures time out only while PENDING. PREPARING/FADING can keep retrying indefinitely, and an APPLIED response without an observed start can also wait indefinitely. Pending transitions block schedule edits. | `schedule_switch.py:12–83`: specify reconciliation and recovery deadlines for every stage, preserving actual playback facts; test socket loss, missing acknowledgements, and worker/engine restarts. |

Additional usability checks should cover mixed duration controls: exact minutes accept values the 15-minute range step and preset menu cannot represent; new/open composition actions do not consistently reset history and dirty indicators; recurring overlaps are often rejected only at Save rather than resolved at the edit; short sections have overlapping top/bottom resize hit areas on mobile.

## What works, and what “works” means

The existing service suite covers mode isolation, source selection, intentional song loops, immutable Show revisions, nested Shows, inserts, recurrence, legacy weekly wrap, DST boundaries, authorization, CSRF, revision checks, Event occurrence uniqueness, queue recovery, and protected content. The new overnight service probe confirms that resolution itself preserves occurrence identity across midnight; S03 is an editor problem.

The isolated installed-engine test passed after granting its temporary local socket access. It verifies an immediate confirmed mode switch before the outgoing 40-second song ends, a measured fade, actual-start acknowledgement, and idempotent retry. This is one real engine scenario; six directed mode changes are covered separately with mocked engine observations. It is not evidence of every failure/restart combination or of a multi-day broadcast soak.

Routine schedule boundaries choose subsequent content and allow the current song to finish. The worker checks boundaries and limits advance queueing; those boundaries are not guaranteed hard cuts at the displayed second. Confirmed mode changes and permitted interrupting Events have separate interruption behavior. Public listing publication is also separate from live playback; test their intended parity and publication timing explicitly.

## Proposed implementation sequence

1. **Freeze evidence and add failing regressions.** Turn the audit reproductions into permanent tests asserting the desired behavior, not the defects. Add browser error capture, screenshots, saved-document snapshots, and deterministic dates. Include two real browser sessions for S01 and delayed server responses for S10. Keep fixtures and sockets isolated from the live station.
2. **Repair edit transactions and persistence.** Address S01–S04 and S07 before cosmetic work. Extract pure document operations from the DOM code. Preserve canonical intervals, recurrence origin/phase, exceptions, insert positions, and revision identity. Make overlap replacement, cancel, undo/redo, and save acknowledgements atomic. Resolve the Blocks partial-save contract.
3. **Repair geometry and time controls.** Address S05–S06; reconcile exact duration, presets, and slider. Exercise both edges, both drag axes, scroll boundaries, collapsed/expanded hours, midnight fragments, tiny intervals, full-day content, touch, keyboard, zoom, and narrow dialogs. Derive visual bounds from one time-coordinate model.
4. **Verify resolver, Events, public views, and recovery together.** Address S08 and S11–S12. Compare selected content, next transition, occurrence identity, Event state, confirmed history, and published listings against an independent reference model. Exercise the six mode directions and inactive-mode isolation with real engine observations where feasible.
5. **Run load and soak acceptance.** Use production-shaped PostgreSQL in an isolated environment; stress concurrent editors, schedule density, the two-second worker budget, source availability changes, and restart recovery. Then run a 48–72 hour isolated audio soak with explicit silence, duplicate occurrence, missed Event, and stuck-transition detection.

## Extensive testing matrix

| Layer | Required cases | Acceptance evidence |
| --- | --- | --- |
| Pure editing operations | Add/remove; split/duplicate; replace/cancel; move/resize; insert transformations; undo/redo; one/following/series edits | Original document unchanged on cancellation; exact undo/redo; unrelated occurrences unchanged; every committed edit validates and survives save/reload. |
| Time and recurrence simulation | Seconds at every start/end; midnight/Sunday wrap; leap day; month end; nth/last weekday; exceptions; 1–365 intervals; 15-minute/24-hour Shows; A/B and longer Block patterns | Deterministic reference comparisons over multiple years, with seeded randomized cases and boundary-heavy sampling. Cover New York, a non-DST zone, fractional-offset zones, and Lord Howe's half-hour DST change. |
| Browser geometry | Actual measured widths 320, 390, 768, 1024, 1440, 1920; 100–200% zoom; mouse/touch/keyboard; long names; Day/Week/Month/Agenda | No document-level overflow; deliberate horizontal timeline scrolling contained in its viewport; bars stay within their day/composition bounds; controls remain reachable; inspect screenshots as well as DOM bounds. Wait for each requested viewport to settle before measuring. |
| Browser persistence | Two editors; stale recovered draft; edits during Save; double Save; failed/slow request; partial Block save; navigation while dirty | No silent lost update; correct conflict message; later edits remain dirty; retries do not duplicate data; reload reproduces the acknowledged saved document. |
| Backend/API | Station isolation; access roles; CSRF; malformed documents; unavailable/deleted sources; composition revision pinning; overlap priorities; concurrent writes | Validate against PostgreSQL as well as SQLite. Confirm transaction/locking behavior using concurrent requests, not mocks alone. |
| Worker and engine | Six directed mode changes; routine boundaries; all Event timing modes; inserted songs; sequences; DJ takeover; missing media; socket failure; restart at each durable transition stage | Correct confirmed audio and history; bounded recovery; no duplicate occurrence or abandoned transition; protected queued content respected. Capture audio, commands, decisions, and occurrence IDs. |
| Public schedules | Active mode versus inactive drafts; revision application date; fallback; overnight/DST; publication and refresh | Public timestamps and labels agree with the intended publication snapshot and resolver; preview has no cursor/history side effects. |
| Performance | 100k tracks plus thousands of collections; 1/100/1,000 definitions; dense Events/inserts; many stations; long planning horizons | Measure API p50/p95, SQL count, document validation time, browser frame/input latency, DOM size, worker tick duration, and memory on a stated reference environment. The source-search benchmark alone is insufficient. |

Proposed CI split: fast editing/service regressions on every change; scheduler browser coverage on every scheduler change; nightly PostgreSQL, randomized recurrence, and engine fault tests; periodic multi-day soak. Keep random seeds and failure artifacts so every failure is reproducible.

Release gates: all S01–S07 data and interaction reproductions fixed; no stale-save data loss; no unexplained geometry overflow; no duplicate Event execution; all mode directions and documented recovery paths verified; complete results with skips and environment limits visible. Define performance thresholds against the reference deployment before treating measured speed as acceptance.

## Reproducible existing-suite commands

Run from the repository with the development dependencies, Chromium/driver, ffmpeg, and Liquidsoap available. Browser and engine tests require local socket access. These fixtures create isolated databases and media; do not substitute the live database.

```sh
venv/bin/pytest -q tests/test_schedule.py tests/test_visual_schedule.py tests/test_timed_events.py tests/test_event_blocks.py tests/test_programming_harmonization.py tests/test_programming_refresh.py
venv/bin/pytest -q tests/test_schedule_studio_browser.py
venv/bin/pytest -q tests/test_automation.py tests/test_playlists.py tests/test_traffic.py tests/test_player_experience.py
FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_schedule_engine.py
FREO_SCHEDULE_SCALE=1 venv/bin/pytest -q -s tests/test_schedule_scale.py
```

## Audit evidence

Temporary reproduction sources: `/tmp/test_scheduling_audit_probe.py`, `/tmp/test_scheduling_service_probes.py`, `/tmp/scheduling_js_probes.cjs`. These probes intentionally confirm current defects; convert them into desired-behavior regressions during implementation. Browser observations are in `/tmp/freo-scheduling-audit-probes.json`; JavaScript observations are in `/tmp/freo-scheduling-js-probes.json`.

The baseline service run passed 64 tests. Its three browser fixtures initially failed to open sockets under the sandbox; they were rerun separately with local socket access. The engine test likewise initially failed on sandbox `setsockopt`, then passed in 26.55 seconds. The 100k metadata-row SQLite search benchmark passed, measuring 8.3ms median / 26.2ms p95 with bounded 40-row responses. Three targeted service probes passed, confirming the split/insert rejection, distant collision fallback, and correct overnight resolver identity.

Final results:

| Run | Result |
| --- | --- |
| Scheduling, Events, sequences, harmonization, and refresh services | 64 passed |
| Existing scheduler browser workflows | 3 passed |
| Automation, playlists, traffic, and public player/schedule services | 42 passed; one existing SQLAlchemy fixture warning |
| Isolated Liquidsoap mode-switch proof | 1 passed |
| 100,000-song source-search benchmark | 1 passed |
| Targeted audit probes | 1 browser probe and 3 service probes passed; JavaScript probes also reproduced cancellation mutation and ignored horizontal movement |

Total: 111 existing tests passed, plus four targeted audit probes. The targeted probes confirm defects or a specific invariant; they do not mean those defects are fixed. Initial sandbox socket failures were resolved by rerunning the browser and engine tests with local socket access. No product assertion failed in the completed existing-suite runs.

Machine-readable observations and counts are retained in [the audit evidence](audits/2026-09-17-scheduling.json). JUnit/log files for these runs are under `/tmp/freo-scheduling-*`. No claim of exhaustive coverage follows from the passing baseline: the reproduced editor defects were absent from those tests.
