# Custom domain implementation and rollout

## Delivered

Stations can hold multiple custom domains. A verified, enabled domain resolves
`/` and `/stations` to its assigned player. Player, listener-alias, and station
logo paths must match that station. Unknown/unverified domains return 404 at the
application; malformed Host values return 400. Installation hosts and existing
station URLs/aliases retain their original behavior. API/admin routing and audio
services retain their existing behavior.

Settings → Domains supports add, verify, remove, and primary selection, with DNS
instructions and status. Verification checks all A/AAAA addresses against trusted
installation targets and requires a claim-specific TXT token. A verified primary
selects the preferred public settings link without redirecting secondary domains.

Authorization uses Freo's existing active global-admin model, CSRF protection,
station-scoped domain lookups, and audit events. This does not add station-specific
user roles or tenant memberships.

## Files changed

- Model/migration: `app/models/__init__.py`,
  `migrations/versions/a09f6d3e82b1_station_domains.py`.
- Routing/verification: `app/services/station_domains.py`,
  `app/routes/station_domains.py`, `app/routes/station_settings.py`,
  `app/services/station_lifecycle.py` (release claims after successful deletion).
- App/configuration: `app/__init__.py`, `app/config.py`, `.env.example`,
  `requirements.txt` (dnspython).
- UI: `app/templates/admin/_station_domains.html`,
  `app/templates/admin/station_settings.html`, `app/static/freo.css`.
- Proxy templates: `deploy/nginx/freo.conf.template`,
  `deploy/nginx/custom-domain.conf.template`, `deploy/nginx/reject-unknown.conf`.
- Tests: `tests/test_station_domains.py`, `tests/test_station_domains_browser.py`,
  `tests/test_station_postgres.py`, `tests/test_station_lifecycle.py`.
- Documentation: `README.md`, `docs/custom-domains.md`, this report.

## Deployment completed

Migration **a09f6d3e82b1**, following **c48f1d207ab9**, creates `station_domains`
with the requested fields plus the verification token. Unique hostname and
partial unique primary indexes protect concurrent writes; check constraints
require verification for enabled domains and an enabled primary domain.

The migration was applied to production after a PostgreSQL backup at
`/tmp/freo-before-domains-20260915-234327.dump` (root-readable only). Both existing
station identities were preserved. The deployed table matches model metadata.

Installed dnspython, configured the installation host allowlist with `freo.world`,
`www.freo.world`, and server IP/loopback names, and set verification targets to `freo.world` / `146.190.35.144`.
The production `.env` is not committed. Preserved Nginx/Certbot, installed the
unknown-host rejection site, and changed the application proxy to preserve raw
Host and clear X-Forwarded-Host. Nginx configuration validation passed; Freo was
restarted and Nginx reloaded. Both services are active and database readiness is OK.

HTTPS smoke checks passed for both installation hostnames and both existing
station players. Admin requests still redirect to login. Unknown hosts return
404 through Nginx (with valid installation TLS SNI) and directly from Flask;
unknown TLS SNI is rejected by the default TLS server.

## Validation

- Domain and existing station-settings tests: **57 passed** (including 40 domain
  cases covering normalization, routing, verification, authorization, constraints,
  primary behavior, removal, and existing URLs).
- Domain browser workflow: **1 passed**, including desktop/mobile layout and
  add → verify → primary → remove.
- Disposable PostgreSQL migration/concurrency suite: **4 passed**, including
  concurrent duplicate domain claims, database constraints, and migration
  downgrade/upgrade. Only existing Alembic integration deprecation warnings.
- Station lifecycle suite: **15 passed**, including failed-deletion retention
  and safe hostname reuse after successful deletion.
- Final full suite (`pytest -q --tb=short`): **303 passed, 15 skipped, 2 failed**
  in 11m59s. All domain tests passed. The skips include opt-in engine and
  PostgreSQL checks; the PostgreSQL suite was executed separately above.
  - `test_import_and_edit_catalog` fails at its existing `dialog button` click
    with `ElementNotInteractableException`. The same failure was reproduced in
    an isolated checkout of the unchanged baseline commit `f27ba21`.
  - `test_cart_glow_global_lock_and_completion_in_both_modes` failed its button
    disabled-state assertion during the full run, then **passed** on an isolated
    rerun. It also passed in the earlier full run. No booth code was changed.
  - The station-deletion cleanup was checked separately with all 15 lifecycle
    tests after the full run had started.

The full suite is not entirely green because of those existing browser checks.
Raw logs are available on this server at `/tmp/freo-domain-final-suite.log`,
`/tmp/freo-catalog-baseline.log`, and `/tmp/freo-domain-booth-recheck.log`.

## Remaining operator steps

For each actual customer hostname, add it in station settings, create the displayed
A/AAAA or CNAME and TXT records, verify it, provision its Nginx site and HTTPS
certificate with existing Certbot, then select a primary if desired. No customer
DNS records or certificates were created automatically.

See [DNS and HTTPS instructions](custom-domains.md). DNS verification is on demand;
it does not continuously monitor DNS changes or establish certificate readiness.
