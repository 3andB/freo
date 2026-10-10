# Timed events (Phase 11)

Timed events answer “what must happen at or near this instant?” They are separate from weekly schedule assignments, which choose the active programming clock. An event never advances clock or rotation cursors; normal programming continues afterward.

Definitions support exact approved Tracks and ImagingAssets. `ONE_TIME` stores canonical UTC converted from a station-local form. `WEEKLY` stores one or more weekdays plus local wall time under one event identity and creates a bounded eight-day horizon of durable, unique occurrences. Weekly conversion uses the station IANA timezone. A spring-gap time shifts forward by the DST gap while preserving its minute/second (02:30 becomes 03:30); a repeated fall hour uses fold zero and fires once. OS clock synchronization is an operational prerequisite.

Timing modes are explicit:

- **HARD** aims for the target and may issue the fixed worker-only `flush_and_skip` operation when policy is `MUSIC_ONLY` and current audio is automated music. Fallback is also replaceable. Imaging, manual content, and another event are protected.
- **SOFT** inserts approved event audio ahead of automatic lookahead at the target (or its explicitly configured early allowance). The current song finishes and queued music retains its order. Unknown, manual, and event requests in the queue prevent displacement. New browser events allow five minutes of lateness; existing definitions retain their saved allowances.
- **NON_INTERRUPTING** does not trigger pre-target queue drain and waits for the current request path to clear. It never cuts audio.

Each occurrence has an early preparation point, target, and explicit late deadline. `SKIP` marks an occurrence missed after its deadline; `PLAY_LATE` permits attempts through the configured late window. Both remain bounded. Content is verified through station-scoped private storage up to 60 seconds ahead. Missing, disabled, rejected, decommissioned, or cross-station content fails safely. Same-time events sort by priority descending and stable occurrence ID; only one event owns the queue at a time. Collision and duration warnings are advisory.

The worker order is playback reconciliation, manual intent, timed-event preparation/execution, then normal refill. Timed events stay active while automation is held. Manual content remains protected, so an event may become late or missed. The managed program queue exposes a fixed, allowlisted insert operation for SOFT events and their sequence items. It preserves both prefetched and waiting music without advancing selection cursors. Program transitions clear future music only when every queued request is known automatic content. HARD events still use their explicit interruption policy. Normal SOFT execution does not drain the queue before the target or restart station services. Engine polling and transitions still impose practical timing limits.

An occurrence is `STARTED` only from Liquidsoap’s confirmed `on_track` event. Timing offset is confirmed start minus scheduled UTC time. Completion is not fabricated because the current integration has no authoritative completion signal. A timed Track start affects future track/artist separation; timed imaging affects imaging recurrence. Worker restart uses durable occurrence state and uniqueness. A queued request invalidated by a Liquidsoap restart becomes failed during normal reconciliation.

Use Programming → Scheduling → Events for definitions, validation warnings, upcoming occurrences, and execution results. Live Assist shows the next event with a browser-only countdown; server UTC controls execution. Recovery CLI includes `flask event list`, `show`, `create`, `enable`, `disable`, `validate`, `occurrences`, and `preview`. No filesystem path, public mutation API, external stream, stopset, time-fit music, fade-to-time, or frame-accurate promise is provided.

## Block content

An event may target an enabled validated EventBlock. Its timing mode, tolerance, priority, and missed policy govern the confirmed start of item one. Internal failures then follow the block and item failure policies.


## Runtime compatibility

The SOFT insertion path requires the updated managed Liquidsoap template, as well as migration `d72e1f90a631` for multi-day recurrence and baseline conversion. Render and activate the updated station configuration before enabling the new worker. Run the isolated engine proof before rollout; changing the runtime configuration is a deployment operation, separate from editing schedules.

The calendar forecast is read-only and works for distant weeks without creating durable occurrences. Actual starts and offsets remain authoritative. A recovered queued submission is reused instead of pushed again. Finalized traffic events link to the commercial log and are locked against generic edits.
