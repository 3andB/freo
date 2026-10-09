# Freo V1 Phase B installed acceptance — 8–9 October 2026

**Acceptance: final installed retest in progress.** This report is completed only
when the final candidate's installed checks finish. No production services or
databases, main branch, public release, or tag were changed.

## Source and environment

- Development: `/opt/freo-v1`, `develop/v1`, repository `3andB/freo`.
- Accepted Phase A: `946348bf49ab6c95ddaa03c4e237e4231fb600ba`;
  its installed runtime was `e6b8b47af908ecf7ad0a72f56a86a471274cbbad`.
- Official 0.3.2 source: `83200e6508654bea13f404e9d5699a8ad3eae19d`,
  schema `c83d4e5f9012`. The original official-kit installation and matched
  fixtures are documented in [Phase A acceptance](v1-upgrade-test-report-2026-10-08.md).
- Final Phase B runtime: `e90265dddd32eecd1d58484d4489eda114b1dc09`,
  private candidate `1.0.0-dev.2`, schema `fc06a1b2c3d4`.
  Subsequent changes are acceptance scripts, evidence, and documentation.
- Authorized trash server: `209.38.64.12`, `Freo-v1-Test-1`, Ubuntu 24.04.5
  x86_64, 2 vCPU, approximately 2 GB RAM plus swap, 58 GB disk. This is a
  disposable application/database installation on a reused VM, not an OS reimage.
- Actual Nginx, PostgreSQL, Icecast 2.5.0 and Liquidsoap 2.2.4 services were used.
  Icecast retains the Phase A iterator-lock correction and adds native global
  listener accounting and persistent broadcast inhibition. No streaming proxy,
  listener daemon, entitlement database, or external commercial API was added.

## Commands and repeatability

Candidates were built from clean pushed commits using the complete hashed
wheelhouse and signed with the existing private test key:

```sh
python scripts/build-release.py --candidate \
  --wheelhouse /root/freo-032-kit/source/wheels \
  --output /root/freo-phase-b-final2.tar.gz
gpg --homedir /root/freo-upgrade-signing --batch --yes --detach-sign \
  --output /root/freo-phase-b-final2.tar.gz.sig /root/freo-phase-b-final2.tar.gz

python -m freo_ops upgrade /root/freo-phase-b-final2.tar.gz \
  --signature /root/freo-phase-b-final2.tar.gz.sig \
  --keyring /root/freo-upgrade-signing/test.gpg --allow-candidate \
  --env-file /opt/freo/.env --backup /root/freo-phase-b/pre-final032-2.gpg \
  --verification-env-file /root/freo-upgrade-preservation/verification.env \
  --verification-directory /root/freo-phase-b/verify-final032-2 \
  --passphrase-file /root/freo-upgrade-preservation/passphrase

freo-admin hosting configure --plan starter
freo-admin hosting configure --plan pro
freo-admin hosting configure --plan custom --stations 3 --listeners 3 --bitrate 192 --storage-gb 1
freo-admin hosting suspend --reason acceptance-test
freo-admin hosting maintenance
freo-admin hosting past-due
freo-admin hosting activate
freo-admin hosting storage
freo-admin hosting verify
```

The actual Python executable was `/root/freo-upgrade-tool-venv/bin/python` for
building, offline recovery, upgrade orchestration, and test scripts. Installed
commands use the candidate's own virtualenv. Private credentials/passphrases were
read from protected files and are excluded from committed evidence.

Tests and their prerequisites are documented in
[tests/hosting_acceptance](../tests/hosting_acceptance/README.md). Tests that change
policy run sequentially. Clean upgrade repeats restore the verified matched
0.3.2 fixture, retaining displaced databases and host trees. After fixture
restoration, complete the baseline's public-schedule/statistics one-shot jobs
before preflight; stopping a running timer job can leave a transient failed unit.
No database row repairs or ignored migration failures are part of the procedure.

## Verified results

| Boundary | Installed observation |
| --- | --- |
| Aggregate listeners | Starter admitted exactly 100 of 116 simultaneous connections; Pro 250 of 266. Custom admitted 5 of 16 across two mounts through public Nginx and direct Icecast. |
| Listener reduction | Five existing sessions survived a reduction to three; new connections were refused until sessions drained. Reconnects and statistics at full capacity worked. |
| Station capacity | With three existing stations, ten concurrent PostgreSQL creations under Pro admitted seven and rejected three. Starter downgrade was refused without changing the active Pro policy. Synthetic stations were retired through supported lifecycle operations. |
| Bitrate | Actual encoded stream measured 128,000 bit/s. A conflicting 64 kbps plan reduction was rejected without altering the current plan. |
| Storage concurrency | Two installed 65,536-byte writers competing for 100,000 free quota bytes admitted one and rejected one. No quota overshoot. |
| HTTP uploads | First slow request reserved its Content-Length before body parsing; the overlapping upload returned structured quota rejection. Aborting released the reservation. A distinct real MP3 then ingested normally. |
| Database artwork | Exactly 15,000 persisted image bytes appeared in accounting. Growth while over quota was rejected; deleting the test asset still worked. |
| DJ recordings | Actual Liquidsoap recording stopped at quota, retained decodable partial MP3, and the public broadcast continued. A following recording completed normally; scoped DJ authentication, route permissions, playback, and mobile layout were exercised. |
| Service states | Past due retained audio. Suspension disconnected existing listeners, blocked public/direct new listeners and live ingress, and defeated direct service starts. Maintenance and reactivation were exercised. |
| Interruption/reboot | SIGKILL after writing inhibition but before stopping services still cut audio through native Icecast enforcement. Repeating suspend reconciled state. Actual reboot retained suspension; explicit activation restored audio. |
| Authority | Application identities could not write policy; non-root CLI exited 3, invalid arguments 2, missing policy 5. Missing policy blocked audio. Repair remained in maintenance until explicit activation. |
| Backup restoration | Actual attachment of the older pre-hosting Phase A backup retained destination suspension. Old web/audio services were blocked, and activation returned incompatible-release exit 6. Signed upgrade to compatible code retained suspension; activation reconciled accounting access and restored audio. |
| Phase A preservation | Original station IDs 1–3, two original accounts, all 18 media/artwork checksums, nine original environment keys, five station/engine secret files, custom media root, custom ingest override, settings, and historical records remained. The originally stopped station remained stopped. |
| Automated regressions | 133 policy/UI/installer/station/audio/upgrade checks and 63 media/import/production/artwork checks passed (196 total). |

The final candidate also passed installed self-hosted UI checks, actual 192 kbps
output, and 116 simultaneous listeners after ordinary Icecast transport tuning.
Hosting controls were absent and commercial suspension was refused. First hosted
enablement under root umask 077 passed with healthy audio. Two clean 0.3.2 upgrades
completed, the second using the final runtime. The remaining final hosted and
feature retests are still running.

## Corrections made during testing

- Reused existing station allocation locking and added transaction guards; the
  hosted form and overview now use assigned limits instead of legacy license UI.
- Used native Icecast admission slots across all mounts, with slot release on
  final client destruction. A persistent native inhibit closes the SIGKILL window.
- Fixed nested storage-root ACL traversal so worker identities can account for
  uploads and production media, including newly created station directories.
- Held image reservations through outer database commit, and passed reservation
  descriptors into bounded encoders so parent death cannot release capacity early.
- Changed quota-stopped recording output to drain its pipe until normal shutdown,
  preserving public audio and allowing the next recording.
- Made service guards and authority markers readable under root umask 077.
  Guards live outside customer application roots and reject older restored code.
- Allowed the exact managed Phase A production-storage override during the
  reviewed bridge; customer-customized overrides still require review. Suspended
  rendering avoids reloading stopped Icecast. Activation re-establishes accounting
  grants after database restoration and verifies application readiness.
- Under concurrent compiler/browser/regression load, one activation exceeded its
  health deadline and correctly retained maintenance. A subsequent verified
  activation passed. Workloads were separated on this small test VM.
- A restored timer job stopped by the fixture briefly retained failed state;
  preflight correctly refused it before backup/migration. The baseline job then
  completed normally and the unchanged upgrade was repeated. Upload harness CSRF
  and duplicate-input mistakes were corrected; these were not product failures.

## Operational limits

Hosted mode targets Freo's supported local PostgreSQL/systemd installation. It
rejects symlinked or unreadable media roots. Quota accounting includes temporary
headroom, so a write may require more free allowance than its final output size.
Recordings can lose the final incomplete encoded fragment when stopped at quota;
decodable partial media is retained. Listener reductions intentionally drain old
sessions. Capacity assignments do not guarantee VM CPU or network throughput.

System reserve is the greater of 1 GB or 5% on each involved filesystem. Unrelated
root processes can still exhaust a shared disk. Replacement infrastructure must
receive administrator authority before customer data is attached; customer backups
are never authoritative for hosting status. Restricted SSH provisioning belongs
to Studio. No billing, provider provisioning, AI chat, Phase C, or Phase D was built.

Sanitized acceptance evidence will be attached when the final installed run completes.
Integration: [Freo Studio command contract](freo-studio-hosting-integration.md).
