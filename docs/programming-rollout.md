# Programming rollout and verification

This change includes application/UI code, migration `d72e1f90a631`, and a managed Liquidsoap program-queue update. Editing the repository does not activate an already running station engine.

## Review and deployment order

1. Review the additive migration, authenticated scheduling redirects, and fixed queue insert command. Preserve an ordinary database backup and prior rendered station configurations using the existing deployment process.
2. Apply `flask --app wsgi db upgrade` in the installation environment. Existing event weekdays and weekly assignments keep their behavior; the new fields are nullable. Do not convert station baselines as part of deployment.
3. Render the updated Liquidsoap configuration for each station using the existing station tooling. The new queue preserves all waiting/prefetched requests and implements `freo_queue.insert` for approved audio only. Check generated configurations with the installed Liquidsoap binary.
4. Activate the updated engine configuration in the station's agreed maintenance window, then restart the automation worker and reload the web application. The new worker requires the insert command. Do not run it against an older station runtime.
5. Verify station health, confirmed playback, admin navigation, default coverage, a recurring event, and a finalized commercial log. A queued event is not evidence of airplay; confirm its actual start.

The event operation never restarts station services. Runtime activation during deployment is a separate operation that can interrupt output.

## Fresh-VM validation plan

Provision a disposable installation using the repository's installation procedure and synthetic audio. Apply the full migration chain on PostgreSQL, downgrade to `c39fa204bb17`, then re-upgrade. Verify old single-day events still resolve and new multi-day events retain one identity. Test baseline conversion/restoration, including Sunday wrap and a DST timezone, before creating any station content on the real installation.

Run the non-browser suite and the browser suite. Run `FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_deck_engine.py` against temporary runtime/storage. Confirm that a song completes, an inserted event starts next, and both prefetched and waiting music follow in their original order. Verify AUTO/DJ transitions still work.

## Rollback

Restore original weekly assignments through Defaults before downgrading a station with active converted baseline blocks. Disable or explicitly convert multi-day event series before schema downgrade; the migration refuses to discard active multi-day behavior. Stop the new worker before restoring an older engine template. Restore matching application and engine versions together and verify actual playback. Airplay history is retained.

## Known boundaries

- Baseline conversion verifies 370 days and aborts if coverage or clock occurrence identity differs. Baseline timing edits currently require restoring assignments first.
- Calendar previews show rule-based coverage and event targets. They do not forecast exact music choices, fit songs to the hour, or guarantee exact-time joins.
- Program changes and event insertion protect queued manual content and active sequences. Manual/DJ ownership can make events late or missed.
- The browser's default late allowance is five minutes; existing saved definitions and CLI defaults are preserved.
