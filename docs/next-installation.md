# Next installation handoff after RC6

## Baseline and preserved release

The owner reported RC6 successful on 2026-09-24. Its delivered signed package,
source tag and test VM remain unchanged. This note supplements that historical
candidate; it does not amend the package or claim that unobserved acceptance
checklist items were independently verified.

Current development version: **0.3.0-rc.7.dev1**. This identifies the newer software
honestly in the UI and existing heartbeat. It is not an announced stable release
or a newly signed installation candidate.

The changes after RC6 are:

- Music import uses the existing playlist bubbles; the redundant playlist list
  is removed. Individual choices, batch defaults and reset after import remain.
- Software and license has inner padding, readable section spacing, bounded
  forms and wrapping for long upgrade messages.
- Browser readiness and CI diagnostics were improved without changing runtime
  licensing, upgrade or broadcast behavior.

No new database migration or dependency update is required for these UI fixes.
The schema remains `f39c8210b7de`. The accepted RC5 ancestry is retained.

## Evidence already collected

- Playlist/import and version checks: 66 passed, including real browser import,
  playlist assignment, defaults for later files and completion reset.
- Existing licensing/upgrade tests: 16 passed.
- Software page: nine isolated layout checks at 390, 820 and 1440 pixels for
  Community, Unlimited, license errors, prepared upgrades and long messages.
  No browser errors or overflowing controls were observed; no real license or
  upgrade actions were submitted.
- GitHub recovery CI and the production deployment receipt must be recorded
  against the exact deployed commit. A successful live deployment does not by
  itself constitute acceptance of a newly built installer.

## Prepare the next signed test installer

1. Finish the owner's live checks of both UI fixes. Record the exact approved
   source commit; include later fixes before choosing the package commit.
2. Give the installation candidate a new identity, such as `0.3.0-rc.7`, and
   update the existing canonical version metadata and matching tests. Never
   overwrite or repoint RC6. Do not present `rc.7.dev1` as an accepted RC7 build.
3. Recheck push/tag workflows before creating or pushing a release tag: the
   existing `v*` tag workflow builds and signs another artifact. Choose one
   authoritative signing path and preserve its exact bytes, manifest and hashes.
4. Use the existing release builder with a clean source commit and verified,
   hash-locked wheels. Assemble the detached signature, trusted public key and
   fingerprint, checksums, installation guide and acceptance record. A
   `--development` source-review archive is deliberately not installable and
   must not be supplied as the installer.
5. Extract and verify the actual signed archive; install its wheels offline into
   an isolated environment and test the delivered application. Preserve the
   source/tag bundle and validation evidence separately from immutable artifacts.
6. Install on a **new disposable Ubuntu 24.04 x86_64 VM**. Verify the published
   candidate checksums and trusted signing fingerprint first. Use the existing
   fresh installer once; do not run it over an existing Freo installation.
7. Check first login/password replacement, two stations, external playback,
   playlist bubbles, import reset, Software page spacing, settings, player,
   statistics, accurate version heartbeat and reboot persistence. Verify HTTPS
   issuance/renewal where applicable and observe uninterrupted playback.
8. Exercise a populated upgrade and encrypted restore using additional disposable
   state. Preserve database, media, settings and installation credentials. Do not
   use either historical accepted candidate VM for destructive rehearsals.

Use `docs/recovery-and-upgrades.md` for the existing signed-bundle upgrade and
recovery procedures. The new kit must carry its own version-specific installation
instructions and pending/completed acceptance record.

Publishing a stable GitHub Release, moving stable/latest pointers and operator
acceptance are separate steps. Preparing this handoff performs none of them.
