# Freo web surfaces

The homepage introduces what Freo currently does and states its early-stage installation status. `/stations` lists enabled managed stations, and `/player/<slug>` plays the real public HTTPS `/stream/<slug>` mount. The player labels metadata as the **last confirmed start**, because the most recent history row is not guaranteed to be the item still on air. It handles stream and metadata outages separately. Browser autoplay restrictions require a user gesture; audio begins only after the listener presses Play.

After sign-in, `/admin` is the operational overview. `/admin/stations` lists all managed stations, including stopped stations, and `/admin/stations/<slug>` opens a deeper station view with pending approved requests. The sidebar has authenticated Media management and editable Categories, Rotations, Clocks, and Schedule pages plus read-only History and System pages. The station picker keeps those pages station-scoped. The old `/dashboard/<slug>` URL redirects to the station detail page.

The overview renders confirmed playback starts, station-local programming and next transition, library totals, queue depth, worker heartbeat, station audio, and recent airplay. History counts only Liquidsoap-confirmed starts. A confirmed start is not proof the track remains on air, so the panel says **last confirmed start**. Pending requests may change before playback. The public HTTPS stream indicator reads a short audio chunk from the same-origin listener URL in the browser, then closes the connection; it refreshes once a minute. Other operational values use 5-second playback, 15-second runtime, and 45-second programming polls. Unknown observations are never presented as healthy. The Media page offers search, station filters, pagination, upload status, and track review. See [media library](media-library.md).

Bootstrap or rotate a dashboard account from `/opt/freo` with:

```sh
sudo ./venv/bin/flask --app wsgi:app admin set-password --email operator@example.com
```

The password is prompted twice without echo and stored as a Werkzeug scrypt hash in PostgreSQL. No account is seeded during public installation. Login has a CSRF token, session cookie with HttpOnly and SameSite=Lax, Secure on production HTTPS, a one-hour session lifetime, and a limited per-session failed-login delay. The failed-login delay is not a substitute for edge-level rate limiting. Active admin accounts may manage station-scoped media and programming through CSRF-protected forms; station lifecycle and automation enable/disable remain CLI-only. `flask admin list|enable|disable` are root-run account controls. Rotate a password previously shared in chat using the hidden `set-password` prompt.

The player has no chat, requests, votes, artwork, audience numbers, track progress, EQ, visualizer, or guaranteed upcoming-track panel. Those were design concepts and are intentionally absent. The dashboard does not simulate listener statistics, uptime, sponsor delivery, or backups. Fallback audio is labelled as not directly observed. The public site does not claim a supported one-command install until the separate Ubuntu 24.04 clean-VM acceptance test has passed, and Freo has no selected software license yet.

Programming editors use server-rendered forms and the shared CLI service functions; see [programming UI](programming-ui.md).

The authenticated **Imaging** section adds one-file upload, cart codes, type and group management, verification, enable/disable, and safe decommission. Clock editors distinguish CART and IMAGING_GROUP slots from music. The dashboard, confirmed history, and public player label imaging without inventing an artist or album. See [imaging](imaging.md).

The station **Live Assist** page is an operator surface for the observed Now/Next/Recent state, automation hold/resume, a bounded music search, and an imaging cart wall. Queue End and Skip are explicit controls with CSRF and server-side authorization. The page labels unavailable observation and possible fallback instead of presenting stale queue data as current. See [Live Assist](live-assist.md).

The authenticated **Events** section creates and edits exact Track or ImagingAsset events and shows schedule, timing mode, validation warnings, and occurrence results. Live Assist shows the next event and countdown. Weekly and one-time inputs are explicitly labeled in the station timezone. See [timed events](timed-events.md).
