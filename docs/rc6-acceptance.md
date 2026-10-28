# RC6 test candidate acceptance

Status: **candidate for testing; VM acceptance pending**. Use the exact signed
`0.3.0-rc.6` archive and record its SHA-256, `release.json` commit and schema with
all results. The kit's `validation.json` lists actual automated results separately
from pending operator/VM acceptance. This document is a checklist, not a pass.

## Fresh VM

1. Follow `rc6-installation.md` on a fresh Ubuntu 24.04 x86_64 VM. Verify the
   publisher fingerprint, signature and both archive checksums before installation.
2. Complete the mandatory first-admin password replacement. Verify logout/login,
   rejection of the old initial password, and HTTP or HTTPS cookies as appropriate.
3. Create two stations. Confirm preparation completes, controls become available,
   each stream plays externally, and starting/stopping one leaves the other intact.
4. Import music into a category and playlist. Test picker, drag/drop, duplicate
   handling, failed upload retry and reset after a completed import.
5. Test Simple, Playlist and Calendar programming, station timezones, scheduled
   transitions, station IDs, queue controls and DJ/cart return to automation.
6. Edit several station settings together and Save once. Verify all changes persist
   after navigation/reload; a validation error must retain the other draft edits.
7. Inspect installation, feedback, settings, tags, categories, media and website
   on desktop/mobile. Check aligned controls, list categories and import performance.
8. Verify the player has textured spinning vinyl, a circular animated center,
   bright outer colors and stationary album artwork. Test pause/resume and reduced
   motion. Confirm statistics update while listening and map bounds prevent repeated
   worlds. Unknown listener locations legitimately have no map pin.
9. Confirm `0.3.0-rc.6` in UI and the accepted heartbeat; credentials and installation
   identity persist across restart. First-release Unknown is normal. Freo Live
   account ownership or paid entitlement must not gate ordinary reporting/playback.
10. Reboot. Verify accounts, settings, media/artwork, schedules and desired-running
    stations survive and playback resumes. Run `scripts/validate-install.sh` again.
11. On a dedicated domain verify public TLS issuance and `certbot renew --dry-run`.
12. Record a clean one-hour two-station observation without heavy test jobs sharing
    the radio host; check continuous decoded audio, actual starts, metadata freshness,
    fallback/incident logs and service restarts. Do not label partial observations
    or earlier development soaks as acceptance of this exact artifact.

## Populated upgrade and recovery

Use additional disposable state/VMs. Install the existing signed RC5 bytes, populate
accounts, two stations, music, artwork, playlists and schedules, then upgrade with
the RC6 signed-bundle workflow. Preserve before/after database rows/sequences, media
hashes, identity/credentials and saved settings. Verify real streams after restart.
Rehearse encrypted off-host restore on replacement disposable state and the existing
upgrade interruption/recovery safeguards. Record observed service interruption.
The preserved accepted RC5 VM remains unchanged throughout.

## Candidate discipline

This build includes the accepted RC5 ancestry, RC6 UI/player/statistics/import
work, audit race/startup fixes and server-provided version awareness. It adds no
schema migration beyond `f39c8210b7de`. A candidate artifact becomes immutable when
handed out; test results are dated supplemental records, never edits to its bytes.
Any product fix requires a separately identified candidate and corresponding tests.
Owner acceptance and stable publication remain separate decisions. No stable/latest
pointer moves and no stable GitHub Release are part of preparing this test kit.
