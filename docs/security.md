# Web control boundary

The authenticated admin session has HttpOnly, SameSite=Lax cookies and HTTPS-only Secure cookies in production. State-changing admin forms require the session CSRF token. Global admin access is centralized in `app.services.admin_auth`; playout control has its own `can_control_playout` permission hook so future operator roles need not inherit programming permissions.

Phase 10 Live Assist never accepts a filesystem path, socket path, or Liquidsoap command from the browser. The browser can submit only hold/resume, approved station media UUIDs for Queue End, or the expected current decision ID for Skip. The worker resolves approved storage through the existing station-scoped media storage service. The socket adapter permits only known queue reads/pushes, metadata lookup by numeric request ID, and fixed skip. The web process user is not in the `freo-playout` group and cannot connect to the socket. Worker snapshots exposed to the browser contain only safe decision metadata, not filenames or raw Liquidsoap replies.

The queue cap, UUID idempotency keys, station row lock, station ownership checks, and current-request check limit retries, concurrent submissions, and IDOR. Audit events record operator actions without session tokens or raw media paths. The Phase 10 migration is additive and retains all prior confirmed playback history.
