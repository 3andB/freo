# Main deployment — 2026-09-23

The owner authorized deploying the integrated main baseline to freo.world and
restarting the affected services. Application source moved from `3833874` to
`2144f36`. This preserves accepted source `739a0ed` and all RC5 development.
The application source at `2144f36` is identical to `739a0ed`; the later commit
adds acceptance and automation-audit documentation. This deployment record is
developed on `feature/rc6-candidate` and does not redefine the historical RC5.

## Recovery and database changes

- Recorded the active service set and preserved the previous Git history/source
  and installed dependency inventory.
- Stopped Freo services under the existing maintenance guards; created an
  encrypted database/filesystem backup, including media and host configuration.
- Restored the backup into isolated PostgreSQL databases and recovered filesystem
  trees. Verified contents, sequences, schema, file hashes, and recovery encoding.
- Rehearsed both additive migrations against the populated restored database,
  then migrated production from `d02f9a41c830` to `f39c8210b7de`.
- Compared all pre-existing row values/columns and database sequences against the
  verified recovery point before restarting services. Preservation passed.
- Existing saved settings were retained by the idempotent settings importer.
  Both stations and all 25 tracks remained present; neither account credentials
  nor existing installation-administration privileges were changed.

The private recovery evidence is retained in the dated
`main-deployment-20260923T151542Z` backup directory. Its passphrase is stored
separately in a root-only key file. Disposable verification PostgreSQL was stopped;
its data and restored recovery trees remain available for deliberate recovery.

## Activation and verification

All pinned runtime dependencies, including cryptography and live-microphone
dependencies, were already installed and passed dependency validation. Existing
service definitions matched their tracked source. The new approved-upgrade runner
and timer were installed; the timer only processes explicitly prepared,
administrator-approved plans and does not follow Git branches.

Restarted the previously active application, workers, microphone gateway, radio
engines, and timers. Nginx and Icecast configuration did not require changes.
Checks after the final restart at approximately 15:19 UTC confirmed:

- Public homepage, login, both player pages, health and readiness returned HTTP 200.
- Player CSS/JavaScript, workspace, importer, and station-control assets matched
  deployed source exactly. Player artwork uses 100% of the record circle.
- Both stations reported running/ready. Each public stream supplied a bounded
  65,536-byte MP3 sample that FFmpeg decoded successfully.
- No new error-priority entries appeared in the checked web, automation, ingest,
  microphone, central reporter, or station-engine journals.

The first live migration command encountered unreadable source files because the
deployment script's private umask affected Git checkout permissions. It failed
before database migration. Changed tracked files were restored to standard
readable source/executable permissions, then migration and preservation checks
passed. An immediate stream check also ran before an Icecast mount had connected;
final verification waited for source startup and passed for both streams. These
were deployment-procedure issues; no accepted application source was patched.

Before deployment, the integration baseline passed 214 regression checks (two
optional integration checks skipped), 14 PostgreSQL recovery checks, all seven
browser cases after correcting the local Snap browser setup, and JavaScript
checks. GitHub main-push validation run `35878095888` reported success.

## Frozen RC5

The signed RC5 installer/test kit, preserved hashes, local RC5 tag, and deep-save
directory were not modified, rebuilt, or re-signed. The known-good RC5 test VM
was not accessed. This was a production source deployment, not publication of a
new release: no GitHub Release, version tag, or stable/latest pointer was changed.
