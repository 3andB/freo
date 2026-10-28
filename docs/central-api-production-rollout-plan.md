# Freo HTTPS reporting rollout for freo.world

Prepared 17 September 2026. This is a deployment plan; no code integration,
migration, service restart, enrollment or telemetry submission was performed
while preparing it.

The deliverable is a deployed client that reports automatically and a verified
installation in Freo Live. Completion requires evidence of a real authenticated
heartbeat, matching installation UUID and fresh server-side last-seen time.

## Product model: installation, optional registration, optional paid license

These are three separate concepts. Installing Freo automatically establishes
identity and reporting. Registration and a paid license are optional.

| Concept | Meaning | Effect on reporting |
| --- | --- | --- |
| Installation | A permanent UUID identifies this Freo installation. It can exist without an account or paid license. | Automatically enrolls and reports using its persistent credential. |
| Registration (optional) | An owner links the installation/station to a Freo Live account and receives `Registered with Freo` status. | Continues with the same credential, installation/channel UUIDs and history. |
| License (optional) | A paid entitlement associated with the owner, station or installation according to the API contract. The API reports its status. | Paid entitlement is not required for enrollment or reporting. |

Community allowance remains available to both unregistered and registered
installations without a paid license. An installation UUID does not establish
owner registration, and registration does not establish a paid entitlement.

Keep identity/connection state, owner registration status and paid license status
separate in storage, validation and Admin → Installation. An unregistered
installation without a paid license is an ordinary supported state. A registered
installation without a paid license is also an ordinary supported state.

`GET /v1/license` remains the status/entitlement fetch required by the supplied
API contract; calling it does not require purchasing or activating a paid
license. A valid response indicating no paid entitlement must be accepted and
cached. It must not be confused with a failed status fetch or expired paid
entitlement. Do not invent a wire representation for absence of a paid license;
the API team has confirmed that this is the normal active Community entitlement.
`plan: free` does not mean a missing license. Read `channel_limit` and
`grace_until` from the response; do not hardcode the current two-channel,
seven-day defaults. A genuinely missing license returns retryable
`503 license_unavailable`; preserve the previous cache and existing broadcasts.

Paid-license changes must not recreate identity, change owner registration or
stop ordinary reporting. Implement entitlement associations and paid feature
rules only as defined by the API contract. Billing and purchase flows are
outside this reporting rollout.

## Sources and observed starting point

- Required client commit: [`a05b690840b047fdb180d75b83b3871adbd27996`](https://github.com/lee-3andB/freo/commit/a05b690).
- Retrieved [client guide at that commit](https://github.com/lee-3andB/freo/blob/a05b690/docs/central-api-integration-plan.md).
- Required [API contract at `506a3ee`](https://github.com/lee-3andB/freo-live/blob/506a3ee/api/docs/contract.md).
  Retrieval of its raw content returned HTTP 404. The local API source cache is
  at `1116c05`, so it cannot establish compliance with the requested revision.
  The retrieved client guide also retains an older contract link in its opening
  paragraph; use `506a3ee` and the supplied requirements as the intended baseline.
- Local checkout HEAD is `b3b9b60`; the required client commit is not present in
  its current object database. There are substantial uncommitted website and
  station changes, including changes to the installation template and API tests.
- Local reporting code still stops at `registration_state == 'unconfigured'`
  and uses email-based `/v1/register`. Starting the current service does not
  provide automatic enrollment.
- Read-only host inspection found `freo-central-api.service` loaded, active and
  running as `freo-automation`. The standard state directory is owned by
  `freo-automation:freo-automation`, mode `0700`; `identity.json` is absent there.
  This does not prove that the database, an alternative state directory or
  backups contain no previous installation identity.
- `.env` explicitly sets `PUBLIC_BASE_URL=https://freo.world`; the three API
  settings below are not explicitly set. Current code defaults match them.
- `/etc/freo/release` contains `5d26c04`, older than checkout HEAD. The deployed
  release must accurately identify the final integrated code.
- No reporter journal entries were returned for the preceding ten minutes.
  No authenticated delivery or Freo Live registry verification is established.

## 1. Establish identity and preserve the running installation

Client team:

1. Record the working-tree changes, current service unit and effective nonsecret
   configuration, database migration revision, channel UUIDs, public URLs and
   broadcast status. Inspect systemd overrides as well as `.env`.
2. Read only the relevant database fields to establish installation UUID,
   enrollment/connection state, owner registration status, cached entitlement
   response and reporting state as separate concerns.
   Check the effective state directory. Do not print credentials, activation
   queues, complete environment files or database connection strings.
3. If an installation UUID or uncertain legacy registration exists without its
   credential, recover that identity with the API team. Do not interpret the
   missing standard-path file as permission to create a replacement identity.
4. Take restricted backups of the database, application release, local changes,
   deployment configuration and identity file if present. Verify backup
   readability without exposing its contents.
5. Prepare integration in an isolated checkout. Preserve both tracked and
   untracked local changes, including deleted files; do not reset the live tree.

Exit condition: existing identity state is understood, recoverable backups exist,
and all newer client work is represented in the integration baseline.

## 2. Integrate the published implementation

1. Fetch the published history containing `a05b690` and inspect its prerequisites.
   Merge that history, or a reviewed descendant, into the preserved current
   client baseline. The final commit alone is a small follow-up and must not be
   treated as a standalone implementation patch.
2. Resolve conflicts around the reporter, API client, installation admin page,
   station URL selection and tests while preserving newer website behavior.
3. Verify that `a05b690` is an ancestor of the final release, and review the
   integrated result against the pinned API contract once accessible.
4. Confirm these behaviors in the final code:
   - New installations generate `freo_` + `secrets.token_urlsafe(32)`, atomically
     persist it before any enrollment request, and authenticate `/v1/enroll`
     with that credential. A `201` first response or `200` retry preserves the
     same installation UUID and credential.
   - Existing credentials and permanent channel UUIDs survive upgrades. Missing,
     corrupt or rejected credentials require recovery. New automatic enrollment
     never calls `/v1/register`.
   - Startup enrolls when necessary, fetches and validates `/v1/license` status,
     syncs complete channel metadata, and sends an immediate heartbeat. Persist
     valid status responses, including the no-paid-license state. Neither a paid
     license nor owner registration is a prerequisite for that heartbeat. An
     empty installation sends `stations: []`.
   - Reporting is independent of account creation, email verification and owner
     activation, and of paid-license presence or status. Registered and
     unregistered clients without a paid license use the same reporting
     endpoints and Community allowance returned by the API.
   - Channel metadata uses permanent UUIDs and actual canonical public URLs.
     Inspect the current freo.world routing and any verified custom domains;
     do not invent URLs solely to match a registry search.
   - Heartbeats contain observed on-air state and available hourly aggregates.
     Unavailable measurements are omitted; an unavailable observation is not
     fabricated as an off-air state or zero listeners.
   - Hourly reporting and license refresh use jitter, durable backoff and
     `Retry-After`. Changed metadata is synchronized before affected reports.
   - API outages preserve the last valid status/entitlement cache and do not stop
     broadcasting. A failed status fetch is retried independently; its failure
     must not become a requirement to register or purchase a license before
     reporting. Honor credential rejection and server retry limits.
     A `401` retains identity and exposes recovery needs. A
     `409 station_not_synced` schedules sync before retrying the heartbeat.
   - Optional activation uses the existing bearer credential, preserves IDs and
     reporting history, and displays `Registered with Freo` only when confirmed
     by the API. License refresh also restores registration status after a lost
     activation response. Activation failure does not disable ordinary reporting.
   - Admin → Installation presents installation UUID/connection, optional owner
     registration and optional paid-license status separately. Never infer
     registration from an installation UUID or paid licensing from registration.
     A valid absence of paid entitlement is a normal status, not a setup error.
   - Verify entitlement validators and channel-expansion checks accept the active
     Community entitlement, including null expiry/renewal and optional owner
     linkage. Retain the supplied channel limit and grace deadline. Do not classify absence of a paid license as an
     expired or suspended license, or add a purchase requirement for Community
     use. Preserve separately specified limits and outage behavior.
   - All communication is outbound HTTPS with certificate verification. No
     inbound access, mothership SSH, Postmark or client Supabase access is needed.
     Credentials and activation codes never appear in logs or diagnostics.
5. Ensure successful delivery has safe evidence: persisted last-successful
   heartbeat time or a structured success log containing only UUID, UTC time,
   HTTP outcome and accepted station/metric counts. Add this if absent; a due
   time, running process or empty journal is insufficient proof.
6. Update deployment documentation and configuration examples to match the final
   behavior and contract revision.

Exit condition: one reviewable release contains the required implementation and
all preserved client changes, with accurate version metadata.

## 3. Validate before production deployment

Run tests with installation configuration isolated, a temporary identity
directory and disposable databases. Tests must not create production API
identities or submit synthetic production telemetry.

| Area | Required evidence |
| --- | --- |
| Enrollment | No owner action; credential saved before transport; first `201`, retry `200`; lost response and process restart retain credential and UUID. |
| Upgrade/recovery | Existing identity retained; missing/corrupt credential with existing identity blocks reenrollment; legacy uncertain registration preserved. |
| Startup/reporting | Status fetch → sync → immediate heartbeat without account or paid license; valid empty-station heartbeat; hourly cadence and metadata changes; response counts validated. |
| Independent states | Unregistered/no paid license, registered/no paid license, and registered/paid entitlement all report. Registration alone preserves Community allowance; license changes preserve UUID, registration and reporting history. |
| Entitlement responses | A valid no-paid-license response is accepted and cached; it is distinct from fetch failure or an expired/suspended paid entitlement. Paid status does not gate reporting; Community use follows the contract. |
| Channel data | UUID stability across rename/restart; actual freo.world URLs; correct observed on-air status; missing measurements omitted. |
| Failure handling | Timeouts, TLS/JSON failures, 429/5xx, `Retry-After`, persisted backoff, 401 recovery and 409 resync; status/entitlement cache retained; broadcasts unaffected; transient status-fetch failure does not gate otherwise permitted heartbeat attempts. |
| Activation/UI | Admin authentication and CSRF; no email gate; same credential/IDs before and after activation; status restored through license refresh; sensitive values excluded. |
| Contract | Request/response fixtures checked against `506a3ee`, preferably its actual server validators; do not substitute the cached older validators. |
| Migration | Disposable PostgreSQL upgrade through `d18e42f6a905` and subsequent release migrations; channel UUID backfill and stability; final schema matches models. |
| Regression | Central API unit/browser/PostgreSQL tests, affected station URL and website tests, then the project suite appropriate to the integrated release. Record skips and coverage gaps. |
| Deployment | Validate the systemd unit, provisioning syntax, service-user database/state access and outbound HTTPS configuration. |

Exit condition: relevant checks pass, with failures fixed and any unavailable
contract or environment checks explicitly recorded before rollout.

## 4. Deploy the reviewed release

Set the following explicitly for the standard installation:

```dotenv
FREO_API_URL=https://api.freo.live
FREO_API_STATE_DIR=/var/lib/freo/central-api
FREO_INSTALL_TYPE=self-hosted
PUBLIC_BASE_URL=https://freo.world
```

1. Stop the reporter for the code/schema transition. Follow the normal deployment
   process for schema-dependent application workers and the brief web restart.
   Keep Icecast and station playout running.
2. Deploy the final integrated release. Apply migrations using the normal Freo
   database user and environment, including `d18e42f6a905` if not already applied:

   ```sh
   runuser -u freo -- env FREO_ENV_FILE=/opt/freo/.env \
     /opt/freo/venv/bin/flask --app app:create_app db upgrade
   ```

   Review the entire migration chain, including newer website migrations; do
   not downgrade or stamp over an existing revision.
3. Install the reviewed `deploy/systemd/freo-central-api.service`. Ensure its
   state path is writable under the unit's sandbox and the service user has the
   required local database/configuration access.
4. Preserve any existing identity file. Enforce directory `0700`, credential
   file `0600`, both owned by `freo-automation`. Do not truncate or replace it.
5. Write the final release commit to `/etc/freo/release` for diagnostics. The
   reported client version comes only from `app/version.py`; legacy
   `FREO_VERSION` overrides and this commit file do not affect reporting.
6. Reload systemd and restart only the application workers required by the
   deployment. Enable and start the reporter. Because the reporter is already
   running today, ensure an explicit restart loads the new release; merely
   running `enable --now` on an active worker does not reload its code.
7. Check web and stream availability immediately, alongside the reporter.

## 5. Verify the real installation end to end

Client team and Freo Live administrator:

1. Check the running worker and recent journal:

   ```sh
   systemctl is-active freo-central-api.service
   systemctl is-enabled freo-central-api.service
   journalctl -u freo-central-api.service --since '10 minutes ago' --no-pager
   ```

2. Read the installation UUID safely from local state, without printing the
   bearer credential. Compare it with the database UUID and any recorded
   predeployment identity. For a new enrollment, verify secure file ownership
   and permissions after the reporter creates it.
3. Verify successful authenticated status/entitlement fetch, channel sync and
   heartbeat. A valid response with no paid entitlement satisfies the status
   fetch check; paid-license activation is not required.
   Record the heartbeat UTC time, HTTP `200`, `next_heartbeat_seconds: 3600` and
   accepted station/metric counts. Counts must match the actual request; do not
   require hourly metrics before a measured hour is available.
4. In [Freo Live installations](https://freo.live/admin/installations), locate
   that exact UUID. Record fresh `last_seen_at`, the final deployed version,
   actual channel UUIDs and freo.world URLs, plus correct registration status.
   Record paid-license status separately, including absence when applicable.
   Check by UUID even when URL search returns no results. A custom canonical
   channel domain must be explained by the actual installation configuration.
5. Restart only the reporter. Compare installation UUID, credential equality
   locally without displaying it, and channel UUIDs before/after restart.
   Verify subsequent successful reporting respects persisted scheduling/backoff
   and updates the same registry record without creating a duplicate.
6. Observe the next scheduled hourly cycle, allowing for jitter. Confirm that
   `last_seen_at` advances and available hourly metrics are accepted. Do not
   erase retry state or repeatedly restart the worker to force an early report.
7. If production activation is desired and an owner supplies a code, activate
   through Admin → Installation and verify the same UUID/history with
   `Registered with Freo`. Otherwise retain the correct unregistered status;
   activation is not a condition for reporting acceptance. Registration without
   a paid license must continue to report. No paid purchase or activation is
   required to complete this rollout.

Completion requires both client-side delivery evidence and the matching Freo
Live record. Health connectivity, service activity and an apparently successful
local tick alone do not satisfy acceptance.

## 6. Recovery and rollback

- If reporting fails, keep broadcasts running and inspect only sanitized error
  categories. Preserve the identity, license cache, channel UUIDs and retry state.
- For 401 or identity conflicts, stop enrollment attempts and coordinate
  credential recovery with the API team. Never delete the identity to retry.
- For a client regression, stop the reporter and restore a compatible previous
  application release while preserving the current database and identity where
  schema compatibility permits. Restore the prior release marker as well.
- Do not downgrade `d18e42f6a905` as a routine rollback: it removes permanent
  channel UUIDs and reporting state. Any database restoration requires a
  coordinated recovery plan that preserves identity and subsequent user data.
- Resume the reporter only after the fault is corrected, then repeat UUID,
  heartbeat and server-side last-seen verification.

## API-team answers and verification handoff

The API team supplied standalone [contract](https://freo.live/downloads/freo-api/506a3ee/contract.md),
[validators](https://freo.live/downloads/freo-api/506a3ee/validation.py) and a
[checksummed bundle](https://freo.live/downloads/freo-api/506a3ee/freo-api-506a3ee.zip).
Bundle checksums and standalone-file equality were verified locally. The
validators use `pydantic[email]==2.13.5`, including cross-field checks.

An installation without a paid license receives an active Community entitlement
at enrollment. Both before and after registration, `/v1/license` returns 200
with `plan: free`, null expiry and renewal, and server-supplied channel limit and
grace deadline. Registration changes the owner profile and registration status;
it preserves identity, credential and entitlement. Current production defaults
are two channels and seven days; clients read these from responses. A genuinely
missing license produces retryable `503 license_unavailable`.

The API team confirmed production compatibility, including security fixes at
`eb41af4` that leave the contract unchanged, and will perform registry-side
verification. After deployment, provide the installation UUID, deployed version,
expected channel URLs, expected registration status and successful heartbeat's
UTC `server_time`. Never provide the bearer credential. Client-side receipt and
API-team registry confirmation are recorded separately until both are complete.

Credential recovery is only needed if an existing identity is found without its
credential. Production preflight found no installation UUID and an unconfigured
local record, so automatic enrollment is appropriate for this installation.

## Final deployment report

Return these fields with evidence references, never the bearer credential:

| Field | Required result |
| --- | --- |
| Deployed commit | Full final SHA containing `a05b690` and preserved newer changes. |
| Installation UUID | Same UUID locally, in the API and after restart. |
| Last successful heartbeat | UTC time and authenticated HTTP 200; accepted station/metric counts. |
| Freo Live verification | Fresh server-side last-seen, matching version, actual channel URLs and correct registration status; paid-license status recorded separately and allowed to be absent. |
| Restart and hourly verification | Identity unchanged; next scheduled report received on the same record. |
| Broadcast verification | Streams remain available through rollout and reporter restart. |
| Remaining limitations | Any unresolved item explicitly marked incomplete. |
