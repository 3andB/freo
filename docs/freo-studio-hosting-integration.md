# Freo Studio hosting integration

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
marker; startup guards prevent service restarts from bypassing it. Station desired
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
