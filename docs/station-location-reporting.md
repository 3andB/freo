# Station location reporting

## Cause and scope

Main `25018e9` still has the issue identified at `e1e699c`: the station model
stores city, region and country only, and `central_api.metadata()` unconditionally
sends null latitude/longitude. Healthy on-air heartbeats cannot provide a position.
No suitable existing city lookup is available, so this change uses optional manual
city-level coordinates, with no geocoder, IP inference or external dependency.

The implementation branch starts at `d0266ee92f3dae2f8a861a0668efabcc140d2d51`,
which contains the approved primary-admin migration and is directly based on main
`25018e9b8bd82f1df39aac4acd5dc8a3167cf5b3`.

## Operator workflow

Open **Station settings** at `/admin/stations/<slug>/settings`. The existing
city/region/country section now includes optional latitude and longitude inputs.
Use the station's approximate city location, never a street address, personal
location or the server's hosting location. Supply both values or leave both empty.
Zero is valid. Finite values within latitude ±90 and longitude ±180 are rounded
to two decimals before storage; out-of-range values are rejected before rounding.

When the named place changes while coordinates are supplied, check the confirmation
that they match the submitted place. Confirmation is bound to all five submitted
location values. Editing any of them clears it in the browser; the server rejects
a confirmation for different values. Failed saves leave stored settings unchanged
and preserve the browser's draft. Normal saves for an unchanged place need no
repeat confirmation. Operators can explicitly clear both coordinate inputs.

The existing **Save all changes** action saves the coordinates atomically with
the other station settings. Coordinates participate in the settings conflict
fingerprint, so an older form cannot silently overwrite a newer location.

## Upgrade and reporting

The Alembic chain is:

`f39c8210b7de` → `a64f09e2b731` (primary admin) → `b72e19d4c603` (coordinates).

The coordinate migration adds nullable floats and a pair/range constraint. It
does not populate locations or change existing stations, identities or consent.
The updated release schema allowlist and preservation checker cover both pending
migrations. The existing matched-backup recovery policy remains in force.

Use the next candidate's verified upgrade tools as documented in
[recovery and upgrades](recovery-and-upgrades.md); the frozen RC5/RC6 runner does
not know the preceding primary-admin data-migration exception. This client change
does not package, deploy or publish a release.

After upgrading, operators must configure coordinates before new map pins can
appear. The existing reporter detects the changed complete metadata fingerprint
at its next scheduled report, normally approximately hourly. Its existing startup
refresh and manual connection-check behavior remain available. Backoff,
Retry-After, credential persistence and worker locking are unchanged.

Location uses only authenticated `POST https://api.freo.live/v1/stations/sync`.
There are no new heartbeat fields or background workers. Reporting is independent
of paid entitlement and public-directory opt-in. Two stations can share identical
coordinates while retaining distinct permanent station UUIDs.

Missing coordinates remain valid and are sent as null. freo.live's stated policy
retains the last known valid position; clearing client coordinates does not promise
to remove a previously known server-side position. No server behavior is changed.

## Complete illustrative sync payload

This example is for an operator-confirmed New York station; it is not applied to
any production station. The Authorization header uses the existing installation
bearer token, never a new credential.

```json
{
  "stations": [
    {
      "station_id": "7f1d7031-90d4-45c0-8e9b-c25bf148a60d",
      "name": "Example Radio",
      "description": "Independent music and community radio",
      "genre": "Rock",
      "categories": ["Independent", "Community"],
      "city": "New York",
      "region": "NY",
      "country": "US",
      "latitude": 40.71,
      "longitude": -74.01,
      "public_url": "https://radio.example.org/player/example-radio",
      "directory_opt_in": false
    }
  ]
}
```

Every existing metadata field remains present because station sync replaces the
complete metadata snapshot. Installed version remains sourced from `app/version.py`
(now `0.3.0-rc.7.dev3`) for both UI and telemetry.

## Validation

Local validation on 2026-09-24: **247 passed, 1 optional contract-source test
skipped**. All fixtures used disposable storage, not production or either frozen
candidate VM. No outbound request was sent to freo.live.

| Check | Result | Evidence |
| --- | --- | --- |
| Location, central API, versions, combined settings and connection checks | 178 passed, 1 skipped | `/tmp/freo-location-unit.log` |
| Serialized HTTPS request, updater, release bundle and station settings regressions | 39 passed | `/tmp/freo-location-regression.log` |
| PostgreSQL migration and encrypted backup/restore suite | 27 passed | `/tmp/freo-location-postgres-rerun.log` |
| Location and central API browser workflows | 3 passed | `/tmp/freo-location-browser.log` |

The optional contract-source test requires an independently provided mothership
source checkout. Existing Flask-SQLAlchemy `get_engine` deprecation warnings remain.
`git diff --check` passed. GitHub CI has not run because the branch is not pushed.

The focused settings/reporter tests cover pair validation, zero, bounds, rounding,
atomic failures, exact confirmation, conflict detection, all metadata fields,
authenticated JSON serialization, scheduled resync, distinct IDs at one location,
license failures, retries, missing coordinates and unchanged heartbeat fields.

PostgreSQL tests exercise a populated pre-migration installation through both
migrations, null initial coordinates, unchanged station rows/UUIDs, application
restart persistence, database constraints, encrypted backup/restore preservation,
and a prior administrator permission revocation surviving the coordinate migration.

Browser tests exercise successful and failed saves, draft retention, confirmation
reset, rounded values, ordinary saves and responsive layout at 390/820/1440 pixels.
No lookup failure test is necessary because there is no lookup or network operation
in the location configuration path.

The initial full-schema `db check` also exposed pre-existing drift outside this
change: migration `e28a91bc7304` creates `ix_event_due` on
`timed_event_occurrences`, but the current `TimedEventOccurrence` model omits it.
This change leaves that historical index intact. The migration test compares the
complete `stations` table metadata and explicitly exercises its new constraints;
it does not claim that the unrelated full-schema drift has been resolved.

## Changed files

- Runtime: `app/models/__init__.py`, `app/services/station_location.py`,
  `app/routes/station_settings.py`, `app/services/central_api/__init__.py`,
  `app/static/station_settings.js`, `app/templates/admin/station_settings.html`,
  `app/version.py`.
- Migration/upgrade compatibility: `migrations/versions/b72e19d4c603_station_coordinates.py`,
  `freo_ops/upgrade.py`, `freo_ops/releases.py`.
- Tests: `tests/test_station_location.py`, `tests/test_station_location_browser.py`,
  `tests/test_station_location_migration.py`, `tests/test_primary_admin_migration.py`,
  `tests/test_installation_settings_postgres.py`, `tests/test_release_bundles.py`,
  `tests/test_versions.py`.
- Test automation: `scripts/test-recovery-postgres.sh`, `.github/workflows/recovery.yml`.
- Handoff: this document, `docs/next-installation.md`, `docs/recovery-and-upgrades.md`.
