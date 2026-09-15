# Timed events (Phase 11)

Timed events answer “what must happen at or near this instant?” They are separate from weekly schedule assignments, which choose the active programming clock. An event never advances clock or rotation cursors; normal programming continues afterward.

Definitions support exact approved Tracks and ImagingAssets. `ONE_TIME` stores canonical UTC converted from a station-local form. `WEEKLY` stores weekday plus local wall time and creates a bounded eight-day horizon of durable, unique occurrences. Weekly conversion uses the station IANA timezone. A spring-gap time shifts forward by the DST gap while preserving its minute/second (02:30 becomes 03:30); a repeated fall hour uses fold zero and fires once. OS clock synchronization is an operational prerequisite.

Timing modes are explicit:

- **HARD** aims for the target and may issue the fixed worker-only `flush_and_skip` operation when policy is `MUSIC_ONLY` and current audio is automated music. Fallback is also replaceable. Imaging, manual content, and another event are protected.
- **SOFT** suppresses normal lookahead during the last 20 seconds, then queues after current content without cutting it.
- **NON_INTERRUPTING** does not trigger pre-target queue drain and waits for the current request path to clear. It never cuts audio.

Each occurrence has an early preparation point, target, and explicit late deadline. `SKIP` marks an occurrence missed after its deadline; `PLAY_LATE` permits attempts through the configured late window. Both remain bounded. Content is verified through station-scoped private storage up to 60 seconds ahead. Missing, disabled, rejected, decommissioned, or cross-station content fails safely. Same-time events sort by priority descending and stable occurrence ID; only one event owns the queue at a time. Collision and duration warnings are advisory.

The worker order is playback reconciliation, manual intent, timed-event preparation/execution, then normal refill. Timed events stay active while automation is held. Manual content remains protected, so an event may become late or missed. The append-only Liquidsoap queue prevents safe arbitrary front insertion; the worker drains lookahead and a permitted HARD event clears stale automatic lookahead at its target. This may briefly expose generated fallback, but never restarts Liquidsoap or Icecast.

An occurrence is `STARTED` only from Liquidsoap’s confirmed `on_track` event. Timing offset is confirmed start minus scheduled UTC time. Completion is not fabricated because the current integration has no authoritative completion signal. A timed Track start affects future track/artist separation; timed imaging affects imaging recurrence. Worker restart uses durable occurrence state and uniqueness. A queued request invalidated by a Liquidsoap restart becomes failed during normal reconciliation.

Use Admin → Events for definitions, validation warnings, upcoming occurrences, and execution results. Live Assist shows the next event with a browser-only countdown; server UTC controls execution. Recovery CLI includes `flask event list`, `show`, `create`, `enable`, `disable`, `validate`, `occurrences`, and `preview`. No filesystem path, public mutation API, external stream, stopset, time-fit music, fade-to-time, or frame-accurate promise is provided.
