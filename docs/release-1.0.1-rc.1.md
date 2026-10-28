# Freo 1.0.1-rc.1 — recovery candidate

This candidate fixes three live backup restoration defects in signed v1.0.0.
It does not change the database schema (fe28c3d4e5f6). Stable v1.0.0 assets remain
immutable. Candidate acceptance results are recorded separately against exact
artifact hashes; a signed package alone is not recovery acceptance.

* Fresh direct-install recovery created the managed releases parent using the
  caller's umask, leaving it inaccessible to service accounts under 0077.
  Recovery now establishes validated root-owned directories as 0755, rejects
  unsafe paths and symlinks, and never recursively changes secret permissions.
* Resume globally replaced source prefixes in already-relocated launchers,
  nesting the recovered destination into itself. Recovery now derives entry
  points from verified restore input, relocates only interpreter paths, and
  atomically replaces scripts while retaining their modes and arguments.
* Direct-install adoption wrote canonical secrets as 0600, contradicting the
  installed validator's 0640 contract. Adoption now establishes root:freo 0640
  for new, existing and already-canonical environment files without changing
  their contents.

These are recovery defects. Earlier passing fresh installation, first-use,
broadcasting and reboot checks did not exercise or certify these recovery paths.
See candidate-installation.md and recovery-and-upgrades.md for verified tools.

## Installations already affected

Keep maintenance/suspension guards in place. Preserve the operation journal,
encrypted backup and key escrow, verified restore input, displaced database and
recovery point. Do not rewrite phases or manufacture completion records.

Verify this candidate's signatures and use its separately extracted management
tools for the entire recovery and resumption, especially when restoring v1.0.0
application code. The normal CLI selects the restored application implementation;
using its old recovery implementation would reintroduce these defects.

The corrected tools repair a validated root-owned restrictive releases parent,
rebuild launchers from the operation's verified input, and normalize canonical
configuration ownership/mode. Run services recover using those candidate tools,
then validate configuration access, account access, programming, media hashes,
hosting authority and decoded audio as appropriate for the current policy.
Do not manually normalize paths before each resume. Unsafe ownership, symlinks,
missing verified input or ambiguous database state require reviewed offline
recovery; do not use recursive chmod/chown or discard retained evidence.
