# Central Freo API integration

Implemented against [freo-live/api/docs/contract.md at 506a3ee](https://freo.live/downloads/freo-api/506a3ee/contract.md) and its strict request validators. The production origin is `https://api.freo.live`; paths include `/v1`. No OpenAPI document or inferred endpoints are used.

## Architecture and changes

| Existing component | Integration |
| --- | --- |
| `Station`, integer IDs, runtime slug, public aliases | Separate immutable, unique UUIDv4. Migration assigns one to every existing station. Renames and normal upgrades preserve it. |
| Station settings / public location | City, state/province/region and two-letter country code; explicit public genre/categories and directory opt-in, default off. Programming categories stay private. |
| Existing admin authentication, CSRF and audit | `/admin/installation` explains automatic reporting, queues owner connection and shows identity/license status. No network calls in web requests. |
| Icecast observation and station-scoped media availability | Once-per-minute aggregate samples and SQL counts, including shared music available to that station. Soft-deleted tracks are excluded. |
| Independent systemd workers | `freo-central-api.service` samples locally and reports hourly. No playout, scheduler, stream-start or restart dependency on this service or the API. |
| Station allocation lock / enable service | Cached entitlement gates only creation and disabled-to-enabled transitions. Existing enabled stations can stop, start and recover after reboots. Existing local `FREO_MAX_STATIONS` behavior also remains. |

Code is in `app/services/central_api/`, configuration/CLI in `app/routes/central_api.py`. Migration `d18e42f6a905` follows `c07d9a21b634`. Three small tables hold private configuration/cache, last station observations and at most seven days of hourly aggregates. Credentials are not stored in those tables.

## Contract behavior

- `POST /v1/enroll` automatically identifies unconfigured installations without email or an owner account. A locally generated 256-bit credential is saved before the request. Retries use that same credential and return the same UUID. Enrollment backoff survives restarts; lost/corrupt credentials never silently generate replacements.
- Legacy `POST /v1/register` sends manager email once and the machine snapshot. Registration is **not idempotent**. A durable attempt marker precedes the request; its returned installation ID/token are atomically saved before any authenticated request. A lost response or uncertain result requires deliberate operator recovery/retry, never an hourly retry.
- `POST /v1/stations/sync` sends complete station metadata using the permanent UUID. Batches preserve station identities. The API has no station deletion or account-email-update endpoint. Local deletion retains the UUID and queues directory opt-out and off-air reporting where possible.
- `POST /v1/heartbeat` sends current on-air observations, machine facts and completed UTC-hour metrics. Server upserts replace each station/hour, so an uncertain acknowledgement is safe to retry. Reports omit email, titles, artist/album names, paths, listener identities and IP addresses.
- `GET /v1/license` runs after registration, at reporter startup and approximately hourly with jitter. Successful, validated responses replace the local cache. TLS/network/malformed-response failures preserve the entitlement and its original receipt time/grace deadline.

The reporter uses certificate-verified HTTPS, 5-second connect and 30-second socket/read timeouts, bounded bodies, no redirects, exponential 60–3600-second backoff with jitter and `Retry-After`. Bad payloads and identity conflicts wait for operator correction; a missing station triggers sync before retry. Unauthorized credentials never trigger registration. Error logs contain only safe categories/status codes, never raw responses or credentials. A persisted hourly request budget and bounded batches prevent retry floods.

## Measurements and licensing

Average listeners = listener-seconds / observed seconds; listener hours = listener-seconds / 3600. Counts are sampled every minute, so brief peaks between samples may be missed. Unknown observations break the interval; gaps over 120 seconds are not extrapolated. Unknown hourly measurements are omitted. Retries retain completed aggregates, prune data older than seven days and use current on-air state. Icecast mount visibility is the existing application's on-air signal; it is not a global Internet reachability probe.

Library song counts, duration and bytes use the existing availability filter once per track. Artist/album counts use distinct nonempty catalog text locally, including legacy imports without catalog foreign keys. Only counts leave the installation. Disk measurements refer to the configured media filesystem; unavailable hardware measurements are null.

License limits count enabled, nondeleted stations. Within the server-provided grace period, cached active entitlements apply even if their nominal expiry has passed during an outage. Suspended/expired status, exhausted limits, missing initial verification after registration, uncertain clocks or elapsed grace prevent expansion; none disables an existing station. An unconfigured self-hosted installation retains existing behavior. Server clock offset, monotonic elapsed time and durable clock checkpoints prevent restarts from resetting grace. Clock uncertainty requires a fresh valid entitlement before expansion.

No street address or external geocoding service is introduced. The API has no geocoding endpoint; city/region/country are synchronized and coordinates are omitted/null.

## Deployment (operator action; not performed by implementation tests)

After reviewing/merging this branch and backing up the database, check out the reviewed commit in `/opt/freo`. No new runtime Python dependency is needed. Run from `/opt/freo` as root:

```sh
systemctl stop freo.service
runuser -u freo -- env FREO_ENV_FILE=/opt/freo/.env /opt/freo/venv/bin/flask --app app:create_app db upgrade
install -m 0644 deploy/systemd/freo-central-api.service /etc/systemd/system/freo-central-api.service
install -d -o freo-automation -g freo-automation -m 0700 /var/lib/freo/central-api
install -d -o root -g root -m 0755 /etc/freo
git rev-parse --short HEAD > /etc/freo/release
chmod 0644 /etc/freo/release
systemctl daemon-reload
systemctl restart freo.service freo-automation.service
systemctl enable --now freo-central-api.service
```

The automation restart loads the new model schema; station playout units need not restart. Fresh installations install the reporter through `scripts/provision.sh`. The reporter automatically enrolls installations without an owner account. Review **Admin → Installation** for reporting details and optional owner connection; review country/directory settings for each channel. No real registration is performed by the tests.

Defaults: `FREO_API_URL=https://api.freo.live`, `FREO_API_STATE_DIR=/var/lib/freo/central-api`, `FREO_INSTALL_TYPE=self-hosted`. `FREO_VERSION` can override `/etc/freo/release`; source-only checkouts otherwise identify as `development`. A custom state directory also needs matching systemd write permission and owner/mode. The API URL must be an HTTPS origin, without `/v1`, credentials, query or fragment. Leave TLS verification enabled; repair the server certificate if verification fails.

## Recovery and backups

Back up PostgreSQL **and** `/var/lib/freo/central-api/identity.json` securely. Preserve owner `freo-automation`, directory 0700 and file 0600. Never commit or publish that file. Restoring the same installation keeps its installation/station identities. Do not run a cloned identity concurrently on another installation. There is no automatic clone/reset operation; arrange new identities with the API operator.

For lost/revoked credentials, obtain a replacement from the API operator; do not register an already-known installation again. Stop only the reporter, then import the recovered credential using the hidden prompt (never a shell argument):

```sh
systemctl stop freo-central-api.service
runuser -u freo-automation -- env FREO_ENV_FILE=/opt/freo/.env /opt/freo/venv/bin/flask --app app:create_app central-api recover-credential
systemctl start freo-central-api.service
```

An uncertain first registration can be retried from Admin → Installation only after acknowledging that it may create an orphaned second identity. Recover the first response through the operator when practical. Connection retry preserves identity and license cache. The API currently offers no manager-email change endpoint; account changes require the API operator.

Downgrading this migration deletes station UUIDs and reporting state. Treat rollback as an operator recovery operation; retain database/credential backups to avoid replacing registered station identities on a later upgrade.

## Verification

`tests/test_central_api.py` covers registration/recovery, secure persistence, station identity/sync, sampling and privacy, outages/backoff, entitlement caching/grace/clock behavior, and admin/CSRF boundaries. `tests/test_central_api_postgres.py` runs migration/backfill/schema checks only with an explicit disposable `FREO_TEST_POSTGRES_URL`.

The optional `FREO_API_CONTRACT_SOURCE=/path/to/freo-live/api` (or the standalone bundle directory) test loads the actual pinned server validators with Pydantic 2.13.5 from a separate test environment. No API source checkout or Pydantic runtime dependency is needed for normal Freo operation or tests.

Verified on 2026-09-16: full suite **397 passed, 20 skipped**; final focused API run **34 passed**, including the actual pinned server validators; new admin browser flow **1 passed**; PostgreSQL migration/concurrency regressions **8 passed** across the new API, existing station and DMCA tests. An additional station/settings regression run passed 73 checks. The full-suite skips are opt-in/environment-dependent checks; the relevant PostgreSQL checks were run separately against disposable databases. Python compilation, shell syntax, systemd unit validation and Git whitespace checks passed. A read-only HTTPS health check returned 200 with certificate verification enabled. No real installation registration, telemetry submission or production deployment was performed.

## Owner-profile activation

Admin → Installation now accepts the short-lived `FREO-XXXX-XXXX` code generated
at https://freo.live/account. The hidden-input `central-api activate` CLI queues
the same operation. The background reporter performs `/v1/activate`; the web
request never receives or writes the installation bearer credential.

A pending activation code is held in the private local database queue for at most
30 minutes, never rendered back or logged. The reporter first enrolls any new
installation using its durable random credential, then claims the owner profile
with that same credential. It retries transient activation failures with persisted
backoff until expiry. The API permits a used code only for the same authenticated,
already-linked installation. Rejected or expired codes are removed. The hourly
license response also recovers the linked profile UUID after a lost response.

Existing installation/channel IDs, credentials, telemetry and cached licenses
remain intact. Upgrades preserve legacy registration uncertainty and recovery
requirements; they never replace a missing or revoked credential automatically.
Owner account creation and public directory publication remain optional. The
reporter does not stop or restart broadcasts on enrollment or API failure.

### Registration status and account email

First startup enrolls and reports automatically over HTTPS. `registration_state`
is internal connection setup state (`enrolled` after credentials are saved).
The admin registration label uses the owner profile returned by the API:
**Unregistered** until activation, then **Registered with Freo**. The license
response also includes `registration_status`; it is checked against that profile.
Registration does not change reporting, channel allowance or outage behavior.
Freo Live signup leads directly to activation-code generation. Postmark and
account email verification are separate and never required to activate a station.
The mothership needs no SSH access to installations.

## Production receipt verification

Validated HTTP 200 heartbeat responses retain their exact `server_time`, accepted
station/metric counts, next interval and deployed version in private local
reporting state. Admin → Installation displays the last successful heartbeat.
The reporter logs only the installation UUID, server time and accepted counts,
never bearer credentials or activation codes. A failed or malformed response
does not overwrite the last successful receipt.

The Community entitlement is a valid active license even without an account or
paid purchase. Read channel limits and grace deadlines from the API. A 503
`license_unavailable` is a refresh failure: preserve the previous cache and
broadcasts, and continue otherwise permitted heartbeat reporting.
