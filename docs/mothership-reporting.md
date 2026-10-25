# Mothership reporting contract 2026-10-v1.1

All Freo installations report directly to https://api.freo.live. This is private
installation and channel reporting. It does not connect the mothership to Studio
billing, orchestration, provisioning or credentials. The software host's
`/api/studio` download API is separate. There is one software distribution.

The authoritative [contract](https://freo.live/downloads/freo-api/2026-10-v1.1/contract.md)
has SHA-256 `2344a1e3eae6d66c71a9fd42e815cac2085ef83e8f74ae9ab56fe09235da25fe`.
The reporter checks the public `/health` endpoint and requires the exact
`X-Freo-Contract-Revision: 2026-10-v1.1` header before using its additions. Unknown
revisions use the legacy payload. Support is rechecked after restart, periodically
and after payload rejection, respecting durable failure backoff and Retry-After.

## Local reporting configuration

Set these values in the existing protected installation environment. A managed
installation uses `/etc/freo/freo.env`; a fresh direct installation uses
`/opt/freo/.env`. Restart only the reporter after a configuration-only change.

```ini
FREO_INSTALL_TYPE=freo-studio
FREO_DEPLOYMENT_LABEL=freo-world
```

`self-hosted` means operated outside Studio hosting operations; `freo-studio`
includes Freo's own deployments operated under Studio. `freo-live` is a deprecated
input alias. `freo-world` is a deployment label, never an installation type.
The label is optional and private. Omission preserves a previously reported label;
an explicitly empty value clears it. `FREO_INSTALLATION_LIFECYCLE=active` or
`decommissioned` is an optional, explicit operator setting. Omission preserves
known server state. Network failure never decommissions an installation.

These descriptive settings cannot grant a software license or hosting capacity.
The local three-station allowance, signed unlimited software license and
root-controlled hosting policy remain authoritative. Remote `channel_limit=2`,
owner linkage, grace expiry and authentication failures do not stop broadcasting
or prevent station restart/recovery. Failed refreshes retain the valid cache.

## Identity, lifecycle and delivery

The worker holds the existing identity-file process lock. `/v1/enroll` uses a
client-generated credential saved before its first request. Retries and restarts
reuse it. `/v1/activate` is optional and authenticated; it cannot replace the
installation UUID or bearer. Neither errors nor upgrades authorize re-enrollment.
Preserve the protected identity directory, database and owner association during
backup/replacement restore, and stop the old running copy before replacement.

Station UUIDs stay permanent. The existing retained Station rows are the durable
lifecycle queue and tombstones. `deleted_at` or local `deleted` maps to deleted;
`pending_delete`, `delete_failed` and explicit `retired` map to retired. Ready and
creation states map to active; unrecognized states remain unknown. Disablement
and stopping do not imply deletion. Known lifecycle includes enabled; retired or
deleted always reports false. Deletion timestamps come only from the stored UTC
value, never from names or receipt time. An explicit local restoration sends
active with the same UUID and clears deleted_at. Full daily reconciliation
includes tombstones even after acknowledgement. Directory consent is separate.

The sampler stops producing new records for retired/deleted channels, retains
existing history and drains eligible completed hours. It records actual bounded
observation coverage, without bridging gaps over 120 seconds. Average listeners
uses listener-seconds divided by coverage; listener-hours uses listener-seconds
/3600. Zero coverage sends null average and hours. Existing positive RC11 coverage
is retained; historical records without known coverage remain unknown. Current listeners retains the last valid observation within its own hour; an
unknown later observation does not erase it or borrow from another hour. Original
metric keys stay present, with null for unknown observations. Stale/missing
scheduler observations are unknown. Shared, nondeleted media counts describe what
is available to each channel, so totals are not unique installation storage.

`/v1/stations/sync` validates the exact returned UUID set and count.
`/v1/heartbeat` accepts installation-only `stations: []` and validates exact
channel and metric counts before acknowledging rows. Each batch remains at most
20 channels with five completed hours each. Historical delivery rebuilds current
on_air rather than replaying historical status. Retries replace the same
channel/hour; accepted completed rows cannot be rewritten by older samples.
Catch-up is bounded to seven days; stored history and lifecycle tombstones are
not deleted when they become ineligible for catch-up.

`/v1/license` remains informational to local software rights. Public
`/v1/releases/latest` and heartbeat version fields remain update information,
never download/execute commands. Legacy `/v1/register` remains only for explicit
legacy registration recovery; ordinary installations use automatic enrollment.

## Upgrade and fallback

Migration `fd17b2c3d4e5` adds one nullable JSON provenance column to hourly metrics.
It does not rewrite installation identity, owner state, existing snapshots,
coverage, listener totals, station UUIDs or license/policy data. Internal sampling
bookkeeping is kept outside the snapshot because older reporters serialize its
keys directly. No new application dependency is required.

Use the signed candidate's verified tools with the standard encrypted
backup/restore upgrade procedure. Existing credentials remain in their protected
location. Never run the fresh installer over an existing installation.

If the server stops advertising support, the client sends `freo-studio` as legacy
`freo-live` and omits new fields. Deletion/retirement metadata stays queued; it is
never stripped and submitted as ordinary metadata. Unknown original metric
values cause that hourly record to be omitted on a legacy server. Unknown current
on_air omits that channel's heartbeat; installation-only reporting continues.
Known, eligible records can still drain without being blocked by older unknown
records. When support returns, lifecycle reconciliation resumes.

Prefer rolling forward. An in-place schema downgrade is refused because it would
discard provenance. Software rollback uses the existing matched backup/recovery
workflow, retaining the newer recovery archive. RC11 cannot honor the new
classification configuration or stop deleted-channel sampling; it is not an
acceptable reporting rollback for a completed v1.1 rollout. Server rollback is
handled by the new client's legacy mode without changing identities or policy.

## Acceptance and operator handoff

Run the actual reporter/transport tests, not just schemas. The opt-in HTTPS tests
use the exact published request validators; set `FREO_API_CONTRACT_SOURCE` to the
checksum-verified bundle and install its test-only requirements separately.
PostgreSQL tests require a dedicated disposable database through
`FREO_TEST_POSTGRES_URL`; they reset that database.

Retain source commit, signed artifact digests, test commands/results and any
skipped acceptance. Export only validated nonsecret receipt fields: installation
UUID, client version, contract revision, UTC server/receipt timestamps and
accepted counts. `central_installation.state.last_sync` also records the accepted
channel UUIDs; `last_heartbeat` records exact accepted metric counts. Never export
credentials, activation state or the whole private installation record.

The mothership operator must independently verify persisted classification,
label, lifecycle, timestamps, UUID ownership and channel/hour replacement values.
For Freo World, verify its seven existing UUIDs against the local database. After
the deleted-channel backlog has cleared, observe at least a full hour with no new
hourly records for the five deleted fixtures. HTTP success alone does not complete
acceptance. Reporting acceptance does not authorize publication of public v1.

## RC16 public listing and song sharing

See [Public listing and now-playing sharing](now-playing-reporting.md) for the
2026-10-v1.3 optional endpoint, default-ON consent migration and failure behavior.
Hourly telemetry and licensing remain unchanged.
