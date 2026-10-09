# Freo Studio hosting integration

Fresh-server bootstrap and the minimal independent SSH contract are documented
in [V1 RC1 installation](v1-rc1-installation.md). Studio owns provisioning, SSH
dispatch, authentication and orchestration; its implementation is not assumed
to exist or be compatible.

Freo enforces local capacity and service policy. Studio makes commercial decisions
and invokes approved local commands over restricted SSH. There is one open-source
Freo distribution and installer. No Studio connection, billing provider, licensing
server, OVH API, management API, or additional daemon is required.

## Authority and defaults

`/etc/freo/hosting.json` belongs to root, mode 0644, under root-owned directories
that application accounts cannot modify. Only privileged administration changes
it. JSON writes use replacement and filesystem synchronization. Duplicate keys,
unknown properties, booleans used as numbers, unsafe permissions, symlinks, and
invalid values are rejected.

The installation default is exactly `{"hosted": false}`. Legacy installations
without a file or a hosting-enabled marker also remain self-hosted. Self-hosted
customers see no hosting controls, notices, plans, or quota display. Their existing
licensing and settings behavior remains unchanged.

An enabled installation uses this schema:

```json
{
  "hosted": true,
  "plan": "starter",
  "status": "active",
  "limits": {
    "stations": 3,
    "listeners": 100,
    "bitrate_kbps": 128,
    "storage_gb": 25
  }
}
```

`plan` is `starter`, `pro`, or `custom`; names are descriptive. Explicit limits
are authoritative. `status` is `active`, `past_due`, `suspended`, or `maintenance`.
An optional `reason` is plain text, at most 160 characters. Limits are positive
integers; bitrate must permit at least 64 kbps. The supported Icecast build accepts
at most 32,640 assigned listeners, reserving additional client capacity for
administrative and source connections. Limits never guarantee that the VM has
sufficient CPU, bandwidth, or physical storage; Studio must size infrastructure.

A root-controlled marker and transaction/audit records live in
`/var/lib/freo-hosting`, outside customer data roots. Once enabled, missing,
invalid, or replaced self-hosted configuration restricts operations. There is no
customer-accessible disable-hosting operation. Repair an invalid configuration
with an explicit `configure` command using the retained last-valid policy; this
keeps service in maintenance until an explicit successful activation.

| Default plan | Stations | Aggregate listeners | Maximum bitrate | Media GB |
| --- | ---: | ---: | ---: | ---: |
| Starter | 3 | 100 | 128 kbps | 25 |
| Pro | 10 | 250 | 128 kbps | 50 |
| Custom | Assigned | Assigned | Assigned | Assigned |

All plans expose the same software functionality. Hosted capacity replaces the
self-hosted commercial station-license capacity check.

## Approved commands

Run as root from a restricted administrative environment:

```sh
freo-admin hosting status
freo-admin hosting configure --plan starter
freo-admin hosting configure --plan pro
freo-admin hosting configure --plan custom --stations 20 --listeners 500 --bitrate 192 --storage-gb 100
freo-admin hosting configure --plan custom --stations 20 --listeners 500 --bitrate 192 --storage-gb 150
freo-admin hosting suspend --reason nonpayment
freo-admin hosting maintenance
freo-admin hosting past-due
freo-admin hosting activate
freo-admin hosting storage
freo-admin hosting verify
```

All four capacities are required for Custom. Starter and Pro fill their defaults;
explicit capacity flags override those defaults. `configure` preserves current
service status. Increasing capacity on a suspended installation does not activate
it. `suspend`, `maintenance`, `past-due`, and `activate` require hosted mode.

Initial enablement provisions storage accounting and the existing Icecast build
with Freo's native listener patch. If the managed engine needs building, the
existing build helper installs its required build dependencies and verifies the
pinned upstream source archive. Initial enablement includes a controlled service
restart to adopt the bounded recording output. Subsequent listener changes reload
Icecast and preserve established sessions.

Arguments are parsed into fixed operations. No argument is evaluated as shell
code. Do not grant customers this command, root access, unrestricted `sudo`, or
write access to Freo code, policy, systemd units, Nginx, Icecast, or their parent
directories.

Studio's SSH integration must authenticate a dedicated administrative identity
and use an audited forced-command/allowlist dispatcher that admits only these
commands and their validated arguments. Disable forwarding and interactive shells
for that identity. Freo does not install SSH keys or a remote execution service.
Never interpolate AI-generated text into a shell command; pass validated arguments
through the dispatcher. Authentication and infrastructure identity remain Studio's
responsibility.

## JSON and exit codes

Responses on stdout are JSON with `schema_version: 1` and a boolean `success`.
Read `success` and the process exit code. A mutating success includes the actual
`state` and `verification`; failures include `error`, `message`, and the resulting
state where readable. Do not infer success from process launch or a timeout.

```json
{
  "schema_version": 1,
  "success": false,
  "error": "station_limit_exceeded",
  "message": "Existing stations exceed the requested capacity.",
  "current_stations": 7,
  "requested_limit": 3,
  "state": {"hosted": true, "plan": "pro", "status": "active", "limits": {"stations": 10, "listeners": 250, "bitrate_kbps": 128, "storage_gb": 50}}
}
```

| Exit | Meaning |
| ---: | --- |
| 0 | Command completed successfully |
| 2 | Invalid command arguments |
| 3 | Privileged authorization required |
| 4 | Capacity conflict or hosted mode required |
| 5 | Invalid authoritative configuration |
| 6 | Operational, storage, engine, or verification failure |

`status` reports policy and inhibition. `storage` reports `used_bytes`,
`file_bytes`, `database_media_bytes`, `reserved_bytes`, `limit_bytes`,
`remaining_bytes`, `percent`, and `over_quota`. `verify` checks storage accounting,
write access to the reservation ledger inside running worker mount namespaces,
application readiness, broadcast service state, expected mounts, and the native listener limit. Its
`draining` flag identifies preserved sessions above a reduced allowance.
After attachment of older code, the standalone dispatcher still answers `status`
with `compatible_release: false` and the authoritative policy/inhibition. Other
commands return `error: "incompatible_release"`, exit 6, until compatible code is
restored. An error response may contain `state: {"restricted": true}` when policy
cannot be read safely.

## Enforcement and transitions

Station allocation uses the existing PostgreSQL station-allocation lock and a
transaction guard. Disabled stations consume capacity; completed deletions cease
to consume station slots. No plan change automatically deletes stations. A station
or queued/current bitrate conflict rejects a downgrade without changing policy.
Backend validation and runtime rendering enforce the bitrate maximum. Supported
output choices remain Freo's existing 64, 96, 128, and 192 kbps options, filtered by
the assigned maximum.

Icecast acquires one native, synchronized slot before admitting an audio listener.
The count includes every mount and listening socket, including direct Icecast
connections, and survives fallback mount moves without double counting. Sources
and statistics requests do not consume listener slots. Disconnects release slots.
On listener reduction, existing sessions drain naturally; new admissions remain
blocked while occupancy is at or above the new allowance. Studio must treat
`draining: true` as an intentional temporary excess, not failed enforcement.

Active and past-due service continue broadcasting normally. Suspension and
maintenance create a persistent inhibit marker, disconnect public audio, and stop
Icecast, station playout, and live microphone ingress. Icecast itself observes the
marker; startup guards prevent service restarts from bypassing it. The installer
adds guards to retained legacy Icecast units as well as new Freo units. Station desired
states and customer data are retained. Reactivation restores intended running
stations and verifies their sources before reporting success. A failed transition
retains a restricted state and reports failure.

Administrative operations are serialized with existing runtime and allocation
locks. They validate before publication and record a durable transaction journal.
`audit.jsonl` records timestamp, operation, operator identity, previous/requested
state, and result without credentials. Invalid downgrades leave the current plan
unchanged; an ambiguous runtime failure inhibits broadcasting instead of reporting
a false successful rollback or activation.

## Storage accounting and recording safety

One GB is exactly 1,000,000,000 bytes. The root-owned storage inventory follows
configured media, uploads, production, and bulletin roots. It includes recordings,
original audio, imaging, file artwork, previews, retained processing media, and all
customer image/blob columns in PostgreSQL. Hard links count once. Symlinked or
unreadable storage fails closed. OS files, application code, logs, and non-media
database contents are excluded. Temporary files cease consuming capacity when
cleaned up.

Writers reserve capacity under a shared filesystem lock. Reservation files carry
live locks; after a crash, stale reservations can be reclaimed while partial files
continue to count. PostgreSQL media blobs retain reservations through transaction
completion. Existing service identities receive read access for accounting; local
peer-authenticated database roles receive read-only access to media-blob tables.
There is no additional database or storage daemon.

Uploads, ingest copies, production, artwork processing, and previews enforce
bounded writes. Processing subprocesses have kernel file-size limits. Multipart
staging reserves space before request parsing; media uploads require Content-Length.
Processing requires temporary headroom, so an operation can be refused even when
its final output alone would fit. Concurrent operations cannot spend the same free
capacity.

Hosted DJ recordings use a byte-bounded subprocess connected to Liquidsoap's
existing recording lifecycle. Quota exhaustion closes the file, signals the
existing worker, and drains remaining pipe data until normal closure or lease
expiry. It does not stop the broadcast or prevent the next recording after space
is available. Completed partial audio is retained where decodable.

Storage reductions may leave usage above quota. Existing media remains available;
growth is blocked, deletion and cleanup remain possible, and broadcasting continues.
Every involved filesystem retains the greater of 1 GB or 5% of capacity as a safety
reserve. Application quotas cannot protect against unrelated root processes filling
a shared filesystem; Studio must monitor the server's overall disk health.

## Upgrades, restoration, and operational verification

Use the supported signed-artifact upgrade workflow. Hosted policy is not database
entitlement data and must never be taken from a customer's restored backup.
The offline restore command creates an isolated database/tree and does not overwrite
live policy. Explicit root-run attachment tools must wrap replacement in
`freo_ops.hosting_recovery.preserve_authority()`. It journals destination authority,
inhibits audio, and restores policy and standalone guards after attachment.
`restore_authority()` resumes that protection after an interrupted attachment.
Neither function activates service. These files are destination administrator
state: back up `/var/lib/freo-hosting` and the root-owned hosting configuration
separately from customer archives. On replacement infrastructure, restore or assign
administrator authority before attaching customer data or starting services.
A customer archive is never the authority for the destination's plan or status.

Older code without hosted enforcement must remain inhibited. Restore or upgrade to
compatible code before attempting activation. Activation reconciles storage access
and database accounting permissions, then verifies actual services. An older backup
must not reactivate a suspended customer.

For acceptance, test simultaneous connections across multiple mounts, including
public Nginx and direct Icecast paths; reconnects; listener reductions; concurrent
uploads; database artwork; actual DJ recording exhaustion; suspension with live
listeners; reboot while suspended; and recovery of an older customer backup.
Use `hosting verify` after changes and review the installed acceptance report.
Do not interpret mocked tests or a successful JSON configuration write as proof of
streaming enforcement.


Verified acceptance and commands are recorded in
[v1-hosting-test-report-2026-10-09.md](v1-hosting-test-report-2026-10-09.md).
The disposable reproduction scripts are in
[tests/hosting_acceptance](../tests/hosting_acceptance/README.md).

## Phase C: local administrative lifecycle

These commands ship in the same distribution and require root in both modes.
They add no customer UI, remote API, monitoring agent, or Studio dependency.
The existing `freo-admin hosting ...` interface remains available unchanged.

### Commands

| Command | Behavior |
| --- | --- |
| `freo-admin status` | Installation ID, installed version, readiness, OS, uptime, hosting state, current administrative operation. |
| `freo-admin health` | Actual database/readiness, expected workers and playout, Icecast sources, bounded direct and Nginx stream reads. |
| `freo-admin resources` | One-second CPU sample, RAM, filesystem byte counts, persistent customer media, aggregate listeners, systemd process resources. |
| `freo-admin backup create` | Maintenance window: stop writers, create and integrity-verify an encrypted full backup, restore permitted services and verify health. |
| `freo-admin backup list` | Approved backup IDs, timestamps, versions, purpose, and verification state. |
| `freo-admin backup verify --id BACKUP_ID` | Verify encrypted bundle contents and recorded checksum. Does not claim a restore was tested. |
| `freo-admin backup restore --id BACKUP_ID --confirm-installation INSTALLATION_ID` | Explicitly authorized live recovery; first retain a recovery point, restore into isolated locations, verify, attach, retain displaced data, verify permitted services. |
| `freo-admin upgrade check` | Inspect root-staged signed releases using the existing updater's preflight; report compatibility and current upgrade journal. |
| `freo-admin upgrade apply --version VERSION` | Run the existing signed-artifact updater, verified recovery point, migrations, activation, and operational checks. |
| `freo-admin services status` | Observed systemd states and resource properties for installed Freo/Icecast units. |
| `freo-admin services restart --service SERVICE` | Restart an approved logical service and verify actual health. |
| `freo-admin services recover` | Resume authorized backup/restore recovery or reconcile required services; never silently restore an old database after a migration. |

`SERVICE` is one of `application`, `icecast`, `playout`, `microphone`, `ingest`,
`automation`, `production`, `statistics`, or `scheduled-workers`. `playout`
selects enabled stations whose saved desired state is running. Arbitrary unit
names, PostgreSQL control, shell commands, executable paths, and URLs are rejected.

Backup IDs contain exactly 32 lowercase hexadecimal characters. Restore accepts
only approved backups belonging to the destination installation. The confirmation
value must exactly match `status.installation_id`; Studio must obtain explicit
administrative authorization before including it. Do not derive authorization
from an AI conversation's unconfirmed inference. Freo itself implements no new
identity provider or approval service.

### Results, errors, and health

Every lifecycle invocation produces one JSON document on stdout. All responses
contain `schema_version: 1`, `success`, and actual hosting `state`. Mutations
return `operation_id` and `verification` when completed. `success` means completed
and verified, not queued. Diagnostics work without Flask startup.

Example successful health response, abbreviated:

```json
{
  "schema_version": 1,
  "success": true,
  "health": "healthy",
  "state": {"hosted": false},
  "checks": {
    "database": {"success": true},
    "freo.service": {"success": true, "expected": "active", "observed": "active", "intentionally_suspended": false}
  },
  "streams": [],
  "listeners": 0,
  "problems": []
}
```

Health classifications are `healthy`, `degraded`, `intentionally_suspended`, and
`failed`. Intentional suspension is healthy only when the required administrative
application/workers work and broadcasting is actually unavailable. A database or
application readiness failure remains a failure during suspension. Individually
stopped stations are not expected to broadcast. A native listener-cap rejection
is distinguished from an unavailable source; probes do not disconnect existing
listeners to obtain a slot.

Resources use bytes, percentages, and seconds. Per-service `CPUUsageNSec` is a
cumulative systemd counter, not an instantaneous percentage. Unavailable counters
are `null`. Self-hosted media reporting has `limit_bytes: null` and installs no
quota policy. Live measurements are observations, not reserved capacities.

| Exit | Meaning |
| --- | --- |
| 0 | Operation completed successfully; health may be intentionally suspended. |
| 2 | Invalid command, argument, identifier, or unsupported service selector. |
| 3 | Root authorization missing. |
| 4 | Operation rejected, including wrong restore confirmation, unavailable backup/version, inhibited broadcast restart, or another administrator holding the lock. |
| 5 | Invalid or unsafe administrative configuration. |
| 6 | Operational, integrity, compatibility, health-verification, or recovery-required failure. |

Structured failures include `error` and `message`, with relevant safe details:

```json
{
  "schema_version": 1,
  "success": false,
  "error": "recovery_required",
  "message": "Inspect the upgrade journal; restore its recovery point explicitly.",
  "backup_id": "0123456789abcdef0123456789abcdef",
  "state": {"hosted": false}
}
```

### Lifecycle result fields

The following fields supplement the common envelope. Treat identifiers as opaque
strings; retain the returned backup ID rather than constructing a filename.

| Operation | Result fields |
| --- | --- |
| `status` | `installation_id`, `version` (or `null`), `application_ready`, `hosting`, `os` (`ID`, `VERSION_ID`, `PRETTY_NAME`), `uptime_seconds`, `operation` (`operation_id`, `operation`, `phase`, or `null`). |
| `health` | `health`, `checks` keyed by component/unit, `streams` array with `station_id`, `listeners`, `problems`. Probes include `success`, HTTP status and bytes read when available. |
| `resources` | `cpu_percent`, `sample_seconds`, `ram` (`total_bytes`, `available_bytes`, `used_bytes`), `disks` (path/device/total/used/free bytes), `media`, `listeners`, `services`. Service counters are `MemoryCurrent`, `CPUUsageNSec`, `MainPID`. |
| `backup create` | `operation_id`, `backup` (`id`, `version`, `status`), `encryption` (`key_id`, `escrow_required`), `verification` (full health result). |
| `backup list` | `backups` array: ID, creation timestamp, version when recorded, role, status. Incomplete entries are not usable recovery points. |
| `backup verify` | `backup` (`id`, `version`, `status`). No health restart is implied. |
| `backup restore` | `operation_id`, `backup_id`, `recovery_point` (pre-restore backup ID), `preserved_database`, `verification`. |
| `upgrade check` | `releases` (version, signature verification, compatibility, commit, platform, schema head, preflight result), `upgrade` (journal operation/phase or `null`), `source: "root_staged"`, `recovery_key_present`. |
| `upgrade apply` | `operation_id`, `upgrade` (existing updater result), `backup_id`, `verification`. |
| `services status` | `services` keyed by unit name, containing observed `LoadState`, `ActiveState`, `SubState`, `Result`, and systemd counters as strings. |
| `services restart` | `operation_id`, `verification`. |
| `services recover` | Result of the resumed operation. Upgrade reconciliation adds `upgrade_outcome`: `complete`, `aborted_before_migration`, or `aborted_before_changes`; ambiguous migration outcomes fail with `recovery_required`. |

A successful `status` means reporting completed; inspect `application_ready` and
use `health` to assess operational health. Missing optional measurements are
reported as `null`. Backup catalog status records creation/integrity verification;
actual restore verification is returned and audited separately. Failed commands
never imply that earlier steps were reversed: inspect the actual state and journal.

### Backup encryption and recovery

Root-owned `/var/lib/freo-admin` stores identity, operation/audit journals, backup
metadata, encrypted bundles, isolated recoveries, and the retained administrative
runtime pointer. It is separate from customer backup roots. Backup bundles use
Phase A's existing format and include database records, media, configuration,
and matched executable code. There is no automatic retention deletion.

On first backup use Freo generates `/var/lib/freo-admin/backup.key` with mode
`0600`. The key never appears in JSON, arguments, logs, or the encrypted bundle.
Studio or the administrator must copy it separately into protected off-server
escrow, alongside encrypted backup copies. Losing both the host key and its
escrow prevents recovery. Existing key metadata prevents silent regeneration of
a missing or replaced key. JSON identifies the key without disclosing it.

Backups require downtime because the existing engine verifies that all writers
are stopped. Space preflight budgets full staging/encryption/restore copies;
this is not incremental backup. The current conservative preflight budgets
six times the current inventory plus 1 GB; live restore also includes the selected
backup's uncompressed size in that multiplier. Provision recovery capacity
separately from the customer media allowance and manage retention externally.
`verify` checks integrity only; live restore also verifies a new database, row signatures, sequences, schema and restored file
hashes before attaching them.

Live attachment preserves displaced databases and files rather than deleting
them. Customer configuration is restored entry by entry while the
`/etc/freo` directory and its administrative policy/trust files stay in place.
An interruption cannot temporarily install an older hosting status or publisher
key from the customer backup. Destination installation identity, hosting policy,
suspension, publisher trust, upgrade policy, encryption key, and administrative
journals remain
independent of restored customer configuration. Destination PostgreSQL and TLS
configuration are not blindly replaced. The supported attachment profile is the
existing local PostgreSQL installation with matching service ownership and paths.
Cross-server migration and external PostgreSQL require a separately reviewed
recovery procedure.

Persistent maintenance guards in `/usr/local/lib/systemd/system` protect an
interrupted operation across reboot, independently of restored `/etc` service
files. The verified candidate installs retained administrative tooling before
the first migration, allowing the same CLI to recover even a 0.3.2 source.
Services absent from an older matched backup are retained and disabled.
`services recover` resumes an already authorized restore from its journal.
Repeating restore with the same backup and confirmation also resumes it; choosing
a different backup during attachment is rejected. Suspended or maintenance
hosting remains inhibited. Application reactivation still requires the existing
explicit `hosting activate` command.

An interrupted migration is not permission to overwrite new writes. Freo reports
`recovery_required`; Studio must inspect the result and obtain authorization for
the explicit backup restore. It retains the failed installation and upgrade
journal for diagnosis. Generic service restart cannot clear an unfinished
upgrade's maintenance guard.

### Root-staged upgrade contract

Studio transfers artifacts through its privileged deployment channel before
invoking lifecycle commands. It must create `/var/lib/freo-updates`, its `staged`
subdirectory, and each version directory root-owned with mode `0700`:

```text
/var/lib/freo-updates/staged/VERSION/release.tar.gz
/var/lib/freo-updates/staged/VERSION/release.tar.gz.asc
```

Both files are root-owned and private. Provision the trusted publisher public
keyring independently at `/etc/freo/publisher.gpg`; never accept a trust key merely
because it accompanies an artifact. The signature and signed manifest version
must match the requested version. There is no command accepting a URL or path.

By default private candidates are rejected. Disposable acceptance installations
may explicitly set root-controlled `/etc/freo/admin-upgrades.json` to
`{"allow_candidate":true}`. This does not bypass signature verification.
Do not enable candidate admission for ordinary hosted customers.

`check` uses existing updater preflight and can stage files/write its private
journal; it does not stop services or migrate. `apply` repeats authenticity and
compatibility checks, creates and actually restores a recovery point, then uses
the existing upgrade workflow. An installed version cannot be replaced by a
different artifact with the same version. No automatic download, release
publication, rollback-over-new-writes, or PostgreSQL major upgrade is implied.

### SSH, concurrency, and interruption

Use the existing restricted-SSH model: an audited forced-command dispatcher
allowlists these operations and their argument grammar. No interactive root shell,
unrestricted sudo, port forwarding, or arbitrary AI-generated shell strings.
Studio owns SSH authorization, scheduling maintenance windows, user confirmation,
remote orchestration, monitoring, notifications, and key escrow.

Mutations serialize with hosting changes and all updater entrypoints. Concurrent
mutations return a structured busy result; diagnostics remain readable. Audit
records include timestamps, operation, resulting state, operation IDs, and local
operator identity when available. Private diagnostics can contain sensitive
underlying error output and must not be returned to customers or AI prompts.

Commands run synchronously; do not interpret an SSH disconnect or timeout as
success. Reconnect, inspect `status`, `health`, and the recorded operation, then
recover according to its phase. Never blindly repeat a consequential restore with
a different backup. Subprocess probes are bounded; full backups and upgrades may
take substantially longer than ordinary status checks.

Recovery also reapplies the destination's native Icecast listener allowance and
managed DJ recording sink before starting audio. Other restored audio settings
are retained; customized recording callbacks/encoders require review instead of
being silently replaced. Health checks verify the actual native listener limit.
Backups whose stations or bitrates exceed destination capacity are rejected before
stopping the current installation. Storage may remain over quota as in Phase B.
Hosting mutations are refused while a lifecycle recovery is unfinished, so a
saved authority journal cannot overwrite a later CLI policy change.

CLI-managed backups record their uncompressed size for expansion-space preflight.
Older unregistered/offline bundles or incomplete preview metadata require the
reviewed Phase A offline recovery procedure. Live attachment rejects a changed
PostgreSQL connection mapping before stopping services; database relocation or
credential remapping must use a reviewed recovery procedure. It never guesses
which differently configured database should be displaced.
