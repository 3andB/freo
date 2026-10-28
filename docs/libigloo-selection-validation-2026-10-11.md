# Libigloo installer fix — 11 October 2026

Historical record: the two-Liquidsoap startup and hosted reactivation failures
below are resolved by the [12 October follow-up](libigloo-readiness-validation-2026-10-12.md).
Original failed checks and their evidence remain recorded here.

## Confirmed cause and source change

[Studio's RC2 acceptance record](https://github.com/3andB/freo-studio-host-manager/blob/main/docs/rc2-live-install-acceptance.md)
records Ubuntu 24.04 headers at 0.9.2, failure before publishing hosted policy,
and successful hosting acceptance after installing `libigloo-dev=0.9.5-1`.
Read-only package history from the retained Freo-v1-Test-1 VPS independently
records Ubuntu `0.9.2-1.1build1` development/runtime selection followed by that
explicit development-package upgrade. Those are historical installations,
not new acceptance runs for this fix.

The installer allowed Xiph `libigloo0` at priority 700 but omitted
`libigloo-dev`, leaving its repository version at the catch-all priority -1.
Ubuntu's development package at priority 500 therefore won. Icecast 2.5.0
requires pkg-config igloo >= 0.9.4. Xiph's 0.9.5 development package depends
on exactly `libigloo0=0.9.5-1`; Ubuntu's 0.9.2 package instead depends on
`libigloo0t64=0.9.2-1.1build1`.

The source fix permits only the missing development package at the existing
runtime priority. Shared hosted-enable/upgrade preparation configures that
signed source before resolving candidates, requires a matching pair >= 0.9.4,
simulates the build transaction without removals, installs the resolved pair,
and verifies both headers and the actual loaded runtime before building.
It leaves the repository-wide rejection and Icecast version rule intact.
See [installation troubleshooting](icecast-upgrade.md#hosted-build-dependencies).

Read-only inspection also reproduced headers at 0.9.5 with a loaded runtime
at 0.9.2: Ubuntu's `libigloo0t64` can replace the runtime library files.
The new runtime probe rejects that state, even if dpkg still reports
`libigloo0=0.9.5-1`. No automatic package removal or forced overwrite is added.

## Changed files

| File | Change |
| --- | --- |
| `scripts/configure-icecast-repository.sh` | Allow the development package at the existing runtime-only Xiph priority. |
| `freo_ops/v1.py` | Shared minimum-version/pair selection, strict repository refresh, simulation and no-removal install, header/runtime preflight. |
| `scripts/check-igloo.py` | Probe the version of the actual loaded shared library. |
| `scripts/build-icecast-2.5.sh` | Check headers and runtime before creating the build directory. |
| `freo_ops/hosting_admin.py` | Actionable dependency error before engine activation or hosted policy publication. |
| `freo_ops/inventory.py` | Include the runtime probe in application and installer artifacts. |
| `tests/test_icecast_dependencies.py` | Focused APT selection, runtime and safe failure regressions. |
| `docs/installation.md`, `docs/icecast-upgrade.md` | Installation requirements and operator troubleshooting. |
| This report | Record root cause, checks, limitations and release requirements. |

## Completed validation

- **Real clean Ubuntu 24.04 package installation and Icecast build:** on the
  explicitly authorized disposable Freo-v1-Test-1 VPS, a separate Ubuntu Base
  24.04.5 amd64 filesystem was verified against Ubuntu's signed checksums.
  Genuine signed APT metadata reproduced the old 0.9.2 development/runtime
  selection. The fixed dependency helper simulated and installed Xiph
  `libigloo-dev=0.9.5-1` and `libigloo0=0.9.5-1`. Rerunning it left the entire
  dpkg status file byte-identical. The unchanged Icecast 2.5.0 source checksum
  was verified, both Freo patches applied without fuzz, compilation succeeded,
  all linked libraries resolved, and `icecast -V` reported actual runtime
  `libigloo/0.9.5`.
- **Real full source installer:** the same separate filesystem booted with
  systemd in private PID, mount and network namespaces. The complete source at
  commit `7f3388b` passed `scripts/install.sh`, including real PostgreSQL
  migrations, service/database readiness, Nginx and first-login validation.
  Xiph Icecast `2.5.0-1`, Ubuntu Liquidsoap `2.2.4-1` and FFmpeg
  `7:6.1.1-3ubuntu5` were installed. The guest's network access for installation
  used a fixture-only Unix-socket proxy; existing VPS services and host APT
  configuration were untouched.

- **Real first-hosting dependency failure:** an intentionally unavailable local
  APT source caused strict repository refresh to fail. The actual root-run
  `freo-admin hosting configure` returned `icecast_dependencies_unavailable`
  with troubleshooting commands and `state.hosted=false`. The self-hosted
  policy and Icecast XML remained byte-identical, no hosted-enabled marker was
  written, both services stayed active and `/ready` remained healthy. The
  fixture's unavailable source was removed before the successful attempt.
- **Real first hosted activation:** the actual CLI built Icecast again from the
  verified archive through the fixed preparation path, activated the private
  engine, and successfully verified custom limits of three stations, two
  listeners, 128 kbps and 1 GB storage using real PostgreSQL and systemd.
- **Real streaming and hosting enforcement:** one Freo/Liquidsoap station
  streamed MP3 through Nginx at configured 128 kbps. A second actual Icecast
  mount received generated 128 kbps MP3 from FFmpeg. Two simultaneous listeners
  across the mounts received real audio; a third received HTTP 503. Actual
  database/policy operations rejected a fourth station, bitrate 192 above the
  128 kbps allowance, and a 2 GiB storage reservation above the 1 GB allowance.
  Storage accounting used real PostgreSQL; no large media upload was allocated.
  Actual suspension succeeded and verified that the backend stopped.
- **Real APT, real cached signed-repository metadata, empty installed-package
  state:** old preferences select Ubuntu `libigloo-dev` and `libigloo0t64`
  `0.9.2-1.1build1`; corrected preferences select Xiph `libigloo-dev` and
  `libigloo0` `0.9.5-1`. Both transactions were simulated, with no package
  installation or host APT configuration changes.
- **Real APT, synthetic isolated repository metadata:** regression reproduces
  both selections and confirms unrelated Xiph packages remain unavailable.
  This tests resolver behavior, not repository availability or installation.
- **Real dynamic loading of synthetic shared libraries:** runtime checks reject
  0.9.2 and accept 0.9.4/0.9.5. The probe also rejected the actual inspected
  0.9.2 runtime without modifying any installed library.
- **Mocked command/hosting failures:** missing/old/mismatched candidates,
  repository update, transaction simulation, installation, header validation,
  runtime validation and build failure preserve the previous hosting policy.
  No failed engine is activated; first-enable failures perform no service mutation.
- **135 unique regression cases passed (32 focused cases rerun after approval):** focused dependencies/hosting/V1
  upgrade, lifecycle/UI, source installer guards, and release inventory/signature
  checks. The GnuPG test initially failed under socket restrictions and passed
  with temporary test keys in the permitted execution environment; no publisher
  key or release artifact was used. Shell syntax and whitespace checks passed.

## Remaining acceptance and artifact requirements

Full release acceptance is **not complete**. This was a separate clean Ubuntu
filesystem with real packages, compilation, PostgreSQL and systemd, sharing the
retained VPS kernel and resources; it was not a new standalone VM or an exact
signed-kit acceptance run. The guest was capped at 75% CPU and 1 GiB memory while
the retained installation continued broadcasting.

Two-station Liquidsoap provisioning failed when the first guest station was
already broadcasting. Provisioning both before starting audio succeeded, but
the second station subsequently missed the CLI's readiness timeout. A separate
one-Liquidsoap-plus-FFmpeg run passed streaming, listener and plan-limit checks
and suspension, then full Freo reactivation failed with
`verification_failed: A requested station has no Icecast source.` The existing
45-second verification window expired and policy correctly fell back to
maintenance. Guest Liquidsoap logs show clock catch-up delays; resource
contention is a likely explanation, not a conclusively isolated root cause.
Do not claim two simultaneous Liquidsoap stations or full Freo reactivation
passed. Repeat those checks on a dedicated adequately sized clean VPS before
release; they do not justify changing unrelated runtime behavior in this fix.

Native Icecast policy-cycle checks with lightweight FFmpeg audio passed:
suspension, maintenance and both reactivations succeeded, with real proxied MP3
bytes after each activation. No Liquidsoap station was requested during that
separate policy-cycle check. Full two-Liquidsoap retries still missed the second
station's readiness deadline after raising only the guest limits to 125% CPU
(1.25 of the VPS's two vCPUs) and 1.25 GiB memory. Sanitized unit logs show its
process started but no source appeared before the CLI stopped it, after about
12 seconds of CPU consumption. The cause is not isolated; increased allocation
did not establish successful full acceptance. These failures remain visible in
the evidence and are a release gate.

HTTP/loopback login was tested; external DNS, HTTPS/certificate issuance,
full-VM reboot and ARM64 were not tested. The installer currently restricts fresh
installations to x86_64.

The isolated guest was shut down and its filesystem removed after retaining
sanitized evidence. The retained VPS's Freo and Icecast remained active and its
readiness endpoint passed after cleanup. No production configuration, services,
database, installed packages or signed Freo artifacts were changed.

## Retained evidence

The workspace fixture and evidence are under
`/opt/freo/source-fixes/libigloo-validation-20261011/`. The sanitized guest
archive is `guest-evidence.tar.gz`, SHA-256
`81fb8a1d4f8ce608597a1c1ad955402861eab22c55ca9c2a2b3d5b65dd4e79ea`.
It contains original/fixed APT policies, original and final simulations, installed
versions, dpkg state before the repeat setup, compilation/linking/runtime logs,
the full source installer log, actual failed-preflight JSON, policy preservation
checks, native streaming/limits and policy-cycle results, failed full-Freo
attempts, sanitized service diagnostics and the hosting audit. Private source
credentials, unique generated application/database secrets and publisher keys
are absent; the installer log contains the documented default password for the
disposable, subsequently deleted bootstrap account.
The archive and fixture scripts are validation evidence, not release artifacts.

## Release artifacts

The source-only review archive is uninstallable and unsigned. Rebuild a new
version of the signed application archive and outer installation kit, including
`scripts/check-igloo.py` in the release inventory, and generate new manifests,
checksums, signatures and acceptance records. Update Studio's approved inventory
only after accepting those exact new bytes. Existing signed RC files and
production installations remain untouched.
