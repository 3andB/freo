# Freo 1.0.2-rc.2 — microphone and recovery durability candidate

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
