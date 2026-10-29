# Freo 1.0.1 — recovery patch

1.0.1 promotes the accepted 1.0.1-rc.1 recovery implementation. The database schema
remains `fe28c3d4e5f6`. Recovery behavior and public CLI/API contracts are unchanged
from that candidate. The source version is now `1.0.1`; existing signed 1.0.0 and
1.0.1-rc.1 artifacts remain immutable.

## Changes

- First live recovery establishes root:root 0755 on the managed releases parent
  and recovered child independently of umask. Unsafe ownership, writable paths
  and symlinks fail closed; secret files are not recursively made readable.
- Every resume derives generated launchers from verified retained restore input.
  Relocation changes only the interpreter path, retains arguments and executable
  modes, and uses atomic replacement. Repeated recovery cannot extend the path
  or change unrelated script content. Systemd unit adoption is atomic too.
- Fresh and existing canonical environment files are established as root:freo
  0640, preserving secret bytes and the existing validator contract.

See the [candidate root-cause and affected-installation guidance](release-1.0.1-rc.1.md).
The stable release uses the same separate verified management-tool procedure when
restoring older application code. Keep those tools outside the restored tree and
use their `scripts/hosting-admin.py` entry point for the whole operation, including
`services recover`; the old restored application can still contain the defects.
Never edit journal phases, discard retained databases/recovery points, or downgrade
the schema to claim successful recovery.

## Candidate qualification

The accepted candidate is source commit
`01576e870d92ae505265ba069bc53ebc119b996f`, package SHA-256
`6e3afb6cf8e23a1c5704fe2575ed9fc0e05acad66736daa9353874a10e788ca2`, kit SHA-256
`a9c280ed9c745be5219000cbab0c4c52fabb37b3778fe239d1052435ea089909`.

[Candidate release and signed evidence](https://github.com/3andB/freo/releases/tag/v1.0.1-rc.1)
records 629 passing CI cases (9 optional skips), including 75 filesystem/lifecycle
cases. Real disposable-Ubuntu qualification covered the normal signed v1.0.0
upgrade, encrypted backups and isolated restore, fresh-install live recovery,
four SIGKILL/resume boundaries, managed and suspended recovery, actual generated
media, decoded direct/HTTPS audio, account/programming/policy preservation and
both suspended/active full reboots. The before-upgrade recovery point was verified.

The owner additionally reported independent Studio/OVH acceptance: public downloads
and signatures as Studio's service user, normal upgrade with verified off-server
backup, interrupted managed restore/resume without repairs, reboot/state
preservation, six decoded streams, administrator login and browser playback.
That is owner-reported evidence; it was not independently run from this checkout.

These recovery results are separate from the earlier v1.0.0 human installation
and broadcasting acceptance. Abrupt power loss during a filesystem write and a
full repeat of the earlier human mobile/microphone matrix were not performed.

## Final stable artifact gate

Source merge is not publication. Build and sign a new versioned 1.0.1 package and
installation kit; record their exact source commit, hashes and publisher signature.
Do not rename or overwrite the RC archives. Validate the final stable bytes on a
disposable host before publishing them or changing the stable bootstrap, API,
Studio defaults or production installation. RC acceptance does not certify newly
built stable bytes.

GitHub-hosted signing is currently unavailable because its release-environment
key, passphrase and fingerprint are not configured. The accepted RC was built
with the normal release builder and signed/verified locally using the established
publisher fingerprint `B835B40E7E1A5838390256751AB72B63BEB716C3`. Keep that trusted
signing process intact; do not weaken signature checks to bypass missing CI secrets.

## Published stable acceptance

The exact stable release is published at [v1.0.1](https://github.com/3andB/freo/releases/tag/v1.0.1).
Source commit: `5481ce775d9c0669cc785660f3865448053278da`.
Package SHA-256: `a3931ca709304a276c9037dee186b7f8b55c3e18dafcb899f956c2f50d678d27`.
Kit SHA-256: `2b213b00a8ad019f9bd9ecfdb006912d391e8ce6c3fc42c8a3022d51075b51a8`.

[Signed acceptance report](https://github.com/3andB/freo/releases/download/v1.0.1/ACCEPTANCE-1.0.1.md)
and [machine-readable results](https://github.com/3andB/freo/releases/download/v1.0.1/ACCEPTANCE-1.0.1.json)
record final stable validation on the attached disposable Ubuntu 24.04.5 x86_64 VM:
ordinary signed v1.0.0 and RC upgrades with candidates disabled, verified encrypted
backups and isolated restores, fresh-direct and managed live recovery with four
actual SIGKILL/resume boundaries in each layout, full configuration-byte and
ownership/mode checks, preserved identity/accounts/media/programming/station states
and destination policy, suspended recovery with root restart inhibition, four full
reboots, and non-silent generated audio decoded through direct and CA-verified HTTPS.
All recovery journals completed without edits or operator recovery repairs.
The exact source passed 629 CI cases (9 optional skips) and 75 local root cases.
The v1.0.0 upgrade baseline was a retained complete matching application/database
snapshot, with deployed source verified before its normal installed updater ran.
The final fresh tests retained Ubuntu packages, Unix accounts and the test certificate;
they were not a newly imaged OS test.

An early fixture attempt began hosted configuration while asynchronous station
creation was incomplete and failed closed before recovery. Its application and
complete database state were retained. The clean accepted repeat waited for both
station provisioning jobs and mounts before hosting setup; no sandbox repair was
used to qualify it. Reported results apply to that completed repeat.

The final artifact gate above has been fulfilled by these exact bytes. Original
v1.0.0 and RC assets remain immutable. Production World and OVH were not upgraded
or interrupted by these tests. Public downloads and the approved World manifest
are verified separately. Existing installations use the signed updater; never run
the fresh installer over existing customer state.

GitHub source/dependency/build/package-startup jobs passed; its remote signing step
remains unconfigured. Local signing used the established publisher and independent
signature verification. No private signing material was uploaded to GitHub.
Power loss during writes and the earlier full human mobile/microphone/six-stream
matrix remain untested on these stable bytes.
