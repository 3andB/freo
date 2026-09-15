# Programming workspace

Programming is ordered Music, Categories, Sound Room, Imaging, then an expandable Scheduling subgroup. Scheduling contains Calendar, Events, Templates, Commercials, and Defaults. Templates groups show templates (clocks), music patterns (rotations), and sequences (event blocks). Existing resource URLs remain valid.

The calendar shows bounded weekly programs and dated overrides, plus effective baseline/default coverage. Day, Week, and Agenda share a read-only forecast. Events are projected from definitions even beyond the worker's materialized occurrence horizon; actual execution results replace projected labels when available. Finalized commercial breaks link to their commercial log. Preview reports missing event audio, empty music categories, and possible event collisions. Times are targets, not duration-fitted playback promises.

A program can select a category, music pattern, or show template. A category or pattern gets a supporting clock automatically. Programs repeat their selection until their end; current audio finishes. Dated programs override recurring programs. Equal start/end means 24 hours; an earlier end continues into the next day.

Events accept songs, approved imaging, or sequences. Weekly events have a multi-day picker with one stable series identity. Editing the series updates its future occurrences and preserves past starts. New browser events default to SOFT (After the current song), zero early allowance, and a five-minute late allowance. Advanced timing remains available. Finalized commercial events cannot be changed through generic event forms or services.

Defaults provides one picker for a category, pattern, or show template. Existing weekly baseline assignments remain active until explicitly converted. The conversion preview lists daily calendar baseline blocks; application compares 370 days of coverage and occurrence keys, aborting on differences. Original assignments are disabled in the same transaction, retained for restoration, and protected from editing while converted. Midnight splits retain the original occurrence key. Restore the assignments before changing converted baseline times. The conversion does not eliminate original identities or rewrite airplay history.

Programming mutations require authenticated station-scoped access and CSRF. Existing CLI services remain recovery tools. Category membership, template slot reordering, previews, and audit recording continue to use shared services. Preview never changes queues or clock cursors.

Runtime and rollout details are in [scheduling](scheduling.md) and [timed events](timed-events.md). The implementation plan is [programming harmonization](programming-harmonization-plan.md).
