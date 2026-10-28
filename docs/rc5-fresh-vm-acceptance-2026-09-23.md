# RC.5 frozen fresh-VM acceptance — 2026-09-23

Status: **owner-confirmed fresh-install acceptance; frozen private release
candidate. Public distribution and merge to main are not approved.**

This record supplements the original [RC.5 checklist](rc5-acceptance.md) and the
build-time `validation.json`. It does not replace or modify any file inside the
signed archive or test kit. Their original pending checks describe build-time
status; the dated results below record subsequent acceptance.

## Exact accepted build

- Version: `0.3.0-rc.5`.
- Source commit: `739a0ed0b4bc9160ce4139cf641d3bd9f67ed9dc`.
- Schema head: `f39c8210b7de`.
- Local annotated tag: `v0.3.0-rc.5`; tag object
  `80d2305e0fdf068daa75764293b72932a0c73c62`, pointing to the source commit above.
- Platform: Ubuntu 24.04 x86_64.
- Publisher: 3andB.
- Publisher primary fingerprint: `B835B40E7E1A5838390256751AB72B63BEB716C3`.

| Frozen artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `freo-v0.3.0-rc.5.tar.gz` | 65,384,180 | `6fb6030b6a5ee06925e4b9c285e3c1e461fe323656d3763e2a54af481922b4bb` |
| `freo-v0.3.0-rc.5-test-kit.tar` | 65,464,320 | `6ba092f70aa2adaab46b882c3f9928d569dbb7a611b2e7e1337eeb7cb8c8fbfe` |

The acceptance-documentation commit is later than the accepted application
commit. It must never be substituted for the frozen tag or used to rebuild RC.5.
Any application change requires a new candidate version and new acceptance.

## Owner-confirmed fresh-VM results

Evidence source: the owner's explicit acceptance report and instruction to record
these successful results on 2026-09-23. These are operator-observed VM results,
not claims that the release agent remotely executed the installation or reboot.

| Acceptance check | Result |
| --- | --- |
| Clean Ubuntu 24.04 x86_64 installation | Passed — owner confirmed |
| Publisher fingerprint, SHA-256 and GPG signature verification | Passed — owner confirmed; preserved artifact independently reverified below |
| First login and mandatory password replacement | Passed — owner confirmed |
| Music import, native file selection and drag-and-drop | Passed — owner confirmed |
| Station creation and configuration | Passed — owner confirmed |
| Simple mode | Passed — owner confirmed |
| Playlist playback | Passed — owner confirmed |
| Calendar playback, including adding a playlist and switching from Simple to Calendar | Passed — owner confirmed |
| Public player and real decoded audio | Passed — owner confirmed |
| Mothership check-in | Passed — owner confirmed |
| Full server reboot | Passed — owner confirmed |
| Previously running station automatically returning after reboot | Passed — owner confirmed |
| Startup tone followed by automatic playlist playback | Passed — owner confirmed |
| Saved configuration and music surviving reboot | Passed — owner confirmed |

The known-good installed RC.5 VM is retained unchanged for upgrade testing. No
upgrade, reinstall, restart, configuration change, database write or music change
was performed on that VM as part of this documentation and deep-save operation.
This source/release backup is not a backup of the test VM's database or media.

## Independent evidence

Before this acceptance record, an external read-only check returned HTTP 200 for
the public `test2` player, reported the station ready/running, and read 8,192 bytes
of `audio/mpeg` with MPEG sync from its public stream. That check established
HTTP/audio-byte delivery; decoded/audible playback is confirmed by the owner.

The preserved signed package's prior automated validation includes 19 packaged
acceptance tests and one real Icecast/Liquidsoap test passing. The separate real
PostgreSQL encrypted recovery suite passed 14 tests. Build-time `validation.json`
contains the detailed earlier suite results; they have not been relabeled as new
VM tests or rerun for this documentation-only change.

GitHub's recovery workflow also succeeded for the frozen source commit:
[RC.5 source CI run](https://github.com/3andB/freo/actions/runs/35808789298).

During the deep save, verification independently confirmed:

- Both artifact SHA-256 values above and their existing checksum files.
- The publisher key's primary fingerprint and a valid detached GPG signature.
- The archive's exact source commit/version and all 645 manifest entries,
  including hashes, sizes and modes.
- All 12 files inside the test kit match the preserved standalone files.
- A baseline SHA-256 inventory of all 15 preserved release-directory files;
  the inventory is checked again at completion.

## Preservation and remaining gates

The original immutable release directory is
`/var/backups/freo-release-candidates/v0.3.0-rc.5`. The separate dated deep-save
backup retains Git bundles and Git metadata for the candidate and production
repositories, the acceptance record, a duplicate of the original release files,
and verification evidence. Its final path and acceptance commit are reported to
the owner after the commit and backup are verified. It is a local-host backup;
an independent off-host copy has not been established by this operation.

No RC.5 tag push, GitHub Release, public artifact upload, stable/latest pointer
change, main merge or production deployment is authorized by this acceptance.
The [automation audit](rc5-merge-automation-audit-2026-09-23.md) explains what a
merge/tag push would trigger and the external configuration still to verify.

Before broader distribution, exercise populated upgrades and recovery on a
separate clone/snapshot of this accepted baseline, including retained media,
settings, schedules, credentials and playback. Preserve the original VM until
that test is explicitly authorized. Public domain TLS issuance and renewal remain
a separate acceptance gate; HTTP VM success does not establish those results.
