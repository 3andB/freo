# Icecast 2.5 upgrade

On 2026-09-17 this Ubuntu 24.04 installation was upgraded from Icecast `2.4.4-4build4` to Xiph's `2.5.0-1`. Liquidsoap remains `2.2.4-1`. The statistics workspace and geographic collector are separate planned work.

## Packages and configuration

The package source is the [official Xiph repository linked by Icecast](https://icecast.org/download/), specifically `https://download.opensuse.org/repositories/multimedia:/xiph/xUbuntu_24.04/`. `scripts/configure-icecast-repository.sh` configures its dedicated key and preferences on supported Ubuntu 24.04 amd64/arm64 machines. The expected signing fingerprint is `0E313DB7936B4E76E720065B77EC2301F23C6AA3`; APT verifies repository signatures and package hashes. Preferences select Icecast `2.5.*`, `libigloo0`, and `libigloo-dev`, rejecting other packages from this repository. The historical September upgrade did not upgrade other existing system packages.

## Hosted build dependencies

Icecast 2.5.0's build requires the `igloo` pkg-config module at version **0.9.4 or newer**. A working packaged runtime does not prove compatible headers are installed. Ubuntu 24.04 provides `libigloo-dev 0.9.2-1.1build1`, depending on `libigloo0t64` at exactly that version. Xiph provides `libigloo-dev 0.9.5-1`, depending on `libigloo0` at exactly `0.9.5-1`. The former pin allowed only `libigloo0`; its catch-all rejection excluded Xiph's development package and APT selected Ubuntu's older headers.

The corrected rule gives only `libigloo0 libigloo-dev` the existing Xiph priority of 700. The repository-wide priority stays -1. Shared hosted-enable/upgrade preparation refreshes the signed repository, checks both APT candidates against minimum 0.9.4 and requires a matching pair. It simulates the build-dependency transaction with `--no-remove` before installing the resolved pair, then verifies both the pkg-config module and the loaded shared library. It does not run a distribution upgrade, force held packages, request automatic needrestart service restarts, or publish hosted policy on dependency/build failure.

Ubuntu's `libigloo0t64` declares `Replaces: libigloo0`: an earlier bad installation can leave 0.9.2 shared-library files even when dpkg reports Xiph's runtime package installed and pkg-config reports newer headers. `scripts/check-igloo.py` calls the actual shared library's version API and rejects that mismatch before a build. Do not force file overwrites or remove packages automatically; reconcile such an existing installation separately, or use a fresh disposable installation for acceptance.

The minimum is a build requirement; `0.9.5-1` is not permanently hard-coded. Only the versions resolved for this transaction are exact-pinned, allowing future compatible package revisions. Customized pins or holds that prevent a compatible pair produce an actionable failure. Repository/network/install errors also fail closed; a failed APT installation may have installed some build dependencies but does not activate Icecast or hosting.

Inspect a failed setup with:

```sh
apt-cache policy libigloo-dev libigloo0
apt-mark showhold
cat /etc/apt/preferences.d/freo-icecast
pkg-config --modversion igloo
dpkg-query -S '*/libigloo.so.0*'
# From the verified source/runtime directory:
python3 scripts/check-igloo.py
```

Resolve the reported repository, pin, hold, or dependency conflict and rerun `freo-admin hosting configure` with the approved plan. Dependency preparation is repeatable: an already compatible pair remains installed. The fresh installer still refuses existing Freo installations; use the upgrade path for populated hosts.

This source fix requires a **new version** of the application archive and installation kit, rebuilt and signed with updated manifests/checksums and acceptance evidence. Update Studio's approved inventory to the new immutable files. Never edit or overwrite signed RC artifacts.

The refreshed repository key has the same fingerprint as Icecast's independently hosted key, with its expiry extended to 2028. The copy at `icecast.org/multimedia-obs.key` was expired during this upgrade, so use the fingerprint-checked repository key.

Icecast's 2.5 package requires `/var/log/icecast2` in its post-install script but does not ship the old package's directory. During an upgrade, dpkg removes the directory if empty. The installer now creates `.freo-keep` there before upgrading to preserve it. Runtime logging still goes to the journal.

The native Freo systemd unit continues to run `/usr/bin/icecast2 -c /etc/freo/radio/icecast.xml` as `icecast2:icecast`, bound only to `127.0.0.1:8001`. Existing credentials and mount passwords were preserved. No changes to media or database schema were needed.

The Icecast socket trusts only the virtual local Nginx proxy. Stream snippets overwrite `X-Forwarded-For` with `$remote_addr`. This enables client geography without trusting headers supplied by public callers. See [Xiph listen-socket documentation](https://wiki.xiph.org/Icecast_Server/Listen_Sockets). Never expose the Icecast backend or its admin credentials to the browser. A future CDN/proxy needs an explicit Nginx trusted real-IP configuration.

## Validation

Before the live upgrade, the downloaded 2.5 executable and dependencies streamed generated MP3 audio on an isolated loopback port and reported a test forwarded address correctly. Repository signatures and package checksums were verified. The standalone preflight process exceeded its shutdown timeout; cleanup was confined to the isolated test environment, and this was not used as proof of service shutdown behavior.

After installation, verify the actual running server through `/status-json.xsl`, not just `icecast2 -v`. Validate both `freo-demo` and `freo-test` with a bounded audio read, public HTTPS playback, `/health/icecast`, `/health/playout`, `/health/stream`, and private `listclients` while holding a test connection. A forged public `X-Forwarded-For` must not become the reported listener address. The backend must remain loopback-only and `dpkg --audit` must be empty.

These live checks passed after the upgrade: 8,192 audio bytes read from each public HTTPS stream, all three public health endpoints healthy, real listener addresses reported, forged forwarding headers rejected, backend listening only on loopback, and a clean package audit. The existing health/booth/station/domain tests passed (65 tests), as did the opt-in isolated two-channel Icecast/Liquidsoap lifecycle test (1 test).

Existing playout units use `Requires=icecast2.service`. Record active units before stopping/restarting Icecast and explicitly start those same units afterward. Do not start intentionally stopped channels. Package-triggered restarts were temporarily suppressed during this upgrade, and that temporary policy was removed afterward.

## Rollback for this installation

The restricted backup is `/var/backups/freo/icecast-2.5-20260917T024353Z/`. It contains the previous Ubuntu package, a configuration archive, the previously active playout unit list and mount list, and package operation logs. The configuration archive contains credentials; keep it root-only and never commit it.

For a rollback, schedule a stream interruption, suppress package-triggered restarts for the operation, install the saved `icecast2_2.4.4-4build4_amd64.deb` with explicit `--allow-downgrades`, and restore the saved Icecast and Nginx configuration before restarting. Version 2.4 must receive the old configuration without the 2.5 virtual socket. Restore any preexisting package-service policy, run `nginx -t`, reload Nginx, restart Icecast and start only the playout units recorded in `state.json`. Repeat the public audio and health checks.

Disable the managed Xiph source/preferences when staying on the old version, otherwise a later APT upgrade can select 2.5 again. Revert the corresponding repository templates before provisioning an old engine. Extra `libigloo0`/`librhash0` libraries can remain installed during rollback; avoid unrelated autoremove operations.

This historical record covers the existing installation upgrade. The libigloo correction and shared cold-start readiness budget passed a new private-candidate installation on a clean Ubuntu 24.04 filesystem, including two real Liquidsoap streams, hosting limits, suspension, maintenance, both reactivations and guest cold boot. The source repository retains the dated validation reports and evidence references. Acceptance of the new publisher-signed kit on the release VM remains required before publication.
