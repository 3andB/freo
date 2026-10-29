# Freo 1.0.1 installation

Ubuntu 24.04 x86_64, Python 3.12. Existing installations must use the signed upgrade workflow with a current verified encrypted backup; never run the fresh installer over existing state.

## Verify the handoff

Obtain these named files through the trusted release handoff:

- `freo-v1.0.1-install-kit.tar`
- `freo-v1.0.1-install-kit.tar.asc`
- `freo-v1.0.1-install-kit.sha256` and its `.asc` signature
- `publisher.gpg`

Confirm this publisher fingerprint through an independently trusted channel:

`B835B40E7E1A5838390256751AB72B63BEB716C3`

From an empty, root-owned staging directory, verify before extraction:

```sh
gpg --show-keys --with-fingerprint publisher.gpg
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.1-install-kit.tar.asc freo-v1.0.1-install-kit.tar
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.1-install-kit.sha256.asc freo-v1.0.1-install-kit.sha256
sha256sum --check freo-v1.0.1-install-kit.sha256
mkdir freo-kit
tar -xf freo-v1.0.1-install-kit.tar -C freo-kit
cd freo-kit
sha256sum --check SHA256SUMS
gpgv --keyring "$PWD/publisher.gpg" freo-v1.0.1.tar.gz.asc freo-v1.0.1.tar.gz
mkdir source
tar -xzf freo-v1.0.1.tar.gz -C source
```

Stop on any verification failure. Never execute an archive's own scripts to
authenticate it. The bundled wheels install offline with required hashes;
Ubuntu/Xiph system packages still need network access. Existing signed release files
must remain unchanged.

## Fresh installation

Use the fresh installer only on an empty, disposable Ubuntu 24.04 x86_64 VM.
Replace `YOUR_SERVER_PUBLIC_IP` with its public IPv4 address or hostname:

```sh
cd source
sudo env FREO_DOMAIN=YOUR_SERVER_PUBLIC_IP bash scripts/install.sh
sudo bash /opt/freo/scripts/validate-install.sh
sudo freo-admin status
sudo freo-admin health
```

For HTTPS, instead supply `FREO_DOMAIN=radio.example.com`,
`FREO_ENABLE_HTTPS=1` and `FREO_CERTBOT_EMAIL=operator@example.com` with actual
DNS, inbound ports and operator email. Supply `FREO_LIVE_MIC=1` if microphone
acceptance is required. The Studio release API requires HTTPS and independently
approved inventory and hash-only key configuration; ordinary installation does
not publish a release inventory or issue a Studio key.

The installer creates the first-use `admin` account with the documented
bootstrap password `IAmOnTheAir`. Complete setup immediately with an operator
email and private password. Reinstalling over existing customer data is refused;
use the verified backup/restore upgrade workflow instead.

Hosted Icecast needs matching libigloo headers/runtime >= 0.9.4. Preparation
selects a compatible pair from the signed scoped Xiph source, simulates the
build transaction without removals and checks the actual loaded library. Failed
dependency/build preparation preserves service health and does not publish
hosted policy. See [dependency troubleshooting](icecast-upgrade.md).

## Exact-kit acceptance

Record the kit/application digests, source commit, OS image and package/runtime
versions. Use the built kit without rebuilding during acceptance.

The installed acceptance helper changes only an explicitly confirmed disposable
installation. It claims setup and creates two generated-audio test stations.
Replace `YOUR_DISPOSABLE_HOSTNAME` with the exact output of `hostname`:

```sh
cd /opt/freo
sudo venv/bin/python scripts/accept-install.py fresh --confirm-hostname YOUR_DISPOSABLE_HOSTNAME
sudo venv/bin/python scripts/accept-install.py hosted --confirm-hostname YOUR_DISPOSABLE_HOSTNAME
```

Retain the root-only acceptance JSON under `/var/lib/freo-admin/rc1-acceptance`;
the historical directory name is part of the existing helper contract. Keep its
private credentials file out of public handoff evidence. Also decode the two
real streams with FFmpeg and verify the native listener cap across mounts.
Cold engine checks use bounded readiness; HTTP 200 or an active process alone
does not prove live audio.

Reboot the VM, then run the installed validator and administrative health and
hosting verification. Check persisted accounts, policy, programming/media and
desired station states, both decoded streams, service restart inhibition while
restricted, and explicit recovery after suspension/maintenance. Verify the
installer rerun refuses before changing state and dependency setup is repeatable.
HTTPS, microphone and signed-upgrade acceptance must be recorded separately
when required by the release's intended scope.

Existing installations use the [signed upgrade/recovery workflow](recovery-and-upgrades.md)
with a verified encrypted backup/restore. The
[RC1 restricted SSH contract](v1-rc1-installation.md) and
[Studio release API contract](studio-release-api.md) remain in force.

Publication, Studio inventory approval and deployment follow acceptance of
these exact publisher-signed bytes.

## Existing Ubuntu runtime conflicts

Icecast requires libigloo >= 0.9.4 at build time; Freo also probes the loaded
runtime before building. Matching development/runtime candidates are selected
dynamically (currently 0.9.5-1), rather than held to a permanent exact version.
APT metadata alone is insufficient: libigloo0t64 can own older shared objects
while libigloo0 is marked installed. The installer refuses this state before
installing dependencies or publishing hosted policy.

Inspect apt-cache policy, dpkg-query -S '*/libigloo.so.0*' and installed reverse
dependencies. Reproduce the transaction on disposable Ubuntu before repairing
an existing host. Any targeted removal of the conflicting t64 package requires
operator approval, no installed dependents, a reviewed simulation and recovery
backup. Never use forced overwrites or broad autoremove. Reinstall the selected
matching pair, rerun scripts/check-igloo.py and rebuild/restart Icecast under a
controlled maintenance window. Repeating dependency setup must pass unchanged.

For a managed layout, validate with scripts/validate-install.sh from the active
release; it selects /etc/freo/freo.env. FREO_ENV_FILE can explicitly select an
existing absolute configuration path. No duplicate secret file is required.

## Broadcast CPU priority

Playout, microphone and automation services use freo.slice with CPUWeight=1000.
The relative share protects broadcast clocks while CPU-heavy media or other
work runs. Idle CPU remains available to other services; this does not add CPU
capacity or impose a hard background quota. The installer installs the slice,
and the managed updater deploys it with the service templates. Validation checks
service membership and the active cgroup v2 cpu.weight after startup.

After an upgrade or reboot, systemctl show freo.slice --property=CPUWeight
should report 1000. Each managed broadcast service's Slice property must be
freo.slice. Run scripts/validate-install.sh and verify actual decoded stream
pacing under bounded concurrent CPU load. HTTP health alone cannot establish
that audio is delivered in real time.
