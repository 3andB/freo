# Integrated scheduling

The calendar chooses dated programs first, then bounded weekly programs, then the weekly baseline. An uncovered interval uses the station default clock, then the active rotation. Events overlay this music selection and do not consume music slots.

Every station has a canonical IANA timezone (`UTC` initially; set explicitly for each station). Absolute selection and playback timestamps remain UTC. Weekly assignments contain a weekday (Monday=0) and station-local `HH:MM` wall time. An assignment remains active until the next enabled assignment, including across midnight and the Sunday-to-Monday wrap. Disabled assignments or clocks are ignored. With no usable assignment, Freo uses an optional default clock, then the Phase 5 active rotation, then Liquidsoap's generated fallback if nothing can be selected.

Weekly schedule assignments select the active clock; they do not represent exact-time playback. Phase 11 [timed events](timed-events.md) overlay specific approved content at or near a target without changing the active clock.

At spring-forward, a skipped local assignment shifts forward by the gap while preserving its minutes (02:30 becomes 03:30). At fall-back, an assignment in the repeated hour activates on its first occurrence and remains active through the second copy of that hour until a later assignment; it does not activate twice. Occurrence identity uses assignment ID plus effective local date. A worker restart within an occurrence resumes its cursor; the next weekly occurrence resets. Server UTC clock accuracy is an operating-system prerequisite.

```sh
flask --app wsgi schedule timezone --station freo-demo America/Denver
flask --app wsgi schedule assign --station freo-demo --day monday --time 06:00 --clock morning
flask --app wsgi schedule list --station freo-demo
flask --app wsgi schedule resolve --station freo-demo --at 2026-09-14T12:30:00Z
flask --app wsgi schedule preview --station freo-demo --from 2026-09-14T00:00:00Z --hours 24
flask --app wsgi schedule status --station freo-demo
```

The worker checks programming each two-second poll. On a program change it may clear stale automatic lookahead, but only when every future request is known automatic content; queued events and manual content remain protected. It stops adding old-clock requests during the final 20 seconds before a known transition; already queued requests may finish. Thus the transition can lag by at most the small preexisting queue plus the currently playing track. It never restarts Liquidsoap, cuts the current track, or guarantees an exact top-of-hour join. Actual playback history carries clock, clock slot, assignment, and occurrence IDs. Public `/api/stations/<slug>/schedule` and `/schedule/current` are read-only; assignments and timezone can be edited by authenticated admins with CSRF-protected forms or by root-run CLI. Dated calendar programs provide overrides. Timed events and commercial sequences are supported separately; duration-fitting music and backtiming remain future work.

Browser programming controls are documented in [programming UI](programming-ui.md). The root CLI remains available for recovery.


## Baseline conversion and station defaults

Defaults has one station fallback picker and a reviewed baseline conversion. Conversion splits the weekly start-to-next-start intervals into calendar baseline blocks, including overnight and Sunday wrap. These blocks remain below scheduled shows. Their original assignment IDs and effective occurrence dates preserve clock progress across midnight. The application verifies 370 days of resolved coverage and occurrence identity before committing; ambiguous DST conversions are rejected instead of changing playback silently. Original assignments can be restored. Restore before editing their times.

See [programming UI](programming-ui.md) for the unified workflow. Calendar coverage displays the actual resolver source instead of treating a baseline-filled interval as silence.
