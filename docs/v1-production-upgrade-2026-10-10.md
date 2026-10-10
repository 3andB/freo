# Freo World V1 production upgrade — 10 October 2026

Production runs `1.0.0-rc.4`; the direct upgrade, full installation validator,
public HTTPS, original streams and release API passed. The exact candidate also
passed an isolated current-data upgrade and reboot. Live World reboot verification
is pending and will run automatically after the authorized reboot.

The operator explicitly authorized this in-place production upgrade after the
original RC1 preparation scope. The stable main source and 0.3.2 release artifacts
remain intact. No stable V1 tag/release was published, and Studio was not modified.

## Signed candidate

- Source: `913beb4020f50450da9094720d23a70d29c2b053` on `develop/v1`.
- Inner archive SHA-256: `d3e9af4160dac2d7148a142bc030b4867264c3291cdc01372e3bfdbbd9278079`.
- Outer kit SHA-256: `83004917ba03654f26cfc879d8efa09c3f353cab7137e3dee6f013a6703541b9`.
- Independently pinned publisher fingerprint: `B835B40E7E1A5838390256751AB72B63BEB716C3`.
- Both detached signatures verified; all 587 payload files verified.
- Existing locked offline Python wheels; Ubuntu 24.04 x86_64 / Python 3.12.
- Schema: `fc06a1b2c3d4`.

Only RC4 is approved in the existing `/srv/freo-studio/approved-releases.json`.
Earlier immutable candidate files remain staged, with the known defective
candidates withdrawn from the download inventory. No second staging system was
created. The native Icecast executable uses the existing side-by-side engine
path; the package executable and stable tracked source were not rewritten.

## Blockers found and fixed

RC2 starved prepared microphones when several stations made a worker cycle
roughly nine seconds long, exceeding the unchanged six-second engine safety
lease. RC3 synchronizes prepared sessions between station work and shortens the
existing worker delay while a microphone is prepared. The same authorization,
lease and fallback checks remain; no new worker daemon was added.

The World RC3 attempt then stopped before database migration: runtime libigloo
0.9.5 was paired with Ubuntu 0.9.2 headers because repository preferences excluded
matching Xiph development headers. The updater automatically resumed the original
0.3.2 services with the old schema and runtime pointer intact. RC4 narrowly admits
`libigloo-dev` alongside the existing runtime and applies the fresh installer's
same fingerprint-checked repository helper before native dependency resolution,
after a verified recovery point. Unrelated Xiph packages remain blocked.

APT with an empty installed-package status selects libigloo runtime/headers 0.9.5
and Icecast 2.5. The clone deliberately reproduced 0.9.2 headers; the exact RC4
updater automatically replaced them and completed the pinned-source native build.
The signed manifest also permits the existing V1 schema as an upgrade source.

The conservative disk guard was retained. Clone preflight refused insufficient
space before maintenance. Named inactive test trees were encrypted and compared
exactly before their duplicates were removed; original encrypted backups and all
databases were retained. On World, verified inactive source-only preflight copies
and exited disposable browser test profiles were reclaimed.

## Passed checks

| Scope | Result |
| --- | --- |
| Automated baseline and regression runs | 339 distinct passed, four skipped, no unresolved failures; runs overlap |
| Focused RC4 version/installer/bundle/API suites | 91 passed |
| Focused installer/upgrade safety suites | 46 passed; overlaps the preceding suite |
| Direct current-data 0.3.2 to exact RC4 clone upgrade | Passed with fresh encrypted backup and verified restore |
| Original records/files/configuration | Both stations/accounts and credential hashes, settings, 38 media/secret files and 12 original environment values preserved |
| Installed payload/schema/dependencies | All 587 signed files, schema head and pip/native dependency checks passed |
| Clone authentication/station creation | Actual HTTPS password login and new station creation/start passed |
| Clone microphone | Real WebRTC 1,000 Hz tone decoded; abrupt disconnect returned to AUTO |
| Native browser | Eight login/admin/mobile/public-player checks passed |
| Clone reboot | Changed boot ID, normal enabled services, preserved data and both decoded streams passed; microphone and release API passed again after boot |
| Production upgrade | Exact RC4 updater completed; fresh pre-migration encrypted backup restored and verified |
| Production application/database/services | Full installer assertions, `freo-admin health`, self-hosted enforcement and public HTTPS readiness passed; no failed services |
| Production streams/login | Both original HTTPS MP3 streams decoded; Nginx/TLS login and session-cookie checks passed |
| Production release API | All five download hashes, authentication, revocation and allowlisting passed; original Hosting Manager key preserved |
| Fresh off-host recovery | User-approved encrypted copy to the existing trusted test host; transport hash, decryption, all 5,545 payload entries and database-dump hash verified |

The four skipped cases require opt-in test facilities. Real installed microphone
and streaming checks were run separately. Original root-fixture/PostgreSQL-port
invocation failures were corrected and passing evidence retained. The initial
RC2 microphone failure and RC3 pre-migration header failure are resolved above.
Browser checks do not establish physical microphone or Safari compatibility.
Production customer passwords were not reset; actual password login and station
creation were tested on the isolated clone.

The full fresh-install validator was run against the upgraded layout with eight
environment-path substitutions to `/etc/freo/freo.env` in a private operator copy.
Its assertions were unchanged and signed runtime files were not edited.
Icecast and the original station instances are enabled for boot, alongside the
application, workers and existing timers. Detailed evidence and encrypted local
recovery points are root-private under `/var/backups/freo/v1-cutover-20261010`.
The fresh encrypted off-host recovery copy is in a root-private directory on the
already trusted test host; recovery secrets are not release materials.

## Studio handoff

The API is live at `https://freo.world/api/studio`. Use the existing **Freo Studio
Hosting Manager** key from Studio's secret store as an HTTPS Bearer header. World
keeps only its hash; it was preserved and cannot be displayed again from storage.

1. Fetch `/health` and `/releases`, then `/releases/1.0.0-rc.4/manifest`.
2. Download the kit and the four support roles, verify every manifest SHA-256,
   both publisher signatures, and the inner signed payload before execution.
3. Use the [RC4 package instructions](v1-rc4-installation.md) and existing
   [restricted SSH command contract](v1-rc1-installation.md) to install,
   configure hosted mode, verify and manage services on an authorized target.

The [release API contract](studio-release-api.md) defines exact roles and errors.
World owns the installer, supported commands and local enforcement. Studio owns
provisioning, SSH authentication/dispatch and orchestration; no implemented or
compatible Studio dispatcher is assumed. The same distribution supports both
self-hosted and hosted operation. This API cannot manage a server.

Studio's supplied host fingerprint was matched, but World's existing SSH identity
was refused by Studio. No SSH security settings or credentials were changed to
force access. The live API supplies the signed materials without that transfer.
On versioned installations, the key operator script is
`/opt/freo/current/scripts/studio-api-key.py`; the API document also handles the
fresh flat installer layout. `freo-admin health` and `freo-admin hosting verify`
work with both layouts.

## Live reboot verification

Rebooting this World host disconnects the current Codex SSH process. All other
work is completed first. The bounded one-shot `freo-v1-cutover-verify.service`
checks a changed boot ID, signed files, preserved data, health, enforcement,
enabled services and both decoded streams after boot. Its marker is removed when
finished, so it does not run on subsequent boots. The same check passed on the
exact RC4 clone. A bounded external observer records HTTPS outage and recovery
on the trusted test host; neither is a management daemon.

After reconnecting, read the authoritative live result:

```sh
cat /var/backups/freo/v1-cutover-20261010/production-after-reboot.json
freo-admin health
freo-admin hosting verify
```

Readiness: RC4 is ready for a fresh Ubuntu 24.04 installation test and has passed
the authorized World upgrade. Do not treat pending live World postboot verification
as an observed pass; use the report above after the reboot.
