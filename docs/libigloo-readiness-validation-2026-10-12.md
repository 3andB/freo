# Libigloo and cold-engine readiness validation — 12 October 2026

The dependency-selection correction and the later two-Liquidsoap/hosted
reactivation failures now pass real clean-Ubuntu acceptance. This follow-up
supersedes those unresolved functional gates in the
[11 October record](libigloo-selection-validation-2026-10-11.md). The original
failed attempts remain retained. Public release approval and publisher signing
are separate from this source fix.

## Confirmed causes and narrow fixes

Genuine signed APT metadata on a fresh Ubuntu 24.04 filesystem reproduced:

| Package | Original candidate | Priority | Corrected candidate |
| --- | --- | --- | --- |
| `libigloo-dev` | Ubuntu `0.9.2-1.1build1` | 500; Xiph `0.9.5-1` was -1 | Xiph `0.9.5-1`, priority 700 |
| `libigloo0` | Xiph `0.9.5-1` | 700 | Xiph `0.9.5-1`, priority 700 |

The original development-package transaction also selected Ubuntu
`libigloo0t64=0.9.2-1.1build1`. Xiph's development package instead requires
exactly `libigloo0=0.9.5-1`. Icecast 2.5.0 requires igloo headers/pkg-config
**>= 0.9.4**; its executable also needs a compatible actual shared library.
A development-package version alone cannot establish runtime compatibility.
The corrected package allowlist retains the repository-wide -1 priority and
Icecast 2.5 rule. No unrelated repository priority, distribution upgrade,
forced hold change or automatic package removal is introduced.

A permanent `0.9.5-1` pin would unnecessarily reject future compatible
revisions. Preparation instead checks matching APT candidates >= 0.9.4,
simulates the full required build transaction with `--no-remove`, and installs
that transaction's exact resolved pair. It then verifies headers and the loaded
runtime before compilation. An older `libigloo0t64` can replace library files
while dpkg still reports Xiph's runtime installed; the actual-library probe
rejects that state for operator reconciliation. Existing affected hosts are
not automatically changed or repaired by removing packages.

The later readiness failures were independent of package selection. Installed
station startup allowed approximately 60 seconds, hosted activation 45 seconds,
audio recovery 60 seconds and diagnostic validation 45 seconds. The existing
real two-engine test already allowed 120 seconds. A healthy cold engine could
therefore be stopped before initialization completed.

The follow-up shares a monotonic **120-second** readiness budget and a
120-second diagnostic-validation budget, with a **150-second** enclosing
runtime command budget. Readiness still requires a live stream. Exceptions
remain visible; an unsuccessful hosted activation still inhibits broadcasting
and enters maintenance. Liquidsoap and system packages were not upgraded to
solve timing failures.

Sanitized real unit journals confirm the timing problem: the second station's
first Liquidsoap `LOG START` occurred **65.85 seconds after systemd reported the
process started**. During the first reactivation, the two engines reached
`LOG START` at **84.91/83.35 seconds**. Actual MP3 reception and decoding then
passed. These exceed the previous 60/45-second windows. Resource contention
and memory pressure extended cold initialization; their individual
contributions were not isolated. The correction permits these healthy starts
while keeping waits bounded.

## Source changes

Dependency changes are in `scripts/configure-icecast-repository.sh`,
`freo_ops/v1.py`, `scripts/check-igloo.py`, `scripts/build-icecast-2.5.sh`,
`freo_ops/hosting_admin.py`, `freo_ops/inventory.py`,
`tests/test_icecast_dependencies.py`, `docs/installation.md` and
`docs/icecast-upgrade.md` (functional commit `7f3388b`).

| Follow-up file | Change |
| --- | --- |
| `freo_ops/engine_readiness.py` | Shared deadlines and monotonic readiness polling. |
| `app/cli.py` | Station start checks actual running/online status for the shared budget. |
| `app/services/station_runtime.py` | Longer enclosing validation budget and bounded audio recovery with master-OFF cancellation. |
| `freo_ops/hosting_admin.py` | Allow cold sources to become ready; preserve maintenance/inhibit fallback on failure. |
| `scripts/render-radio-config.py` | Cold syntax validation retains staged configuration safety. |
| `tests/test_engine_readiness.py` | Late readiness, permanently missing streams, exceptions, master-OFF cancellation, hosted failure fallback and staged-config preservation. |
| `tests/test_station_streams.py` | Real-engine acceptance uses the same budgets as installed commands. |
| `tests/test_versions.py` | Remove obsolete `dev.1` literal while retaining the assertion that source version overrides legacy configuration. |
| `app/version.py` | Private candidate identifier `1.0.0-dev.13`. |
| `docs/radio-engine.md`, both validation reports, `docs/icecast-upgrade.md` | Requirements, startup behavior, evidence and release scope. |

Readiness runtime changes are commit `96d7bdd`. Subsequent changes are test and
documentation corrections; the installed runtime code tested below is that
commit's code.

## Real installation and hosting checks

The explicitly authorized disposable Freo-v1-Test-1 VPS hosted a **new** Ubuntu
Base filesystem, verified against Ubuntu's signed checksums. It was a private
mount/PID/network namespace with its own systemd, PostgreSQL, Nginx and services,
sharing the VPS kernel. Its 4 GiB filesystem was capped at 125% CPU and 1280 MiB
memory while the retained RC installation continued running. A fixture-only
Unix-socket network proxy provided package downloads. Host APT, retained
application state and retained services were not reconfigured.

The tested application archive was a new private candidate built from
`96d7bdd58ae23193fdf65ad4435c9f697ad8585e` with hash-locked offline wheels:

- File: `freo-v1.0.0-dev.13-candidate.tar.gz`
- SHA-256: `5d399d636fe3ff712fb426661ba57b8ce5cdc8fde0a05594638ed63bbb9d03ce`
- Disposable test signing fingerprint: `7DC1EDDA1351532454A57689DF44B5D553798B02`

The guest verified the archive checksum and detached signature before
extraction. This key is a validation key, not the release publisher's identity.

All of these are **real installation/runtime checks**, with no substituted
APT resolver, Icecast, Liquidsoap, database or systemd:

1. Original preferences selected Ubuntu 0.9.2 headers/runtime in an APT
   simulation. Corrected preferences selected Xiph 0.9.5 development/runtime
   packages without removals. The full installer then installed its own system
   dependencies, hash-locked wheels, PostgreSQL schema, Nginx and services;
   readiness and first-login validation passed.
2. An intentionally unavailable local APT source made actual
   `freo-admin hosting configure` fail with
   `icecast_dependencies_unavailable` and actionable policy/hold/library
   commands. Policy and Icecast configuration stayed byte-identical, no enabled
   marker appeared, Freo/Icecast stayed active and `/ready` remained healthy.
   The fixture source was removed before retrying.
3. Hosted enable built the patched native Icecast from the verified 2.5.0
   archive (`d9aa07c7429aec19d950ff6fd425c371f77158cd34ff220fc191b2c186c67c7a`),
   activated it and verified authoritative limits. `icecast -V` and the
   library probe reported actual runtime **libigloo/0.9.5**; linking resolved
   all libraries. `dpkg --audit` was empty.
4. Repeating dependency preparation left the entire dpkg status file
   byte-identical.
5. Two actual Liquidsoap stations streamed MP3 through Nginx/native Icecast;
   FFmpeg decoded each stream. Two concurrent listeners on different mounts
   received audio; a third received HTTP 503. Actual database/policy operations
   rejected a fourth station, 192 kbps above the 128 kbps allowance and a 2 GiB
   reservation above the 1 GB storage allowance. The reservation test did not
   allocate or upload a 2 GiB file.
6. Actual suspension, maintenance and **both reactivations** passed with the
   requested Liquidsoap sources. Streams stopped during restricted states and
   returned after activation. Full command times were 51.52/79.65 seconds for
   station starts and 105.62/90.82 seconds for reactivations; those include CLI
   startup and verification, not just readiness polling.
7. A guest cold boot resumed both streams, decoded audio and verified active
   hosting. Station state persisted; radio configuration, policy and package
   status remained byte-identical. The corrected verification run observed
   streams after 112.61 seconds from its own start. The VPS itself was not
   rebooted.

Installed packages: `libigloo-dev 0.9.5-1`, `libigloo0 0.9.5-1`,
`icecast2 2.5.0-1`, `liquidsoap 2.2.4-1`, `ffmpeg 7:6.1.1-3ubuntu5`.
`libigloo0t64` was absent in this fresh guest.

## Regression checks and retained test failures

- **80 focused cases passed**, including real APT resolution with synthetic
  repository metadata and synthetic-library dynamic loading. Command failures,
  long readiness delays and activation fallback use mocks/fake clocks; these
  are not proof of a real installation.
- The existing **real two-Liquidsoap lifecycle integration passed** in 218.80
  seconds on temporary ports/files. Its systemd/Nginx supervisor is substituted;
  rendering, validation, streaming and shared audio playback are real. The
  surviving station continued after deletion of the other station/owner.
- The full isolated SQLite backend run completed with **1,477 passed, one
  failed and 27 skipped**. Its sole failure was the obsolete `dev.1` assertion,
  already incompatible with the earlier `dev.12` source. After correction,
  **all 64 version-module cases passed**. The complete suite was not rerun after
  this test-only correction. Skips were opt-in integrations.
- An earlier sandboxed attempt could not bind localhost test sockets and was
  interrupted. The complete run used permitted private HTTP/TLS/Nginx fixtures.
- The initial full-install wrapper reported a parent-network-namespace teardown
  error after inner acceptance exited 0. Correcting the fixture's `/proc`
  namespace made later wrapper shutdown exit 0. The first cold-boot verifier
  used system Python for its final app/database assertion and lacked `dotenv`;
  audio and hosting had passed, but the fixture exited 1. Repeating with the
  installed virtual environment passed all checks and exited 0. These failures
  and their logs are preserved; they were test-fixture errors, not source fixes.
- Candidate build/offline wheel verification, shell syntax, Python compilation
  and whitespace checks passed.

Evidence is retained under
`/opt/freo/source-fixes/readiness-validation-20261012/`, including JUnit/logs,
fixtures and sanitized guest evidence. The guest archive SHA-256 is
`6a47a005c620c73db2efe08efb3e41d5aff2059e37aa8d2c0fd324e0e38150dd`.
It retains original/fixed APT policies and simulations, actual package/runtime
versions, source/binary digests, installation and safe-preflight records,
stream/limit/cycle results, sanitized timing journals and both cold-boot attempts.
Private generated credentials and publisher private keys are not included.

The stopped disposable filesystem was removed after checksum-verifying the
retrieved evidence. Retained Freo, Icecast and Nginx remained active, `/ready`
returned `{"status":"ok"}`, and host free disk returned to 4.1 GiB.

## Release requirements and limitations

The observed package-selection, two-source startup and hosted reactivation
failures are resolved. This is a real clean Ubuntu installation and guest cold
boot, not a new standalone VM or a full hardware/kernel reboot. It does not
establish station-capacity/performance guarantees, a long streaming soak,
public DNS/TLS issuance, ARM64 support, or a complete V1 release qualification.
The full-load journals still show clock catch-up under resource contention.

Rebuild a **new immutable release version** of the application archive and
outer installer kit from the final reviewed source, including the runtime probe
and readiness module. Regenerate release/file manifests, checksums, detached
publisher signatures, kit digest and acceptance documentation. Accept those
exact publisher-signed bytes on the release test VM before updating Studio's
approved inventory or publishing. The private test-key candidate does not
provide publisher signing approval. Existing signed RC artifacts and production
servers were not modified.
