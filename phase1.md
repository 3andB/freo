# Freo V1 — Phase 1 completion and testing report

Review date: 4 October 2026 (UTC). Workspace: `/opt/freo-v1`. Branch: `develop/v1`.

## Completion assessment

Phase 1 implements all five requested capabilities through Freo’s existing scheduler, selection decisions, playback acknowledgements, and cursor machinery. No parallel scheduler or replacement playback architecture was introduced.

This report covers the complete Phase 1 implementation and the fixes made during this review. **Phase 1 is complete for development review within the behavior boundaries below.** The final verification runs passed 256 distinct test cases, with no unresolved functional failures in the tested scope. Production deployment and release approval remain outside this review.

## Safety and scope

- The working directory and branch were verified before review changes.
- `/opt/freo` was clean and at commit `32495f607711a432c08973abeaf979973c9ee2ad` before and after the review. The final working directory and branch remained `/opt/freo-v1` and `develop/v1`.
- Production 0.3.2, `main`, production tags, and release artifacts were not edited. No production migration, service restart, publishing, or deployment was performed.
- The pre-existing untracked `V1_AUDIT.md` was left intact.
- Tests used temporary SQLite databases, browser profiles, generated audio, and private runtime directories under `/tmp`. PostgreSQL tests used a new disposable PostgreSQL 16 cluster, with TCP disabled and a private Unix socket; the runner stopped it afterward. Liquidsoap tests used private sockets and local WAV output, not an Icecast broadcast.
- The installed Python interpreter at `/opt/freo/venv/bin/python` was used read-only with `PYTHONDONTWRITEBYTECODE=1`; dependencies and production code were not changed.

## Feature completion

| Requested capability | Implemented behavior | Verification |
|---|---|---|
| Playlist leader | Optional available MUSIC or station-owned STATION track. One leader per existing occurrence/activation, followed by normal membership. Leader decisions do not consume member positions. | Straight and Random modes; new occurrences; visual activations; restart; pending/confirmed state; failed submission; queue refresh; unavailable/deleted leaders; station isolation; real Liquidsoap playback. |
| Artist separation | Station setting from 0–86400 seconds. Case/whitespace-normalized artist names, using confirmed-start history and provisional queue holds. Empty artist names do not group unrelated tracks. | Category/rotation, ordinary playlist, visual playlist, boundary/fallback tests, history beyond 500 decisions, and blank artists. |
| Track separation | Same station-wide configuration and history policy for individual tracks. | Confirmed start time rather than selection time; pending/submitting holds; exact window boundary; failed decisions; station isolation; small-library fallback. |
| Weighted categories/tags | Positive weights up to 100 for Random playlist selection. Matching weights add; unmatched songs have weight 1. Separation and shuffle-cycle eligibility apply first. | API validation, category/tag combination, seeded probability sampling, once-per-cycle behavior, unconfigured defaults, and browser persistence. |
| Dynamic smart playlists | Current MUSIC membership from metadata filters: artist, title, album, genre, BPM, release year, duration, tags, and categories. Filters combine with AND; selected values within a tag/category filter combine with OR. | Every supported filter; combined filters; inclusive bounds; literal `%`/`_` handling; live metadata changes; sharing and station isolation; disabled audio; PostgreSQL queries; editor and search counts. |

Editor controls, CSRF/programming permissions, playlist revision checks, audits, source search, event duration estimates, deletion cleanup, programming signatures, and preview integration are included. Static membership is retained when dynamic mode is turned off.

### Behavior boundaries to review

1. **Weights favor selection order within a shuffle cycle.** They do not establish a long-term category/tag airplay ratio: every eligible song still plays once per cycle. Straight mode ignores weights.
2. **Separation is best effort.** If the current eligible pool cannot satisfy both windows, artist separation relaxes first, then track separation. The decision records `none`, `artist`, or `track`. Existing shuffle-cycle rules remain authoritative.
3. **Leaders are occurrence-based.** Shuffle rollover, worker restart, or stop/resume within the same occurrence does not create another leader. An unavailable leader records `playlist_leader_unavailable`; normal selection continues. Re-enabling that leader applies to a later occurrence.
4. **Explicit playback order remains authoritative.** Manual cue choices, leaders, fixed event items, and Straight ALL event sequences are not rearranged by music separation. Timed-event ONE and shuffled playlist selection use the shared policy. STATION/COMMERCIALS audio do not acquire music separation.
5. **Timed-event membership is a snapshot.** Dynamic rules resolve when the existing finite event execution is created. Library changes affect subsequent executions; they do not rewrite an already queued event.
6. **The rule set is deliberately small.** No nested Boolean expressions, scripting, BPM progression, or generalized rule engine was added. A missing numeric metadata value does not satisfy a numeric bound.

## Findings corrected during this review

| Finding | Impact before correction | Correction and evidence |
|---|---|---|
| Untracked leader after select/push/commit crash — high | A saved `selected`/`submitting` leader could wait indefinitely after worker restart. A lost queue acknowledgement could also allow a duplicate retry. | Existing request reconciliation now recovers accepted requests by decision annotations. It retries a missing untracked leader only after a ten-second confirmation window with complete inventory. It never invents a confirmed start. Five parameterized cases failed before the fix; the recovery and incomplete-inventory cases now pass. |
| Pending-leader polling — medium | The normal two-second worker interval could unnecessarily delay member selection after a short leader. | Pending leaders use the existing 250 ms cadence. The cadence regression failed before the fix; actual 0.8-second and 3-second leader playback was tested. |
| Partial visual checkpoint restoration — high | Refreshing a directly selected visual leader could raise `KeyError: 'rotation'`, because its checkpoint contains visual state only. | Restore now changes only cursor families present in the checkpoint. A reproduced failure is covered by a regression asserting that unrelated clock/playlist progress survives. |
| Deleted smart filter disappearing from the editor — medium | A missing tag/category option could be silently omitted when saving an unrelated change, broadening the playlist. | Unavailable saved filters/weights remain visible. Saving requires explicit removal or a valid replacement. Browser coverage verifies that an unrelated save preserves the rule and reports validation failure. |
| Empty dynamic-playlist message — low | The editor suggested adding music even though dynamic membership disables manual additions. | It now explains that no songs match and directs the operator to edit the filters. |

The fixes extend existing reconciliation, worker cadence, checkpoint restoration, and editor behavior. They do not introduce another scheduling loop.

## Test results

| Final verification run | Result | Duration |
|---|---|---|
| Phase 1 and broader backend regression suites | 238 passed, 1 skipped | 489.74 seconds |
| Final checkpoint-fix regression: review, programming refresh, visual scheduling, and schedule/Booth integration | 76 passed | 269.69 seconds |
| Browser workflows | 4 passed | 165.01 seconds |
| Disposable PostgreSQL 16: Phase 1, existing schedules/events, and deletion | 11 passed | 75.48 seconds |
| Real Liquidsoap playback: 0.8-second and 3-second leaders | 2 passed | 49.94 seconds |
| Python syntax, JavaScript syntax, whitespace checks | Passed: 134 Python files, `node --check`, `git diff --check` | — |

Across these final runs, **256 distinct test cases passed**. The runs overlap: 331 successful executions are not 331 distinct tests. The sole backend skip was `test_delete_all_references_postgres`; it passed in the separate PostgreSQL run, so every test case collected across these runs has a successful execution. The final checkpoint fix was verified by the 76-test follow-up run after the broader backend process had started.

There were no failures or errors in these final runs. Backend warnings comprised an existing SQLAlchemy fixture warning and Flask-SQLAlchemy migration API deprecation warnings; PostgreSQL also reported that migration API deprecation. The existing 370-day calendar regression exceeded the 90-second diagnostic threshold in both backend runs and emitted stack traces, then completed successfully. This is recorded as a test-performance observation, not a test failure.

The production Git tree remained clean at the original commit. `V1_AUDIT.md` retained SHA-256 `102b20f89c1fdf73afdeae99fb79f6e8630756e541f759468fd2df1fa5210bab`. No production deployment or migration was performed.

### Coverage and evidence

- `tests/test_phase1_scheduling.py`: the original Phase 1 regression suite, including migration defaults, leaders, separation, weights, dynamic membership, station scope, CSRF, snapshots, preview, deletion, and refresh.
- `tests/test_phase1_review.py`: crash windows, incomplete inventory, pending-leader cadence, every smart filter, long history, weighted behavior, and partial checkpoint restoration.
- `tests/test_phase1_postgres.py`: full migration chain, Phase 1 upgrade/downgrade preservation, leader foreign-key behavior, concurrent selector serialization, and PostgreSQL dynamic filters.
- `tests/test_phase1_engine.py`: installed Liquidsoap playback using generated tones; real START ordering, audible output, short leaders, and worker event-reader restart without duplicate leaders.
- `tests/test_playlists_browser.py`: existing membership/Undo/reorder/scheduling workflows plus smart configuration, separation, mobile width, and deleted-filter handling.
- Existing scheduling, automation, imaging, event, queue-refresh, music-deletion, Sound Room, and catalog suites were included in the broader regression run.

Machine-readable JUnit results and logs are retained for this review at `/tmp/freo-phase1-review/` (`backend`, `refresh`, `browser`, `postgres`, and `engine`, with `.xml` and/or `.log` extensions). These temporary evidence files are not release artifacts. The initial failure reproductions are separate from final passing runs.

### Reproduction

Use a disposable environment and the repository’s declared test dependencies. The review used the following environment for backend/browser tests:

```sh
PYTHONDONTWRITEBYTECODE=1 FREO_ENV_FILE=/dev/null DATABASE_URL=sqlite:// \
  /opt/freo/venv/bin/python -m pytest -q --tb=short \
  tests/test_phase1_review.py tests/test_phase1_scheduling.py \
  tests/test_playlists.py tests/test_automation.py tests/test_visual_schedule.py \
  tests/test_schedule.py tests/test_schedule_regressions.py \
  tests/test_schedule_booth_integration.py tests/test_event_completion.py \
  tests/test_event_blocks.py tests/test_timed_events.py tests/test_station_events.py \
  tests/test_programming_refresh.py tests/test_imaging.py tests/test_music_delete.py \
  tests/test_sound_room.py tests/test_music_catalog.py
```

Run `tests/test_playlists_browser.py` separately with Chromium/ChromeDriver and localhost sockets available. For real audio, set `FREO_ENGINE_TEST=1` and run `tests/test_phase1_engine.py` with Liquidsoap and FFmpeg installed. For PostgreSQL, point `FREO_TEST_POSTGRES_URL` exclusively at a disposable cluster and run `tests/test_phase1_postgres.py`, `tests/test_schedule_postgres.py`, `tests/test_events_postgres.py`, and `tests/test_music_delete.py::test_delete_all_references_postgres`. The existing PostgreSQL fixtures isolate test databases or schemas.

## Migration and deployment status

Migration `f106a1b2c3d4` follows `c83d4e5f9012`. It adds the optional leader reference, disabled-by-default dynamic configuration, empty rules/weights, and the indexed leader occurrence key on selection decisions. Existing playlist membership, revisions, and confirmed history are preserved. PostgreSQL upgrade, downgrade, re-upgrade, and `ON DELETE SET NULL` behavior were tested.

Downgrading removes Phase 1 configuration; it is not a backup of that configuration. The migration has **not** been applied to production. Application code and schema must be deployed together through a separately approved release process.

## Remaining limits and review decision

- Tests cover deterministic service behavior, browser workflows, real PostgreSQL, and isolated generated-tone playback. They do not substitute for a sustained broadcast soak with the station’s actual catalog, media formats, event mix, and operating conditions.
- No production data migration, production listener test, release packaging, or deployment was attempted.
- Large-catalog throughput and long-running performance have not been certified by this review. The first implementation evaluates live candidates and returns editor/catalog data without a new large-library pagination architecture.
- The review should explicitly accept the weighted-order, best-effort separation, leader fallback, and finite-event snapshot semantics above.

**Decision: Phase 1 is implemented, tested, and ready for review on `develop/v1`.** Five review findings were corrected and verified. No unresolved Phase 1 functional defect was found within the exercised scope. The remaining work before production release is operational validation and acceptance of the documented behavior boundaries, rather than a missing Phase 1 feature.

## Publication follow-up

The owner subsequently authorized committing, pushing, and deploying Phase 1. The implementation, review fixes, tests, and this report are included in the Phase 1 commit on `develop/v1`. The pre-existing `V1_AUDIT.md` remains outside that commit. No separate V1 runtime configuration or service was found on this host: the installed Freo services reference `/opt/freo/current` and production configuration. Deployment therefore awaits identification of a separate V1 target; the production freeze remains in force.
