# Freo web surfaces

The homepage introduces what Freo currently does and states its early-stage installation status. `/stations` lists enabled managed stations, and `/player/<slug>` plays the real public HTTPS `/stream/<slug>` mount. The player labels metadata as the **last confirmed start**, because the most recent history row is not guaranteed to be the item still on air. It handles stream and metadata outages separately. Browser autoplay restrictions require a user gesture; audio begins only after the listener presses Play.

After sign-in, `/admin` is the read-only operational overview. `/admin/stations` lists all managed stations, including stopped stations, and `/admin/stations/<slug>` opens a deeper station view with pending approved requests. The sidebar has read-only Media, Categories, Rotations, Clocks, Schedule, History, and System pages. The station picker keeps those pages station-scoped. The old `/dashboard/<slug>` URL redirects to the station detail page.

The overview renders confirmed playback starts, station-local programming and next transition, library totals, queue depth, worker heartbeat, station audio, and recent airplay. History counts only Liquidsoap-confirmed starts. A confirmed start is not proof the track remains on air, so the panel says **last confirmed start**. Pending requests may change before playback. The public HTTPS stream indicator reads a short audio chunk from the same-origin listener URL in the browser, then closes the connection; it refreshes once a minute. Other operational values use 5-second playback, 15-second runtime, and 45-second programming polls. Unknown observations are never presented as healthy. The media table shows up to 100 tracks but its summary counts the whole station library.

Bootstrap or rotate a dashboard account from `/opt/freo` with:

```sh
sudo ./venv/bin/flask --app wsgi:app admin set-password --email operator@example.com
```

The password is prompted twice without echo and stored as a Werkzeug scrypt hash in PostgreSQL. No account is seeded during public installation. Login has a CSRF token, session cookie with HttpOnly and SameSite=Lax, Secure on production HTTPS, a one-hour session lifetime, and a limited per-session failed-login delay. The failed-login delay is not a substitute for edge-level rate limiting. The login grants **no web mutation capability**; all station, media, automation, clock and schedule changes remain root-run CLI operations.

The player has no chat, requests, votes, artwork, audience numbers, track progress, EQ, visualizer, or guaranteed upcoming-track panel. Those were design concepts and are intentionally absent. The dashboard does not simulate listener statistics, uptime, sponsor delivery, or backups. Fallback audio is labelled as not directly observed. The public site does not claim a supported one-command install until the separate Ubuntu 24.04 clean-VM acceptance test has passed, and Freo has no selected software license yet.
