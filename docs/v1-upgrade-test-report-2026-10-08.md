# Freo 0.3.2 → V1 upgrade acceptance, 8 October 2026

**Status: ACCEPTED for the tested installation profile. Two complete upgrades
from clean 0.3.2 baselines passed using the final runtime code, without manual
row repairs or undocumented intervention.** Private candidate testing only; no public release,
tag, merge to main, production change or hosting-management work.

## Source, target and environment

- Official v0.3.2: `83200e6508654bea13f404e9d5699a8ad3eae19d`, schema
  `c83d4e5f9012`. Official kit SHA-256:
  `2488f8784243fd5bfed4116ea4aff6c0ee6b15f619361379650b7405a269b91a`.
  Publisher signature verified against fingerprint
  `B835B40E7E1A5838390256751AB72B63BEB716C3`.
- Final V1 payload: `e6b8b47af908ecf7ad0a72f56a86a471274cbbad`,
  `1.0.0-dev.1`, schema `fc06a1b2c3d4`.
  Candidate 7 SHA-256:
  `4ba428aae8c1161a762375b4818baad7b5166ea65db68d7cecbc25a3c5b08149`.
  Built with the complete hashed wheelhouse, validated in an empty virtualenv,
  privately signed and explicitly accepted using `--allow-candidate`.
  Later commits contain test/documentation updates, not changed runtime payload.
- Trash server `209.38.64.12`, hostname `Freo-v1-Test-1`, Ubuntu 24.04.5
  x86_64, 2 vCPU, approximately 2 GB RAM plus swap. User confirmed disposable
  reuse. The old test installation, dirty review checkout and evidence were
  encrypted, restored for verification and retained before reuse; an encrypted
  copy and Git bundle were also saved off-server. Unique review work was saved
  under `docs/audits/v1-legacy-*` and pushed.
- This was a fresh application/database install on the recycled VM, **not an OS
  reimage**. Source installation used the official kit's normal installer.
  Every repeat started from a verified matched 0.3.2 backup. Displaced databases
  and host trees were retained, with no dropped database or manual row repair.

## Commands actually exercised

```bash
cd /root/freo-032-kit/source
FREO_DOMAIN=209.38.64.12 FREO_LIVE_MIC=1 bash scripts/install.sh

cd /root/freo-v1-source
/root/freo-upgrade-tool-venv/bin/python scripts/build-release.py --candidate \
  --wheelhouse /root/freo-032-kit/source/wheels \
  --output /root/freo-v1-candidate-7.tar.gz
gpg --homedir /root/freo-upgrade-signing --batch --yes --detach-sign \
  --output /root/freo-v1-candidate-7.tar.gz.sig /root/freo-v1-candidate-7.tar.gz

/root/freo-upgrade-tool-venv/bin/python -m freo_ops upgrade \
  /root/freo-v1-candidate-7.tar.gz \
  --signature /root/freo-v1-candidate-7.tar.gz.sig \
  --keyring /root/freo-upgrade-signing/test.gpg --allow-candidate \
  --env-file /opt/freo/.env --backup /root/freo-upgrade-tests/pre-final1.gpg \
  --verification-env-file /root/freo-upgrade-preservation/verification.env \
  --verification-directory /root/freo-upgrade-tests/restore-final1 \
  --passphrase-file /root/freo-upgrade-preservation/passphrase
```

The repeat uses `pre-final2.gpg` and `restore-final2`. Native Chromium completed
initial administrator setup, uploaded actual MP3/AAC files and observed playback.
The [saved harness](../tests/upgrade_acceptance/README.md) records population,
verification, interruption and attachment commands. Private evidence resides in
`/root/freo-upgrade-tests`; selected sanitized results are committed in
[audits/v1-upgrade-2026-10-08.json](audits/v1-upgrade-2026-10-08.json).

## Baseline and verification

| Check | Original baseline | Verified after each final upgrade |
| --- | --- | --- |
| Stations | IDs 1, 2, 3; two running, one stopped | Same IDs, settings and running/stopped states |
| Audio/artwork | 9 music tracks, 3 imaging assets, 3 album covers; 18 files | All 18 hashes match; 3 verified conversion copies added |
| Programming | 12 playlists, 9 members, 3 rotations, 3 clocks, 21 assignments, 3 imaging groups | All retained; 3 converted playlists added; imaging cart and scheduled group played |
| Users/configuration | 2 original accounts, 9 environment keys, 5 secret files | Both old logins work; original values and secret bytes match |
| History/analytics | 16 confirmed starts, 43 statistic buckets, 80 samples | Starts 92/93; buckets 111/119; samples 304/308; exports work |
| Storage | `/srv/freo-upgrade-media`, custom ingest override | Same root and override; originals, artwork and new recordings accessible |

The updater compares all pre-existing database rows' original columns and
sequences against its restored recovery point before the explicit Imaging
conversion. Legacy records/files remain; the converter maps carts, schedules
and history to corresponding V1 tracks/playlists. Existing music keeps its
identity/classification even when its bytes duplicate legacy imaging.
Independent checks then compare original media hashes, settings, users and
station states, and exercise actual application/engine behavior.

Installed tests include original logins; station pages, schedules, history and
analytics exports; all original artwork responses; rotated/automated playback;
converted imaging in a live cart and existing scheduled clock; scoped DJ and
API permissions; API revocation; listener-request submission; voice-track
production and ingest; two recorded deck shows decoded by FFmpeg and played in
Chromium; generated 1000 Hz WebRTC audio through the installed mic gateway,
Liquidsoap and Icecast; and disconnect returning to AUTO.

## Failures corrected and recovery demonstrated

- The first custom-storage fixture had an unhealthy ingest override: its
  `ReadWritePaths` list needed resetting before specifying the moved media root.
  Corrected the fixture and added a preflight guard against failed/restarting
  baseline services. This was a fixture defect, not lost upgrade data.
- Actual V1 startup exposed missing `/var/lib/freo/bulletins`; provision it with
  the installed service ownership/mode. Also provision production/recordings,
  honor custom upload roots and saved microphone enablement, and install missing
  V1 units. Added regression coverage.
- Expanded imaging acceptance exposed the uninvoked legacy converter. Invoke it
  during guarded maintenance; preserve original music when checksums duplicate
  imaging, using a narrow partial uniqueness index for legacy conversions.
  Regression covers identity, bytes, classification, carts/groups and reruns.
- Preserve matched old source/venv in each backup, retain prior terminal journals
  on no-op/retry, reject customized runtime files and source/schema mismatch.
- Harness corrections: action-specific CSRF tokens, configured HTTP Host, and
  allowance for Icecast's buffered audio before measuring microphone frequency.
  No application database repair was used to make acceptance pass.

Earlier candidate 5 (`78ec08c`) completed migrations, original-data checks,
production, DJ recordings and mic playback. It was not counted as final imaging
acceptance. Its actual pre-upgrade backup was restored and original login,
checksums and automatic playback verified.

Candidate 6 (`f829887`) was deliberately killed with SIGKILL immediately after
real database migrations, before activation. The journal remained `migration`,
its maintenance marker remained, and another upgrade refused. A real reboot
confirmed **zero active Freo units across 17 services/timers**. Its own verified
`pre-interruption.gpg` restored matched 0.3.2 code, venv, database, media and
configuration; both old logins, all 18 hashes, all station pages, two decoded
streams and Chromium automatic handoff passed. Temporary test tooling removed
by reboot was recreated outside `/tmp`; the self-contained application backup
was sufficient to restore the installation.

Final candidate `final1` was restored from its own `pre-final1.gpg`; both old
logins, all hashes, all station pages and two decoded streams passed on 0.3.2.
That matched baseline then completed `final2`. The off-server backup checksum is
`5cb60355f68de52c4b05211fee84c53ef22ef1f1972ef12e8f73e171b69fe428`.
Encrypted backups, the matched candidate and Git bundles are retained in the
private off-server `/root/freo-v1-upgrade-archive-20261008` directory.
Identical-candidate reapplication returned `already_installed` and preserved
the prior completed journal.

## Acceptance and limits

Focused upgrade/release/imaging regressions: **60 passed**. Isolated real
PostgreSQL recovery/migration regressions: **29 passed**. Installer/migration-head
checks: **6 passed**. Real patched-Icecast checks: **2 passed** (listener polling with five reloads,
and decoded MP3/AAC-LC at 128 kbps). The strengthened existing-clock/queued-audio
relationship regression also passed after its final test-only update.

| Run | Completed operation | Result |
| --- | --- | --- |
| `final1` | `c9021cdc44194b58b395470392c5d0cf` | Full data, imaging, HTTP, DJ/recordings and microphone acceptance passed |
| `final2` | `75d8d9a06661452b957a9ab20f8a13f0` | Same complete checks passed from restored clean 0.3.2 |

Final `/ready` reports `ok`; no failed systemd units or maintenance marker remain.
An off-server HTTP check received 200 from the home page and 8,192 audio bytes
from each running public stream. The third station remains intentionally stopped.

Scope is the tested standard Ubuntu/local-PostgreSQL installation and reviewed
custom-storage override. Recovery is a demonstrated explicit restore-and-attach
procedure, not automatic database downgrade. Synthetic audio exercises the real
services; physical microphone hardware, remote NAT/TURN, external HTTPS, paid
AI providers and public release distribution were not certified. Request
submission was exercised; request-to-playback latency was not an acceptance
claim. Backups, keys and raw private logs remain outside Git. Production `/opt/freo`
was not modified; all development is on `develop/v1`.
