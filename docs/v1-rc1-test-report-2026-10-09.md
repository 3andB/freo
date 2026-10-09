# Freo World V1 RC1 readiness — 2026-10-09

**Ready for a fresh-OS live installation test.** The signed candidate passed a
fresh Freo installation, self-hosted/hosted acceptance, and active/suspended
reboots on the designated disposable VPS. That VPS reused Ubuntu 24.04.5; a
provider OS rebuild was not performed. This is not stable-release approval.

## Candidate

- Version: `1.0.0-rc.1`; source: `6b1d31a2de7ecfa6e5278fea6f36244b2fc4d7e7`.
- Archive: `freo-v1.0.0-rc.1.tar.gz`.
- SHA-256: `95d67f5279aed6182f85d59ff7bae1486f07f1966a73b1300639a1dc510f2d63`.
- Publisher: `B835B40E7E1A5838390256751AB72B63BEB716C3` (existing Freo release key).
- Signature, all 580 manifest entries, migration head, and offline hashed wheels
  verified; an altered archive was rejected before extraction.
- Later branch commits change tests/CI/evidence only. All 537 shipped source
  files were checked against the signed archive and still match.

## Blockers corrected

Fresh installation registered its recovery runtime against temporary staging;
it now uses installed code. Validation depended on `/usr/local/sbin` being in the
bootstrap PATH; it now invokes the fixed administrative path. Suspended hosting
intentionally blocks setup/operational routes; validation now checks expected
inhibition while retaining application/database/service checks. Fresh-install
refusal also recognizes retained V1 administrative/hosting authority. Installed
version metadata now comes from the shipped application version.

The existing release workflow gained an explicit private-candidate mode for
`develop/v1`, with no release tag or `latest.json`. No new daemon, API, or hosting
implementation was introduced. The release signer was used locally; GitHub's
protected signing secrets remain unconfigured, so CI signing is not claimed.

## Results

| Check | Result |
| --- | --- |
| Broad backend suite | 1,463 passed; 29 skipped; 1 stale assertion failed, fixed and independently rerun |
| Affected version/upgrade suite, unprivileged | 87 passed |
| Focused installer/package/hosting/admin regressions | 159 passed; final installer/refusal rerun: 20 passed |
| Login/setup browser and validator | 14 passed, including real HTTP/HTTPS first-use browsers |
| Nginx vhost/TLS/negative cases | 10 passed |
| Suspended login and acceptance harness regressions | 17 passed |
| Isolated PostgreSQL backup/recovery and migrations | 29 passed |
| Exact final archive PostgreSQL/HTTP/HTTPS | Passed all three PostgreSQL URL forms; migration, restart, login and TLS/SNI |
| Final VPS install, hosted enforcement and two reboots | Passed; reused Ubuntu OS, fresh Freo state |
| GitHub clean Python installation matrix | [Passed](https://github.com/3andB/freo/actions/runs/37932059102) |
| GitHub recovery workflow | [Passed on retry](https://github.com/3andB/freo/actions/runs/37933346306): 397 settings/artifact, 98 V1 boundary and 53 browser checks; PostgreSQL recovery passed |

The full backend run began before a stale version assertion was corrected; its
single failure is recorded rather than hidden. The affected version/upgrade
suite passed afterward as an unprivileged user. Other initial test-environment
failures (GPG sandbox sockets, incomplete interpreter, Nginx PATH, simulated
package queries and root-owned CI evidence) were diagnosed and corrected.
A CI runner that stalled during dependency setup was cancelled and retried;
the retry completed successfully, including browser and PostgreSQL recovery stages. Counts from separate runs overlap. The isolated PostgreSQL recovery/migration
suite subsequently exercised database cases skipped by the broad backend run. The 29 skips include opt-in PostgreSQL,
engine, ACL and soak fixtures, plus optional live-microphone dependencies absent
from the development test interpreter. The installed package includes and checks
those microphone dependencies; its microphone service passed the reboot checks.

On `Freo-v1-Test-1` (`209.38.64.12`), the final archive installed with a clean
environment. Removing the original staging path did not break administration;
a second install refused existing state without changing the environment.
Acceptance replaced the bootstrap password, created two stations through the
existing CLI, and read actual MP3 through Nginx and direct Icecast. Hosted tests
verified station/bitrate/storage/listener limits, actual 128 kbps encoding,
past-due broadcasting, suspension, maintenance, restart guards and activation.
Unprivileged administration, customer policy writes and an unapproved service
restart were refused.

Both actual reboots changed boot ID and retained installation identity. Active
streams returned automatically; suspended streams stayed stopped until explicit
activation. Login survived both reboots and the bootstrap password remained
revoked. The disposable fixture is healthy, with two test stations and custom
limits of 2 stations / 2 listeners / 128 kbps / 1 GB. Rebuild it before customer use.

## Handoff

Use [the RC1 installation and SSH contract](v1-rc1-installation.md). Freo World
owns verified installation and local enforcement; Studio owns infrastructure,
SSH dispatch/authentication and orchestration. No Studio compatibility is assumed
or certified. Pristine Ubuntu provisioning and Studio integration remain the
next acceptance steps.

Production 0.3.2, `main`, stable update metadata and production services were not
changed. No stable V1 release or production deployment was performed. Changes
were committed and pushed only to `develop/v1`.
