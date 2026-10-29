# Freo 1.0.2-rc.3 — microphone and recovery durability candidate

RC1's real unclean guest-reset test exposed a second defect. Recovery copied
verified roots, renamed them into place and durably marked them attached without
first persisting their file contents and directory entries. After a reset before
launcher fsync, a copied managed Nginx policy file returned empty. Resume correctly
failed closed with `Unmanaged hosting proxy configuration requires review`.
The failed operation and complete VM application/database state are retained;
it is not counted as successful recovery and was not manually repaired.

Persist every file and directory in the staged verified copy before attachment,
then persist the destination parent before recording completion. An interrupted
staging copy is discarded and rebuilt from verified input. This covers ordinary
restored roots and per-entry customer configuration, while preserving separate
destination authority. Restore symlinks atomically and persist their parent.
Write managed hosting guards and proxy policy atomically with file and directory
fsync too. Unsafe custom configuration still fails closed. Modes, secret contents,
retained databases and displaced recovery points remain protected.

This candidate also includes RC1's healthy-muted-microphone correction and real
RTP/Liquidsoap regression. The database schema and dependency locks are unchanged.
RC1's signed tag/source and draft artifacts remain retained and are not overwritten.
Existing stable 1.0.1 assets remain immutable and do not contain these new fixes.

Existing installations need an explicitly approved radio-maintenance upgrade;
the ordinary admin updater intentionally refuses this radio-template change.
Fresh install only on an application-fresh disposable Ubuntu 24.04 x86_64 VM.
The exact signed artifact must pass fresh and managed recovery, actual unclean
resets, resumption, reboot, data/permissions and decoded audio validation before
this candidate is published. Native phone/Safari, physical microphone/USB removal
and actual host-power removal require unavailable hardware and remain untested.


For an installation already affected by the earlier torn-copy failure, retain the
maintenance/suspension guard and preserve the entire failed filesystem, database,
recovery journal and verified encrypted backup. Do not delete an empty proxy
file, normalize launchers, clear guards or edit attachment checkpoints to make
resume appear successful. Validate the matched backup in isolation with trusted
fixed tools and review a full recovery attachment with the operator; old completed
copy checkpoints cannot prove that all copied contents survived a power cut.
The new candidate prevents this fault in newly executed attachments; it does not
silently trust or rewrite arbitrary corrupted managed configuration from an older
operation. The failed test baseline is archived before a separate fresh-install
acceptance run, not repaired and reported as passing.


Verified isolated restore input is synced before its checkpoint; root-controlled
journal/catalog directory creation persists every ancestor entry. Maintenance and
hosting-inhibit removals persist their parent directory before successful startup
can be checkpointed. The Icecast maintenance guard is written atomically. RC2's
final artifact passed fresh installation and 17 engine cases, then was superseded
at durability review before power qualification; no failed power test is claimed
for that source. All earlier tags and builds remain retained.


## Published test candidate acceptance

The exact [signed prerelease](https://github.com/3andB/freo/releases/tag/v1.0.2-rc.3)
is published for its documented disposable-VM testing scope. Source:
`aa5e4a46b58444ee2edc5ca6916060a0d4e42b84`.
Package SHA-256: `8bb26be0246130a86e54031aeca700f4b8ad9bdfb77b53a6bb4804f1985d7aa4`.
Kit SHA-256: `f472789dd9b1ef1433e9a40f0550aae03db2d97ce60c42bd1dfb3895336a75d1`.
[Download ZIP](https://github.com/3andB/freo/releases/download/v1.0.2-rc.3/freo-v1.0.2-rc.3-download.zip)
SHA-256: `665a119733ce0f4fd4dd665ee868f2588393407833709dd46fc83b6f3d0bed01`.

The exact source passed 154 root recovery/hosting/lifecycle/upgrade cases, 17 real
Liquidsoap/WebRTC microphone/engine cases and the complete branch/tag release
workflows including independently verified signing. CI XML records 618 passes and
10 optional skips; PostgreSQL and actual packaged startup gates passed too.
These counts are separate overlapping suites and are not summed.

The separate application-fresh Ubuntu 24.04 VM retained OS/packages/accounts and
TLS identity. Normal setup replaced the bootstrap credential and created actual
generated media, an assigned DJ, persistent Simple programming, hosted policy and
one deliberately stopped station. Deployed HTTPS browser microphone/gain/mute/
return/permission/client-loss and six Chromium player profiles passed with actual
decoded sample/spectral checks. Under umask 0077, encrypted backup and isolated
restore passed. Three actual SysRq-b unclean guest resets preserved the same real
incomplete operation, held broadcasts inhibited and retained all 5,068 verified
input files exactly. Ordinary CLI recover completed without operator repairs.
Managed and suspended live restores, attempted root service starts while suspended,
suspended and active full reboots, account/media/programming/policy retention,
whole environment bytes/root:freo 0640, executable launchers and non-silent direct/
HTTPS decoded audio passed. Current restore journals reached completion truthfully.

[Signed extended acceptance](https://github.com/3andB/freo/releases/download/v1.0.2-rc.3/EXTENDED-ACCEPTANCE.md)
and [machine-readable evidence](https://github.com/3andB/freo/releases/download/v1.0.2-rc.3/EXTENDED-ACCEPTANCE.json)
retain earlier failed attempts and exact scoped results. [Both ZIPs downloaded
anonymously and verified as Freo's Unix user on World and the disposable VM](https://github.com/3andB/freo/releases/download/v1.0.2-rc.3/PUBLIC-DOWNLOAD-VERIFICATION.json).
World production runtime and OVH endurance were not interrupted.

Physical phones/Safari, USB microphone input/removal, physical host-power removal,
the full earlier human six-stream matrix, final stable-to-RC3 maintenance upgrade
and Studio/World approval for this new version remain outside this qualification.
The corrected release remains a prerelease; latest stable stays 1.0.1 with its new
issues disclosed. All prior signed tags and published artifact bytes remain intact.


## Additional owner-reported fresh-VPS acceptance

The owner reports a successful RC test on a genuinely new Ubuntu VPS:
installation, first direct-layout restore, controlled interruption/resumption and
reboot completed without manual repairs. State, generated data, permissions and
four decoded streams passed. This adds reported clean-OS coverage to the earlier
retained-OS acceptance above.

Provenance: owner report. Exact tested artifact digest, operation IDs, interruption
method and raw logs were not supplied with this update. Those details remain
pending for independent artifact binding. The published kit, ZIP, signatures and
original signed reports retain their existing bytes. Remaining physical-device,
physical-power and stable-to-RC upgrade qualifications remain as documented above.
