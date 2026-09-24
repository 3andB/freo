# RC8 test candidate acceptance

Status: **candidate for testing; VM acceptance pending**. Use the exact signed
`0.3.0-rc.8` archive and record its SHA-256, `release.json` commit and schema with
all results. The kit's `validation.json` lists actual automated results separately
from pending operator/VM acceptance. This document is a checklist, not a pass.

## Fresh VM

1. Follow `rc8-installation.md` on a fresh Ubuntu 24.04 x86_64 VM. Verify the
   publisher fingerprint, signature and both archive checksums before installation.
2. Complete the mandatory first-admin password replacement. Verify logout/login,
   rejection of the old initial password, and HTTP or HTTPS cookies as appropriate.
3. Create two stations. Confirm preparation completes, controls become available,
   each stream plays externally, and starting/stopping one leaves the other intact.
4. Verify `/admin/software` access and spacing. Import music into a category and playlist. Test picker, drag/drop, duplicate
   handling, failed upload retry and reset after a completed import. Playlist bubbles should
   be the only playlist selector, with no redundant dropdown.
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
9. Confirm `0.3.0-rc.8` in UI and the accepted heartbeat; credentials and installation
   identity persist across restart. First-release Unknown is normal. Freo Live
   account ownership or paid entitlement must not gate ordinary reporting/playback.
10. Reboot. Verify accounts, settings, media/artwork, schedules and desired-running
    stations survive and playback resumes. Run `scripts/validate-install.sh` again.
11. On a dedicated domain verify public TLS issuance and `certbot renew --dry-run`.
12. Record a clean one-hour two-station observation without heavy test jobs sharing
    the radio host; check continuous decoded audio, actual starts, metadata freshness,
    fallback/incident logs and service restarts. Do not label partial observations
    or earlier development soaks as acceptance of this exact artifact.

## New behavior since RC6

- Login: leave an admin tab signed out while logging in elsewhere; background
  polls must not invalidate the form. Expired forms must recover clearly.
- Location: Settings accepts optional city-level paired coordinates, including
  zero. Verify rounding, invalid/incomplete pairs, same-place saves preserving
  coordinates and changed-place confirmation. Failed saves must change nothing.
  Missing coordinates after upgrade are normal; no server-IP inference occurs.
  With configured coordinates, verify distinct station UUIDs in station sync and
  map pins/clusters on freo.live after the existing reporting interval. No public
  directory opt-in or paid entitlement is required for location reporting.
- Microphone: on HTTPS, start LIVE MIC from AUTO and from DJ. Switching tabs must
  stop microphone broadcast. Leaving the page warns; Cancel keeps the session,
  Leave ends it and restores the interrupted feed. Test browser reload/back,
  soft navigation, sign-out and delayed permission approval. Verify the previous
  station audio externally. HTTP on a remote VM cannot exercise browser capture;
  record this as untested unless HTTPS is configured. Production microphone
  acceptance does not replace testing this installed artifact.

## Scope

This round targets a fresh installation on the owner's new disposable VM.
Historical RC5/RC6 upgrade rehearsals are outside the requested scope. Existing
migration/recovery tests remain available, but fresh installation success must
not be described as independent upgrade or off-host restore acceptance.

## Candidate discipline

This build preserves the accepted RC5/RC6 ancestry and all changes approved on
production through `cd29c398c66665fb7996685c4f7354fb28ee6571`. RC7 existed as
unpackaged development identities; this signed checkpoint is RC8. The only runtime
change from that tested production commit is the canonical version identity.
Schema advances from `f39c8210b7de` through `a64f09e2b731` to `b72e19d4c603`.
A candidate artifact becomes immutable when handed out; later results are dated
supplemental records. Any product fix requires a separately identified candidate.
Owner acceptance and stable publication remain separate decisions. No stable/latest
pointer moves and no stable GitHub Release are part of preparing this test kit.
