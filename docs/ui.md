# Freo web surfaces

The homepage introduces what Freo currently does and states its early-stage installation status. `/stations` lists enabled managed stations, and `/player/<slug>` plays the real public HTTPS `/stream/<slug>` mount. The player labels metadata as the **last confirmed start**, because the most recent history row is not guaranteed to be the item still on air. It handles stream and metadata outages separately. Browser autoplay restrictions require a user gesture; audio begins only after the listener presses Play.

`/dashboard/<slug>` is a password-protected, read-only operations overview. It shows observed stream/playout state, desired state, automation heartbeat and queue, active programming, next transition, media/category summaries, and confirmed recent starts. All data comes from existing station-scoped APIs. A status of `Unknown` means an observation failed; it is never presented as healthy. The media listing API is capped at 100 rows, so the dashboard labels that figure **tracks shown**, not a full library count. The heartbeat timestamp is evidence of recent worker activity, not an uptime metric.

Bootstrap or rotate a dashboard account from `/opt/freo` with:

```sh
sudo ./venv/bin/flask --app wsgi:app admin set-password --email operator@example.com
```

The password is prompted twice without echo and stored as a Werkzeug scrypt hash in PostgreSQL. No account is seeded during public installation. Login has a CSRF token, session cookie with HttpOnly and SameSite=Lax, Secure on production HTTPS, a one-hour session lifetime, and a limited per-session failed-login delay. The failed-login delay is not a substitute for edge-level rate limiting. The login grants **no web mutation capability**; all station, media, automation, clock and schedule changes remain root-run CLI operations.

The player has no chat, requests, votes, artwork, audience numbers, track progress, EQ, visualizer, or guaranteed upcoming-track panel. Those were design concepts and are intentionally absent. The dashboard does not simulate listener statistics, uptime, sponsor delivery, or backups. The public site does not claim a supported one-command install until the separate Ubuntu 24.04 clean-VM acceptance test has passed, and Freo has no selected software license yet.
