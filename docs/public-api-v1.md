# Public API v1

Freo serves its versioned read API from the existing application at `/api/v1`.
Use your installation's HTTPS address and a bearer credential. This API is separate
from Freo's outbound freo.live installation reporting connection.

## Credentials

In **Radio Station Ops → API credentials**, an active ADMIN can create a named
credential for one or more explicitly selected stations. Copy the token from the
creation response: Freo never displays it again. Store it in your integration's
secret store. The credentials list contains only metadata; it cannot recover a token.

Each credential has `read` scope. DJs cannot manage credentials. Browser login does
not authenticate API requests, and an API credential cannot administer credentials.
Tokens are accepted only in the `Authorization` header, never query parameters or
request bodies. Keep credentials server-side; there is no cross-origin browser API
configuration.

```sh
curl --header "Authorization: Bearer $FREO_API_TOKEN" \
  https://radio.example/api/v1/stations
```

Revocation takes effect for subsequent requests. A credential also stops working
when its issuing administrator is deleted, inactive, changed to DJ, or required to
complete account setup. Credentials do not expire automatically. To change station
access or rotate a token, create a replacement and revoke the previous credential.
New stations do not automatically join existing grants.

## Endpoints

All data endpoints use `GET`. `<slug>` is the station's canonical slug returned by
the stations endpoint, not a custom public URL alias. All stations and nested
resources are checked against the credential's grants.

| Endpoint | Data |
| --- | --- |
| `/api/v1/stations` | Authorized, non-deleted stations: `id`, `slug`, `name`, `description`, `timezone` |
| `/api/v1/stations/<slug>` | One station with the same fields |
| `/api/v1/stations/<slug>/now-playing` | `current`, `program`, `mode`, `fresh`, `observed_at`, `stream_online`, `timezone` |
| `/api/v1/stations/<slug>/schedule` | Current/upcoming intervals with `start`, `end`, `title`, `source` |
| `/api/v1/stations/<slug>/listeners` | `current`, `online`, `fresh`, `observed_at`, `summary`, `timeline` |
| `/api/v1/stations/<slug>/library/tracks` | Available music metadata |
| `/api/v1/stations/<slug>/library/tracks/<uuid>` | One available music track |

The now-playing `current` array accommodates overlapping audible sources. Each item
has `track` (UUID or null), `freo_track_id`, `title`, `artist`, and `started_at`.
For an audible upstream relay, `track`, `freo_track_id`, and `started_at` are null;
`title` and `artist` contain the available upstream metadata. Upstream URLs and
connection details are never exposed. It uses confirmed, fresh engine observations. An empty array does not prove silence;
check `fresh` and `stream_online`. `mode` is Freo's existing operator mode, such as
`AUTO` or `DJ_BOOTH`; a configured mode alone does not prove a live broadcast.
`program` is the existing player presentation, including “Live DJ” where applicable.

Schedule accepts `days` from 1 to 7, default 7. Its window starts at midnight today
in the station timezone and ends at midnight after that many calendar days. Expired
intervals are excluded. Intervals are clipped to this window, so the first start
may be midnight even when the program began earlier. This describes current active
programming through Freo's existing resolver, including visual modes and legacy
clocks; it is not a historical airplay log or a prediction of individual songs and
timed-event execution. It does not depend on the website's schedule publishing setting.

Listeners accepts `range=24h`, `7d`, or `30d`, default `24h`. The current count uses
existing cached stream observations; missing/stale observations produce null.
`summary` contains `average`, `peak`, `listener_hours`, and `coverage` (percent).
`timeline` contains bounded aggregate points with `at`, `average`, and `peak`;
unobserved points have null averages and peaks. Coverage distinguishes missing
observations from measured zero audience. Metadata includes the requested range,
UTC `start`/`end`, timezone, and underlying `resolution_seconds`. Chart intervals
may combine multiple retained buckets. No individual listener information is exposed.

Library metadata contains `uuid`, `freo_track_id`, `title`, `artist`, `album`,
`genre`, `release_year`, `isrc`, and `duration_ms` (original media duration).
Only enabled, accepted, non-decommissioned music is included. Existing track,
artist, and album sharing grants intentionally make shared music available to other
stations; private music from another station remains inaccessible. The collection
supports literal case-insensitive title/artist search with `q` (maximum 100 characters).
The API supplies neither audio downloads nor internal storage/ingest metadata.

## Responses, pagination, and errors

Success responses use `{"data": ...}`. Collections also include
`"meta": {"page": 1, "per_page": 50, "total": 123}`. Stations, schedules, and
track lists accept `page` (1–1,000,000) and `per_page` (1–100, default 50).
Ordering is stable: station slug, schedule start, or artist/title/track identity.
Pages beyond the result set contain an empty array. Pagination is not a snapshot;
concurrent catalog changes can shift items between pages.

Dates and times are ISO 8601 UTC with an explicit offset; station timezone is IANA.
Absent optional metadata can be null. Unknown/duplicate query parameters and invalid
values return `400`. Collection filters are applied before pagination and counting.

```json
{"error":{"code":"unauthorized","message":"A valid API bearer token is required."}}
```

| Status | Error code | Meaning |
| --- | --- | --- |
| 400 | `invalid_request` | Invalid parameters |
| 401 | `unauthorized` | Missing, invalid, revoked, or inactive credential; includes `WWW-Authenticate: Bearer` |
| 403 | `forbidden` | Station outside this credential's grants |
| 404 | `not_found` | Missing/deleted resource, unavailable track, or unknown endpoint |
| 405 | `method_not_allowed` | Unsupported method; includes `Allow` |
| 429 | `rate_limited` | Rate limit exceeded; includes `Retry-After` in seconds |
| 500 | `internal_error` | Unexpected failure; no internal details returned |
| 503 | `unavailable` | Required settings or schedule presentation unavailable |

Authentication precedes routing errors: anonymous requests receive `401`, including
unknown URLs under `/api/v1`. All V1 responses are JSON and marked `no-store`
(normal HTTP `HEAD` responses have no body). Automatic authenticated `OPTIONS`/`HEAD`
do not grant write access. There are no data write endpoints.

## Limits and compatibility

Fixed UTC-minute limits are 120 requests per credential and 300 requests per client
network address, shared across application workers. Invalid authentication attempts
also consume the network allowance. Respect `Retry-After`; polling now-playing every
five seconds is sufficient for typical integrations.

Address handling follows `DMCA_TRUSTED_PROXY_IPS`: only those peers may supply
`X-Real-IP`. Limit records contain a daily keyed address hash rather than raw IPs,
and requests prune buckets older than 24 hours. Limits use the existing database;
no additional service or configuration is required. Database failure does not
bypass authentication or rate limits.

Existing unversioned player/public endpoints retain their established behavior.
This API does not alter UI authorization, scheduling, ingest, automation, or listener
request workflows. Webhooks, OAuth, public writes, SDKs, GraphQL, and developer
portals are deferred.
