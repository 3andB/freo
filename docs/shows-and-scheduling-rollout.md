# Shows and scheduling: implementation and rollout

The source implementation is complete for the requested Calendar, Blocks, and Simple workflows. This change has not been deployed to live stations. The database and managed Liquidsoap configurations must be updated together before operators activate the new scheduler.

## Operator workflow

1. In Station settings, choose the default playlist. It supplies music whenever the active mode has an empty interval or unavailable source.
2. Open Schedule. Calendar, Blocks, and Simple identify the active mode; browsing another workspace does not activate it.
3. Build Shows using the timeline on the left and searchable sources on the right. Set 15 minutes through 24 hours using the duration slider or exact value. Expand individual hours using the overview, drag sources into place, and pull section edges to change their duration. A song can also be inserted once within a collection section. Multiple artists can be combined by dropping another artist onto an artist section.
4. Calendar places Shows or sources on days and times. Use Day, Week, Month, or Agenda; recurring placements support daily, weekly, and monthly rules. Select an occurrence to edit one date, following dates, or the series. Save publishes the draft.
5. Blocks use the same editor with a fixed 24-hour duration. Save a Block, select Assign days, build an ordered pattern, and assign weekdays, a continuous daily rotation, or selected dates. Save the assignments. Unfilled time uses the default playlist.
6. Simple selects one Show or source and repeats continuously. Saving a different selection is a draft until Change what plays is confirmed.
7. Use the mode activation button and review the confirmation. Confirm & switch now requests a two-second outgoing fade. Active mode changes only after the engine reports the new audio started. Cancel leaves playback unchanged. A mode handoff also interrupts current live audio or Events; future Events remain scheduled.
8. Events handles IDs, announcements, commercials, songs, and sequences in every mode. Search approved content and audition audio before selection. Weekly Events can repeat at selected hours on selected days, with start/end dates.

Saved Shows have immutable revisions. Apply to future uses explicitly updates Calendar and Block references from the next local day, preserving current playback and Simple's active selection. Undo/redo and recoverable local drafts support timeline editing. Source lists return at most 40 results per page.

## Deployment order

Use the existing release procedure and a station maintenance window for engine restarts. No live restart or database migration was executed during implementation.

1. Back up the database, application release, and managed station configs. Record the current migration revision and running stations.
2. Stop/restart application and automation processes as coordinated by the release procedure. Apply `venv/bin/flask --app wsgi:app db upgrade` using the installation's configured environment. New head: `ab92e51c7034`; parent: `d18e42f6a905`. The migration adds scheduling tables, hourly Event fields, and a title/id search index. It does not activate stations or rewrite legacy programming.
3. Deploy the matching application, worker, static files, and Liquidsoap template. Render each managed station through the root-run `station render <slug>` CLI and restart its managed instance in the maintenance window. Rendering validates Liquidsoap before replacing its config. An old engine cannot execute the new scheduling handoff; the worker checks capability before queuing target audio.
4. Start the matching web and automation processes. Verify normal station health, audio, Event delivery, and active-mode status. Configure the default playlist, review the imported Calendar, save it, and explicitly confirm activation for each station.
5. Confirm on-air playback and selection history after switching. Check an unfilled Calendar interval, unassigned Block day, and unavailable Simple source against the default playlist.

Existing stations keep their legacy resolver until explicit activation. Legacy clocks are compatibility sources rather than implicitly converted timed Shows. Weekly baselines and bounded programs appear in Calendar, including Sunday wrap and overnight tails. Original clocks, assignments, commercial records, and their legacy endpoints remain for compatibility/history; they are removed from ordinary scheduling navigation. Operators should use the new workspace after activation.

Rollback restores a matching prior application/worker/engine release and database backup. The additive schema can remain while the old application is restored, but old code ignores the new modes: review the legacy schedule before returning it to air. A schema downgrade discards new compositions, assignments, transitions, and hourly Event configuration; do not use it as an automatic rollback on an active station.

## Verification and limits

- Isolated Liquidsoap proof confirms the fade before the outgoing 40-second song ends, actual-start acknowledgement, and idempotent retries.
- Service tests cover all six directed mode changes, exclusive mode resolution, default fallback, intentional single-song looping, immutable revisions, nested Shows, play-once inserts, recurrence, access control, stale edits, cursor restoration, and migration upgrade/downgrade.
- Browser tests exercise sidebar navigation, source selection, Show saving and mouse edge resizing, accordion control, confirmation/cancellation, Block weekday assignment, Settings default selection, full-day Calendar placement, Event series, and narrow-screen layout.
- A seeded SQLite catalog with 100,000 songs returned 40-row pages with 7.3 ms median / 8.6 ms p95 in the isolated benchmark. This measures source search, not complete playout throughput or production PostgreSQL latency.
- Legacy overnight coverage is compared across 370 dates. DST boundary tests cover spring and fall; music follows local wall time and wakes at UTC-offset changes. The timeline currently uses a local 24-hour ruler without separate visual lanes for repeated hours.

Production PostgreSQL migration/recovery, live station restarts, and an operator usability review remain rollout checks. The v1 editor uses individual section selection; bulk multi-selection and dedicated faceted tag/sort controls from the broader design are not included. Search includes song title, artist, album, and tags. Existing legacy clocks containing only imaging/sequences should retain compatibility playback until the operator configures a music source/default for activation.
