# Scheduling repairs and repeatable verification

The [September 19 scheduling and DJ Booth audit](scheduling-booth-audit-2026-09-19.md)
records the subsequent integration repairs and verification. Those repairs include
a Liquidsoap template change and require coordinated application, worker and engine
activation; the deployment notes below describe the earlier September 17 change.

The September 17 audit is in [scheduling-audit-2026-09-17.md](scheduling-audit-2026-09-17.md). This change addresses its twelve findings: canonical overnight editing, atomic edit proposals and cancellation, recurrence phase and exceptions, insert transformations, stale-save protection, save-in-progress tracking, responsive timeline bounds, drag coordinates, complete recurrence collision validation, atomic Block saves, Event visibility, and bounded transition recovery.

The editor keeps its loaded document revision separate from live status polling. A stale page or recovered draft cannot silently adopt a newer revision and overwrite it. Changes made while a save is pending remain unsaved, and double submission is disabled. Blocks save composition and assignments in one transaction; assigned revisions remain pinned and are displayed explicitly. Apply to future uses remains an explicit action.

Timeline bars retain their actual time bounds. Drag feedback uses a fixed-height status area so it cannot push the timeline away from the pointer. Event refreshes defer timeline redraws until a drag ends. Short sections have readable buttons below the timeline for exact editing. Cross-day dragging preserves the canonical interval; handles appear only at real endpoints, not at midnight clipping boundaries. Splitting a calendar occurrence can create a separate next-day tail. A recurring series whose split would require a new next-day recurrence currently asks the operator to choose **This occurrence**, preserving the original data rather than generating an incorrect monthly or multi-week rule.

Following-series edits use a lower date bound (`starts_on`) while retaining the phase anchor. Collision validation uses modular daily/weekly recurrences and monthly occurrence enumeration across the supported date domain, with a wall-time interval sweep to avoid comparing non-overlapping sections. Dated overrides retain their higher priority.

Pending switches expire after 30 seconds; prepared/fading switches have a 120-second acknowledgement deadline. Late recovery reads the engine's existing token instead of issuing a new switch. If the engine's actual result cannot be confirmed, the transition fails visibly and automation filling is held. The operator can confirm a mode from Station Control to resume. Playback starts are never invented, and an already confirmed matching engine token can still reconcile successfully.

Deploy the web application, static files, and automation worker together. No database migration or Liquidsoap template change is needed. Older workers do not understand the new following-series lower bound, so a rollback must also review/revert definitions created with that bound.

## Routine regression suite

From the repository root:

```sh
venv/bin/pytest -q tests/test_schedule_editor.py tests/test_schedule_regressions.py tests/test_schedule.py tests/test_visual_schedule.py tests/test_timed_events.py tests/test_event_blocks.py tests/test_programming_harmonization.py tests/test_programming_refresh.py tests/test_automation.py tests/test_playlists.py tests/test_traffic.py tests/test_player_experience.py
venv/bin/pytest -q tests/test_schedule_editor_browser.py tests/test_schedule_studio_browser.py
FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_schedule_engine.py
venv/bin/pytest -q tests/test_schedule_booth_integration.py
FREO_ENV_FILE=/dev/null FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_schedule_booth_engine.py --basetemp=/tmp/freo-mixed
FREO_SCHEDULE_SCALE=1 venv/bin/pytest -q -s tests/test_schedule_scale.py
bash scripts/test-scheduling-postgres.sh
```

The pure editor suite uses Node.js and includes 2,000 seeded interval/insert cases. Service regressions compare the recurrence solver with a day-by-day reference across 250 generated rule pairs, plus 200 generated overnight documents. Browser tests use Chromium/Selenium and local sockets; engine tests require ffmpeg and Liquidsoap. The PostgreSQL runner creates a separate cluster under `/tmp`, tests concurrent saves and transaction rollback, then removes that cluster. It never reads the installation database credentials.

Use the service/pure suite for each change, browser coverage for scheduler changes, and the database/engine/scale suites before release. Add `--junitxml=/tmp/<run-name>.xml` to retain CI results. Local socket tests require an environment that permits local sockets.

## Continuous playback

```sh
FREO_SCHEDULE_SOAK_SECONDS=65 venv/bin/pytest -q tests/test_schedule_soak.py --basetemp=/tmp/freo-scheduling-soak-smoke
FREO_SCHEDULE_SOAK_SECONDS=172800 venv/bin/pytest -q tests/test_schedule_soak.py --basetemp=/tmp/freo-scheduling-soak-48h
```

Use a fresh `--basetemp` directory: pytest clears an existing directory at startup. This fixture creates isolated database/media/runtime paths, runs a dedicated Liquidsoap process, and discards output audio. It exercises all six directed mode changes, actual-start acknowledgement, idempotent transition retries, worker queue refill, sustained-silence detection, and repeated song starts. Metrics persist to `test_continuous_scheduling_soa0/soak-result.json` inside the base directory; engine logs sit beside them. The engine is stopped when the test ends.

A 65-second run completed seven switches, recorded twenty started decisions, collected 129 steady-state samples, and measured a maximum switch time of about 3.1 seconds. This is a short continuous-playback proof, not a completed 48-hour soak. It uses one controlled tone track; it does not establish full-library throughput, audio quality across codecs, or all Event/DJ takeover fault combinations.

The 100,000-song SQLite benchmark returned bounded 40-row responses with 9.0ms median / 11.4ms p95 in the final measured run. The 1,000-definition calendar validated in 2.67 seconds, with resolver median 12.0ms / p95 20.8ms. These are local measurements, not PostgreSQL production latency guarantees. Further performance work should batch repeated source validation for large saved documents.

## Applied verification

The web application and automation worker were restarted onto this update on September 17, 2026. No mode switch was pending. Web health, database readiness, automation heartbeat, Icecast, playout, and stream checks all returned HTTP 200 with `status: ok`. Liquidsoap and Icecast were not restarted. A pre-change source archive is retained at `/tmp/freo-before-scheduling-fixes-20260917.tgz`.

Across the final verification runs, 136 distinct pytest cases passed: 122 service/pure-editor cases, eight browser cases, two PostgreSQL cases, one installed-engine proof, two scale cases, and one continuous-playback case. The pure-editor wrapper also runs its seeded JavaScript assertions. An existing playlist fixture emits one SQLAlchemy warning. Early failures from fixture cleanup, socket/startup limits, and test setup were resolved and the affected checks rerun; the permanent tests assert repaired behavior.

[Machine-readable repair evidence](audits/2026-09-17-scheduling-repairs.json) records artifacts, source hashes, health checks, and counts. The 48-hour soak and broader mixed-media/Event/DJ fault soak remain uncompleted acceptance work, not claimed passing results.

## Final repository integration — September 18

Before committing the remaining scheduling work alongside the deployed importer, all recorded scheduling source hashes matched the tested September 17 repair evidence. A fresh focused run passed 22 service/editor/browser cases, and the disposable PostgreSQL run passed both concurrency cases. The older workspace calendar test now clicks the readable short-entry edit button rather than the geometrically accurate, tiny timeline bar; its editing and mobile layout assertions pass. JavaScript syntax and diff whitespace checks passed. No scheduling switch was pending before the application restart. Logs: `/tmp/freo-final-scheduling-checks.log` and `/tmp/freo-final-scheduling-postgres.log`.
