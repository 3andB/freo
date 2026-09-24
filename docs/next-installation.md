# Next installation handoff after RC6

## Baseline and preserved release

The owner reported RC6 successful on 2026-09-24. Its delivered signed package,
source tag and test VM remain unchanged. This note supplements that historical
candidate; it does not amend the package or claim that unobserved acceptance
checklist items were independently verified.

The approved production baseline is **0.3.0-rc.7.dev5**, commit
`cd29c398c66665fb7996685c4f7354fb28ee6571`. The next isolated signed candidate is
**0.3.0-rc.8**; RC7 was used only for development identities. Production remains
on its tested baseline while the new VM is tested. See [RC8 installation](rc8-installation.md),
[acceptance](rc8-acceptance.md). The owner scoped this round to a fresh VM;
historical RC5/RC6 upgrade rehearsals are not required for this testing handoff.

The changes after RC6 are:

- Signed-out admin tabs no longer invalidate an open login form's security token.
- LIVE MIC ends before AUTO/DJ tab changes. Leaving the booth warns the owner and
  resumes the interrupted feed; the microphone gateway supports a bounded return
  handoff during page closure. See [LIVE MIC](live-mic.md) for tests and fallback behavior.

- Music import uses the existing playlist bubbles; the redundant playlist list
  is removed. Individual choices, batch defaults and reset after import remain.
- Software and license has inner padding, readable section spacing, bounded
  forms and wrapping for long upgrade messages.
- Browser readiness and CI diagnostics were improved without changing runtime
  licensing, upgrade or broadcast behavior.
- A one-time migration grants installation administration to the existing unique
  `username='admin'` account. It changes no other account fields or users and
  does not select a substitute owner when that username is absent.
- Station settings accept optional city-level latitude/longitude and report them
  through the existing station sync. Existing stations start with null coordinates;
  operators must configure their actual location before a new map pin can appear.
  See [station location reporting](station-location-reporting.md).

The UI fixes need no dependency update. The primary-admin migration advances the
schema from `f39c8210b7de` through `a64f09e2b731`; the optional station-location
migration then advances it to `b72e19d4c603`. The accepted RC5 ancestry is retained.

## Evidence already collected

- Station location client fix: 247 checks passed, with one optional mothership
  source-contract test skipped. This includes both pending migrations on real
  disposable PostgreSQL, restart persistence, authenticated sync serialization,
  unchanged reporting cadence/identity and real browser save workflows. See the
  location handoff for evidence and the unrelated historical index drift found.
- Playlist/import and version checks: 66 passed, including real browser import,
  playlist assignment, defaults for later files and completion reset.
- Existing licensing/upgrade tests: 16 passed.
- Software page: nine isolated layout checks at 390, 820 and 1440 pixels for
  Community, Unlimited, license errors, prepared upgrades and long messages.
  No browser errors or overflowing controls were observed; no real license or
  upgrade actions were submitted.
- Primary-admin migration: 23 PostgreSQL migration/recovery checks passed,
  including missing/disabled/already-privileged primary accounts, repeated
  migration, authenticated Software page access and encrypted backup restore.
  The preservation checker rejected missing grants and unrelated permission,
  password, username, email and active-state changes. The related application,
  updater and artifact suite passed all 105 checks (the signature fixture needed
  a rerun outside the process sandbox to start its temporary GPG agent).
  This is isolated application/recovery evidence; the signed candidate's full
  service upgrade still requires the disposable-VM rehearsal described below.
- GitHub recovery CI and the production deployment receipt must be recorded
  against the exact deployed commit. A successful live deployment does not by
  itself constitute acceptance of a newly built installer.

## Prepare the next signed test installer

1. Finish the owner's live checks of both UI fixes. Record the exact approved
   source commit; include later fixes before choosing the package commit.
2. Give the installation candidate a new identity, `0.3.0-rc.8`, and
   update the existing canonical version metadata and matching tests. Never
   overwrite or repoint RC6. Do not present a development build as an accepted RC8 build.
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
8. Record the fresh installation results against the exact signed package. The
   owner has excluded historical RC5/RC6 upgrade rehearsals from this round.

Use `docs/recovery-and-upgrades.md` for the existing signed-bundle upgrade and
recovery procedures. The new kit must carry its own version-specific installation
instructions and pending/completed acceptance record.

Publishing a stable GitHub Release, moving stable/latest pointers and operator
acceptance are separate steps. Preparing this handoff performs none of them.
