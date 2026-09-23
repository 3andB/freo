# Version awareness client — RC6 development

The existing central API reporter, persisted installation identity, and canonical
`app/version.py` remain authoritative for client identity and installed version.
This change uses development version `0.3.0-rc.6.dev2`. It is not a stable release,
RC6 freeze, automatic upgrader, or change to licensing enforcement.

## Running version and release metadata

UI, enrollment, legacy registration, activation, and machine snapshots import the
same `VERSION`. No environment override or nearest Git tag supplies the version.
A restarted process imports the newly installed source. Invalid empty/nonstring/
overlength build metadata is logged and becomes `unknown`, never an invented
release number. Build tooling continues to require an exact `v` + VERSION tag for
public packages. The development bump distinguishes this change from deployed
`0.3.0-rc.6.dev1`.

A future stable release requires its own approved product version, matching tag,
and published stable GitHub Release in `3andB/freo`. This task publishes none.
No release/build mismatch was found; stable version selection remains a separate
release decision after VM acceptance.

## Wire behavior

An abridged request to `POST https://api.freo.live/v1/heartbeat`:

```json
{
  "installation": {
    "freo_version": "0.3.0-rc.6.dev2",
    "install_type": "self-hosted",
    "os": "Linux",
    "architecture": "x86_64"
  },
  "stations": []
}
```

The real request retains known CPU, RAM, disk measurements, all station status,
and existing hourly metric batches. This example omits optional measurements and
uses an installation with no station entries. Response-only version fields are
never sent. Authentication uses the existing bearer header, never a URL parameter.

Representative first-release response (timestamps are illustrative):

```json
{
  "server_time": "2026-09-23T22:00:00Z",
  "next_heartbeat_seconds": 3600,
  "stations_accepted": 0,
  "metrics_accepted": 0,
  "installed_version": "0.3.0-rc.6.dev2",
  "latest_version": null,
  "version_status": "UNKNOWN",
  "update_available": null
}
```

Only the server establishes version precedence. Leading `v`, prereleases and
legacy strings are transmitted unchanged. The client no longer implements SemVer
comparison. Missing/unfamiliar status fields become Unknown without rejecting the
heartbeat or changing identity. Extra response fields are ignored.

## UI behavior

Both installation settings and the operations overview share the cached version
projection. They show the running version, latest stable (or Unknown), status,
last heartbeat time and a separately labeled release-discovery time.

| Server status | Label | Update notice |
| --- | --- | --- |
| CURRENT | Current | None |
| UPDATE_AVAILABLE | Update Available | Only with explicit boolean `true` |
| AHEAD | Ahead | None; normal development/test state |
| UNKNOWN | Unknown | None |

A successful Unknown response clears the prior status. Network failures preserve
the last receipt and show a stale note; an older running-build receipt cannot
claim the newly running build is Current. Public metadata alone never establishes
an installation's status. A new public latest version invalidates the previous
comparison until the next successful heartbeat.

`GET /v1/releases/latest` is unauthenticated and supplies optional release details
on an explicit existing **Check connection now** action, at most hourly. Normal
heartbeats do not add release requests. Successful discoveries and their actual
server `checked_at` are cached separately from local fetch/contact times. Failed
lookups retain the cache; Retry-After is honored. Only HTTPS links to the official
repository's release tag pages are rendered. A null latest release is normal.

Public discovery was checked during implementation: it returned `latest_version:
null`, `release_url: null`, and discovery time `2026-09-23T21:01:40.649035Z`.

## Worker and outage behavior

The existing systemd service and filesystem process lock remain unchanged; no
second scheduler, installation ID, enrollment, or credential recovery path was
added. Startup requests a prompt machine snapshot through the same worker while
respecting durable failures, blocked credentials, global Retry-After, and the
existing hourly call budget. Successful reporting schedules the next tick from
the server's positive `next_heartbeat_seconds` plus existing jitter. Automatic
sampling still ticks once per minute. License failures do not gate reporting
unless the existing authentication/rate-limit safeguards apply.

The transport retains certificate verification, bounded connect/read timeouts,
response size limits, no redirect following, and sanitized errors. Reporting
errors do not interrupt broadcasting. No credentials appear in UI or logs.

## Changed files and validation

- `app/version.py`: development identity and diagnostic fallback.
- `app/services/central_api/releases.py`: tolerant server status, public metadata,
  link validation, shared cached UI projection; removes local comparison.
- `app/services/central_api/__init__.py`: startup reporting, server interval,
  optional cached discovery within the existing manual-check lifecycle.
- `app/routes/central_api.py`, `app/services/operations.py`: shared presentation,
  discovery-only CLI and correct contact/discovery timestamps.
- `app/templates/admin/installation.html`, `app/templates/admin/overview.html`,
  `app/static/operations.js`: all four states, stale note and optional release link.
- `tests/test_versions.py`, `tests/test_central_api.py`,
  `tests/test_connection_check.py`, `tests/test_central_api_browser.py`,
  `tests/test_operations_browser.py`: contract, lifecycle, outage, identity,
  telemetry preservation and browser coverage.
- `CHANGELOG.md` and this document: development handoff.

Focused tests exercise actual payloads, restarted reporting, all four statuses,
older/malformed responses, null latest, nonboolean flags, server cadence, transport
errors, free/absent/expired/suspended entitlement, cached discovery and timestamps,
untrusted links, persistent credentials and the existing singleton process lock.
Browser coverage checks both screens, notices and links at mobile/tablet/desktop
widths. Full regression validation runs on disposable GitHub runners.
