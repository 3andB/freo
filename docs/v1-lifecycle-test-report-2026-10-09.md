# Freo V1 Phase C lifecycle acceptance — 2026-10-09

**Acceptance: passed.** Phase C is implemented and verified on the disposable
installation. Final runtime tests included live restore, interruption, actual
reboot, preserved suspension, explicit reactivation and real streaming audio.

## Source and environment

| Item | Tested value |
| --- | --- |
| Official 0.3.2 source | `83200e6508654bea13f404e9d5699a8ad3eae19d` |
| Accepted Phase A | `946348bf49ab6c95ddaa03c4e237e4231fb600ba` |
| Accepted Phase B | `af7bedbb6f3725c651dc211a53c68abf80e8c0a5` |
| Legacy upgrade/interruption and unrestricted self-hosted runtime | `9d12917bdf037688512d816812458b85dd894d8f`, private `1.0.0-dev.11` |
| Final installed runtime | `8ef6c2c1f3615d2595c7d4b85f81c70107a9bb5f`, private `1.0.0-dev.12` |
| Final artifact SHA-256 | `25d3f9e4ae97d867f132a97d1bd1a9d77add9f3f339ae4afcc94662b2bcff49f` |
| Disposable host | `Freo-v1-Test-1`, `209.38.64.12`, Ubuntu 24.04.5 x86_64, 2 vCPU, 2 GB RAM plus swap, 58 GB filesystem |
| Services | Local PostgreSQL, systemd, Nginx, actual patched Icecast, Liquidsoap, microphone gateway and Freo workers |

Development remained on `/opt/freo-v1`, `develop/v1`. No release, tag, main merge,
or Phase D work was performed. Production application files, services and
databases were not changed. An installer test initially created unused local
administrative identity/runtime metadata outside its temporary fixture. The
fixture was corrected; those two entries were archived after confirming that
no production launcher or guards referenced them. The final automated run left
no `/var/lib/freo-admin` test state on the development host.

The final runtime changes only administrative restore attachment and the candidate
version relative to the preceding tested code. The final documentation commit
follows the runtime commit above; it is not a different tested binary.

## Implementation and commands

The existing `freo-admin` launcher now exposes installation status, health,
resources, backup lifecycle, signed upgrades and approved service operations.
It reuses Phase A's encrypted backup, isolated restore and signed updater, Phase B's
root policy/locking and the installed systemd units. No management API, daemon,
database, billing integration or commercial self-hosted interface was added.

Private candidates were built from clean pushed commits using the existing
wheelhouse, signed with the disposable verification key, and staged in the
root-owned layout in the [Studio contract](freo-studio-hosting-integration.md).
Publisher trust was provisioned independently. Candidate admission was enabled
only on the disposable installation. No private keys or customer secrets are in Git.

```sh
python scripts/build-release.py --candidate \
  --wheelhouse /root/freo-032-kit/source/wheels \
  --output /root/freo-phase-c/candidate-dev12.tar.gz

gpg --homedir /root/freo-upgrade-signing --batch --yes --detach-sign \
  /root/freo-phase-c/candidate-dev12.tar.gz

freo-admin status
freo-admin health
freo-admin resources
freo-admin services status
freo-admin services restart --service application
freo-admin services restart --service icecast
freo-admin services recover
freo-admin backup create
freo-admin backup list
freo-admin backup verify --id BACKUP_ID
freo-admin backup restore --id BACKUP_ID --confirm-installation INSTALLATION_ID
freo-admin upgrade check
freo-admin upgrade apply --version 1.0.0-dev.12
```

All lifecycle responses use JSON schema version 1, actual resulting state and
structured errors. Installed tests checked non-root denial, invalid services,
invalid versions/paths, wrong restore confirmation, inhibited restarts, completed
mutation verification and exit codes. The integration contract specifies the
allowlist, privileges, fields, timeouts, key escrow and recovery semantics.

## Installed results

- Signed Phase B → initial Phase C upgrade passed. Corrected complete lifecycle
  repetitions on private candidates dev.4 and dev.5 passed.
- A recovered clean 0.3.2 installation upgraded to dev.11 through the original
  signed updater, with migrations and actual audio healthy. Its root-only
  environment file retained its permissions.
- A real dev.11 updater was killed at the migration boundary. Generic recovery
  refused implicit database rollback. Explicitly confirmed CLI restore recovered
  0.3.2; the subsequent complete signed upgrade passed without database repairs.
- On dev.11, unrestricted self-hosting had no hosting UI, no hosting endpoint,
  no commercial suspension and no station/storage allowance. Actual streaming
  used 192 kbps and held 116 aggregate listeners across two mounts. Original
  transport settings were restored afterward. The final automated suite also
  verifies self-hosted behavior; dev.12 did not change those UI/audio paths.
- Signed dev.11 → dev.12 upgrade while suspended passed and remained
  `intentionally_suspended`; explicit activation restored healthy streaming.
- Final dev.12 completed the full lifecycle sequence: status/resources, deliberately
  failed ingest worker → degraded health → recovery, verified application and
  Icecast restarts, encrypted backup/create/list/verify and actual live restore.
  Restoring an older Starter backup into a suspended Custom destination preserved
  its exact policy, 5-listener allowance and 1 GB quota. Activation restored audio;
  eight held connections admitted exactly five.
- A second dev.12 restore was killed immediately after the old database was
  retained. A real reboot changed the boot ID. The exact suspended policy and
  persistent guards survived; direct Icecast/microphone/playout starts remained
  inhibited, port 8001 stayed closed and premature activation was refused.
  `services recover` completed to `intentionally_suspended`; explicit activation
  then returned healthy audio.
- After that recovery, 16 simultaneous public/direct listener connections across
  two mounts admitted 5 and rejected 11. Reducing the allowance to 3 preserved
  the five existing sessions, rejected growth and allowed reconnection after
  draining. Enforcement uses Phase B's native Icecast aggregate counter/limit.
- Concurrent 64 KiB storage writes with 100,000 bytes available admitted one and
  refused one. The actual unprivileged recording sink stopped at 65,536 bytes;
  its partial MP3 decoded. Reducing storage below usage preserved files and denied
  growth while broadcasting continued.
- The browser DJ test created a scoped account, checked forbidden routes, reached
  quota during an actual Liquidsoap show recording, and verified that broadcasting
  continued. A second recording completed; both decoded and a recording played
  in the browser. Storage uses the existing serialized byte accounting and bounded
  recording sink, including persistent media and artwork.
- Original users authenticated; all three stations' media, playlist, scheduling,
  history and statistics pages remained accessible. All three original album
  artworks were served. Scoped API access/revocation, listener requests and actual
  production/ingest workers passed.

- Scheduled imaging passed: all three converted legacy assets decoded, a legacy
  cart played and its migrated clock group reached actual playback. The original
  nine music files remained unchanged.
- A generated 1,000 Hz WebRTC microphone signal traversed the installed gateway,
  Liquidsoap and Icecast. Decoded audio measured 1,000 Hz and RMS 0.123; disconnect
  returned playout to AUTO.
- Final `upgrade check` authenticated all six cached candidates, reported older
  versions incompatible and dev.12 `already_installed`. It retained every existing
  release and removed its temporary copy. Final status, resources, service status
  and health passed; both public streams were healthy on the restored Starter plan.
  All 18 original media/artwork checksums were checked again after audio testing.

The post-reboot baseline comparison preserved station IDs 1–3, both original
accounts, all 18 original media/artwork checksums, nine environment keys, five
station secret files, the custom media root and ingest override. The third
station remained intentionally stopped. Historical started selections increased
from 16 to 139; original tables/relationships remained populated. No manual
schema or row repair was used.

## Automated tests and evidence

The final focused matrix passed **151 tests**, with **4 opt-in PostgreSQL skips**.
The separate real PostgreSQL recovery/migration matrix passed **13 tests**.
Coverage includes lifecycle authorization/arguments, policy isolation, signature
and compatibility validation, recovery journals, interrupted attachment, resource
reporting, installer guards, hosting behavior and quota concurrency.

Run disposable acceptance scripts with the provisioned test environment:

```sh
python tests/lifecycle_acceptance/check.py accepted-dev12
python tests/lifecycle_acceptance/restore_interrupt.py
python tests/lifecycle_acceptance/reboot_check.py before
# Reboot the disposable host, reconnect, then:
python tests/lifecycle_acceptance/reboot_check.py after
freo-admin services recover
freo-admin hosting activate
freo-admin health

python tests/hosting_acceptance/listeners.py
python tests/hosting_acceptance/storage.py
python tests/hosting_acceptance/dj-quota.py phasec-verified-dev12
python tests/upgrade_acceptance/features.py phasec-verified-dev12
python tests/upgrade_acceptance/imaging-check.py phasec-verified-dev12
python tests/upgrade_acceptance/mic.py phasec-verified-dev12
```

The interruption test and fixture requirements are documented in
[`tests/lifecycle_acceptance/README.md`](../tests/lifecycle_acceptance/README.md).
Root-private evidence is under `/root/freo-phase-c` and
`/root/freo-upgrade-tests/phasec-verified-dev12` on the disposable host. It includes
`accepted-dev12.json`, `interruption-dev11.log`, `upgrade-dev11.json`,
`upgrade-dev12-suspended.json`, `final-reboot-inhibition.json`,
`final-reboot-recovery.json`, `final-reactivation-health.json`, listener/storage
results, `final-upgrade-check.json`, `final-health.json`, `final-integrity.json`
and audio/browser artifacts. Private journals and credentials are not
published. A restored encrypted backup, signed final candidate and public key
were copied off-server and checksum-verified; encryption-key escrow was checked
separately without disclosure.

## Failures corrected and retested

- Closed PostgreSQL attachment-preflight sessions explicitly; transaction context
  managers alone did not close psycopg2 connections.
- Reconciled actual destination listener limits and the managed recording sink
  after customer restore, before starting audio.
- Installed verified administrative recovery tooling before the first migration;
  retained it across legacy restores and placed persistent guards outside restored
  `/etc` unit files. Legacy recovery now selects matched workers and desired stations.
- Accepted only exact trusted managed Icecast guards during legacy re-adoption;
  unsafe/customized overrides still fail. Missing V1-only directories are optional
  in untouched 0.3.2 inventory.
- Allowed systemd stop/start deadlines to finish and passed already-parsed settings
  to migration children without relaxing root-only environment permissions.
- Preserved `/etc/freo` and authority files continuously while attaching customer
  entries. Earlier testing caught a temporary older policy before reboot; focused
  injected-interruption tests and the final real interrupted restore/reboot passed.
- Added expansion-size/space checks, safe pre-journal recovery and compatibility
  reporting for cached older candidates. Successful temporary preflights are removed.
- Actual low-space preflight refused a restore before changes. Redundant completed
  test staging was archived and verified off-server before removal; the full
  sequence then passed. Space protection was not weakened.
- Isolated filesystem-writing installer fixtures and made quota unit-test disk
  budgets explicit, while retaining dedicated low-space rejection tests and real
  installed disk checks. Corrected the listener test to retain HTTP responses.

## Operational limits

Backups are full encrypted copies with a maintenance window, substantial staging
space and administrator-managed retention. Current preflight budgets six times
inventory plus 1 GB, including selected uncompressed backup size for live restore.
Recovery capacity is separate from customer media allowances. There is no
incremental backup or automatic deletion. Escrow the key separately.

Live attachment supports approved same-installation backups and the existing local
PostgreSQL deployment with matching ownership, paths and connection mapping.
Cross-host migration, external PostgreSQL, old unregistered backup catalogs and
custom recording callbacks require reviewed recovery procedures. Destination
PostgreSQL/TLS settings and root hosting authority are not blindly replaced.

Studio must stage independently signed artifacts and supply restricted SSH and
explicit restore authorization. Freo accepts no arbitrary URL, executable or unit
name. A disconnect is not success and an interrupted migration is not authority
to overwrite later writes. Recovery retains displaced data and reports actual state.
