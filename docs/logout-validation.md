# Logout revocation and RC9 validation

The RC8 investigation reproduced an application defect independently of browser
navigation timing. Three controlled tests generated authenticated status, static
and login-page responses, held their Set-Cookie headers, signed out, then applied
the delayed headers. All three restored access to `/admin` on the old code.

The fix extends the existing signed-cookie authentication. Each login has a
small `admin_login_sessions` row keyed by a SHA-256 hash of its existing random
logout token. No new authentication cookie, installation identity, reporting
worker or credential is introduced. Logout removes that login's authority before
clearing the cookie. Requests require the matching unexpired login record as well
as the existing active-account/password checks. A delayed cookie cannot recreate
that record, and a response finishing after revocation does not rewrite it.

Flask's one-hour signed-cookie expiry and renewal remain in effect. Login records
have five minutes of cleanup grace, allowing their expiry to be renewed at most
once per five minutes before view processing. Session response finalization only reads the record,
so it cannot commit an unrelated page draft or renew a revoked login. The grace does
not extend the browser cookie's one-hour validity. Expired records are pruned on
subsequent sign-in. Separate browser logins are independently revocable; tabs
sharing a cookie share the login. Existing pre-upgrade cookies require a fresh
sign-in once. No user/account permission is changed by this migration.

Migration `c83d4e5f9012` follows `b72e19d4c603` and adds only the login table and its
expiry index. Runtime application startup does not apply migrations. Production
and the signed RC8 artifacts stay unchanged during preparation.

Regression coverage includes delayed cookie delivery, responses held in flight
across logout/re-login, revocation across application restart, separate logins,
invalid logout CSRF, old cookies, sliding renewal and idle expiry. A real-browser
LIVE MIC test holds an authenticated response in a second tab while the first
cancels and then confirms logout, checks microphone return, releases the response,
and verifies both tabs require login. Existing HTTP/HTTPS, first-use, microphone
and audio checks remain required.

The RC9 test kit's validation.json records the actual final automated results.
Signing requires one fully green recovery run and full acceptance matrix on the
final source. Previous failures and development evidence do not substitute for
that run. Fresh-VM provisioning, reboot, external playback and owner acceptance
remain pending until performed against the exact signed RC9 package.
