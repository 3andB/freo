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
