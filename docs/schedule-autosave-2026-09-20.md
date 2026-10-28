# Schedule synchronization and calendar autosave — September 20, 2026

The editor previously treated every station schedule revision change as an external conflict. The playback worker increments that revision when it acknowledges a mode switch, and saving a default playlist or a different scheduling mode also advances it. The browser retained its old revision and Simple selection, so subsequent legitimate saves reported that another session had changed the schedule.

The calendar now saves completed edits automatically, including moves, resizing, removals, Undo, and Redo. Its Save button is removed. Saves are serialized, preserve edits made while a request is pending, and finish before workspace navigation or mode activation. Temporary network/server failures and pending mode handoffs retry automatically. Unsaved changes remain recoverable from browser storage; a failed save is never labeled Saved.

Idle workspaces refresh their saved state. Simple, calendar, Block assignments, and default playlist saves compare the relevant saved content instead of rejecting unrelated station revision changes. Independent calendar edits merge under the station transaction lock. Competing edits to the same item return a conflict and preserve local changes, with explicit choices to load the saved version or keep the local edits. Existing clients retain revision protection. Source authorization, recurrence validation, overlap checks, and atomic Block saves remain enforced.

Shows, Blocks, and Simple retain their explicit Save controls. Mode activation remains an explicit playback action. No database migration is required.

## Validation

- Scheduling service/API/editor regression suite: 45 passed. Includes stale Simple/default saves, retries after a committed response is lost, independent item merges, same-item conflicts, overlap/source validation, and pending handoffs.
- Disposable PostgreSQL concurrency suite: 4 passed, including simultaneous independent autosaves and competing same-item writes.
- JavaScript editor suite and syntax checks passed; `git diff --check` passed.
- Browser recovery suite: 3 passed, covering temporary server failure, a lost response after commit, navigation during a pending save, conflict resolution, and saving Simple again after the worker advances the mode revision.
- Broader scheduling browser run: 9 passed, with one intercepted test click beneath the fixed playback toolbar. The test now scrolls the target into view using the existing click helper; its scheduling persistence assertions had passed before that click.
- Final browser rerun: 4 passed, covering both recovery scenarios, default playlist saving after a revision change, Block assignments, full-day calendar autosave, and the corrected recurring pointer workflow. All 12 distinct affected browser scenarios passed across these runs.
- Installation validation passed against the running server. Production data was not used for test fixtures.

Logs: `/tmp/freo-autosave-services-final.log`, `/tmp/freo-autosave-postgres.log`, `/tmp/freo-autosave-recovery.log`, `/tmp/freo-autosave-browser.log`, `/tmp/freo-autosave-browser-final.log`, `/tmp/freo-autosave-install-check.log`.
