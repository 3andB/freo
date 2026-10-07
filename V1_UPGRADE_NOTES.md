# Freo V1 upgrade notes

## V1 development source installation — 5 October 2026

The development identifier is `1.0.0-dev.1`. This is an unpublished test build,
not a stable 1.0 release, signed kit, or supported 0.3.2 upgrade. The complete
Phase 1–9 source, tests and migrations belong to `develop/v1`; install an exact
reviewed commit from that branch. The public bootstrap at `freo.live/install`
continues to accept only signed stable releases and must not be used for V1.

### Fresh disposable server

Use a blank Ubuntu 24.04 x86_64 VM with root/sudo access and outbound package
access. Install directly from the application repository `3andB/freo`, not the
separate `lee-3andB/freo-live` mothership. No intermediate 0.3.2 installation is
needed. Run only on the disposable test VM (currently `209.38.64.12`):

```bash
git clone --branch develop/v1 --single-branch git@github.com:3andB/freo.git freo-v1-source
cd freo-v1-source
git status --short
git rev-parse HEAD
sudo env FREO_DOMAIN=209.38.64.12 bash scripts/install.sh
```

Confirm that HEAD matches the approved test commit before installing. The VM's
GitHub identity must have read access to `3andB/freo`; access to the mothership
repository alone does not establish that. If Git is absent on the blank VM,
install it first with `sudo apt-get update` and `sudo apt-get install -y git`.
The existing installer installs the application dependencies; no manual database,
Python virtualenv, Nginx or Icecast setup is needed. It installs under `/opt/freo`
on the disposable VM only, with local PostgreSQL and new secrets. This path must
never be confused with `/opt/freo` on the production host. Existing or partial
installation state is refused; preserve failure logs instead of erasing state
and rerunning blindly. `FLASK_ENV=production` in the installed environment means
the hardened Flask configuration, not a stable release or production server.

For external browser microphone testing, first point `v1.freo.world` at the
test VM, allow HTTP/HTTPS certificate validation, and use this installation
command **instead** of the HTTP command above:

```bash
sudo env FREO_DOMAIN=v1.freo.world FREO_ENABLE_HTTPS=1 \
  FREO_CERTBOT_EMAIL=YOUR_CERTIFICATE_EMAIL FREO_LIVE_MIC=1 bash scripts/install.sh
```

After installation, complete mandatory administrator setup and run
`sudo bash /opt/freo/scripts/validate-install.sh`. Do not use stable-update
installation actions on this development source build.

### Services, storage and secrets

- The installer applies the whole migration chain to the new database, through
  `f906a1b2c3d4`, including `f316a1b2c3d4` recording management. Phase 1 scheduling
  migration `f106a1b2c3d4` and its compatibility defaults are described in
  `phase1.md`; existing playlists retain their opt-in scheduling behavior.
- Existing web, PostgreSQL, Nginx, Icecast, automation, ingest, central reporting,
  station provisioning, public schedules, statistics/inventory/GeoIP and updater
  units retain their lifecycle. Managed playout instances start through station
  controls; the diagnostic tone remains opt-in with `FREO_ENABLE_DIAGNOSTIC=1`.
  Relay transport runs inside automation on loopback port 8092; requests, public
  API and platform polish require no separate worker.
- `freo-production.service` is now installed and enabled after migration for
  both ordinary voice-track conversion and optional AI production. Private
  staging `/var/lib/freo/uploads/production` is created as `freo:freo`, mode 2770.
  The service runs as user `freo-ingest`, with the shared `freo` group and its existing
  resource limits. Nginx does not expose this directory.
- A fresh installation generates `FREO_PROVIDER_ENCRYPTION_KEY` independently
  of Flask's session secret and the database password, or preserves a valid key
  supplied privately in the installer environment. Invalid supplied keys are
  rejected before provisioning. The key is stored only in root:freo mode-0640
  `/opt/freo/.env`, not printed. Keep a protected backup separately from database
  backups. The fresh-install refusal prevents accidental key rotation on reruns.
  No ElevenLabs or other provider API credential is generated or required for
  installation/manual voice tracks; enter development credentials through the
  installation administrator's provider settings only when needed.
- `freo-mic.service` is installed but remains disabled unless `FREO_LIVE_MIC=1`
  is explicitly supplied. For source installs that flag installs the existing
  optional Python requirements, imports the initial microphone preference and
  enables the gateway. HTTPS, usable ICE/UDP connectivity and any required TURN
  configuration remain operator responsibilities; port 8091 stays private.
  Later activation must also update the saved installation preference through
  installation settings, then follow `docs/live-mic.md` for station re-rendering
  and restart. Changing `.env` alone does not replace adopted database settings.
- Show recording still requires the existing narrow per-station storage/ACL
  setup. After creating each test station, before its first recorded show, run
  the following on the disposable VM, replacing `STATION_SLUG`:

  ```bash
  sudo /opt/freo/venv/bin/python /opt/freo/scripts/recording-storage.py /var/lib/freo/media STATION_SLUG
  sudo systemctl daemon-reload
  sudo systemctl restart freo-automation.service
  ```

  Start the station afterward, or restart that station's playout instance if
  already running so its new override takes effect. The helper gives playout
  write access, web read-only access and automation deletion access solely to
  that station's recordings. It does not grant broad media write permissions.
- V1 upgrade notes and the public API operator guide are included in the source
  install/customer-file inventory. Tests and the audit remain source-only.

### Registration and validation boundaries

No enrollment token or paid license is needed. The existing reporter automatically
creates a new private installation identity and enrolls with `api.freo.live` when
the installer starts it. This will create a separate mothership record; it does
not remotely provision the server. Use a new disposable owner profile/code for
optional account linking, keep public-directory publication off, and never copy
production `.env`, identity files, provider credentials, database or media.

Focused installation validation uses `/tmp` files and stubbed package, database
and service operations: source copying, unit inclusion/order, private staging,
key generation/preservation/redaction, optional microphone dependency selection,
and refusal of existing state are exercised without running the host installer.
At preparation time, migration graph checks established one complete head, not a
clean PostgreSQL installation result. The subsequent disposable-VM validation
below records actual migration, service, browser and broadcast results separately.
No production bridge, stable bootstrap change, release publication or deployment
is authorized by these notes.

Preparation validation: 119 focused checks passed (111 installer/dependency/
version/production/runtime checks, one real service-account recording ACL check,
and seven inventory/release-guard checks). The ACL proof required a privileged
rerun confined to `/tmp`; the sandbox could not change fixture ownership. Shell
syntax, changed Python/JavaScript syntax, all 81 Jinja templates and Git whitespace
checks passed. These results do not claim full V1 integration or VM acceptance.

Disposable VM integration follow-up: the complete chain applied to an empty
private PostgreSQL database through `f906a1b2c3d4`; Alembic metadata comparison
reported no drift, and settings import/bootstrap succeeded. Three historical
migration regression fixtures needed correction: seed historical Track/Station
columns without current ORM fields, and compare the API migration roundtrip with
the actual current head. All eight focused checks then passed. These fixture
repairs change no migration, schema, or upgrade compatibility contract; they do
not implement or certify the deferred production 0.3.2 → 1.0 bridge.

The full PostgreSQL regression group subsequently passed all 45 cases. The broad
backend run passed 1,266 cases and exposed two more obsolete fixtures: shared
source deletion must be requested from its owning station, and a `create_all`
statistics fixture must round-trip its explicit statistics revision rather than
reapply later, already-present schema additions. Focused corrected checks passed,
including shared-source deletion on PostgreSQL. The bitrate validation message now
lists the supported 192 kbps choice; encoding behavior and the 128 kbps default
are unchanged.

Two standalone Liquidsoap fade regressions also needed their fixture extraction
limited to the `track_fades` function: later relay declarations had been included
in the isolated scripts without their runtime dependencies. Both real-engine
checks passed after correcting the fixture. This changes no broadcast processing
or installation requirement.

On Ubuntu 24.04, Chromium's Snap launcher has a private `/tmp`, while invoking
the native Chromium binary directly does not. Browser upload fixtures distinguish
those launch modes when preparing file-picker paths. The disposable VM tests use
`FREO_TEST_CHROME=/snap/chromium/current/usr/lib/chromium-browser/chrome` and
`FREO_TEST_CHROMEDRIVER=/snap/chromium/current/usr/lib/chromium-browser/chromedriver`.
These are test harness settings, not application environment requirements.
Both corrected file-picker/catalog workflows passed against native Chromium.

Additional PostgreSQL regression fixtures now assert historical login-session,
primary-administrator and station-location changes at their explicit revisions,
then apply the current head before using current application models and handlers.
This avoids mistaking later V1 columns for historical data-preservation failures.
No migration or production upgrade implementation is changed.
All 18 additional PostgreSQL cases passed after these fixture corrections; the
30-round Chromium navigation-retention diagnostic also passed.

Installed-service acceptance on the disposable Ubuntu 24.04 VM verified browser
setup, two timer-provisioned stations, real ingest of generated audio, one shared
underlying asset, and encoded 192 kbps MP3 output from both stations. The optional
microphone dependencies/service and adopted microphone setting were enabled
before station rendering; the per-station recording helper and service reloads
above were applied. Native Chromium/WebRTC reached the installed gateway, kept a
ready microphone off program, broadcast generated microphone audio, and returned
to automation after an unexpected peer disconnect without a three-second silent
gap. A show recording completed. This used a secure loopback browser context;
public HTTPS/DNS and an external physical microphone remain separate acceptance
requirements. No external AI key was configured or provider call made.

HTTP browser integration found that listener requests, production actions and
external player-ad adapters called `crypto.randomUUID()` directly, which is
unavailable on an IP-only HTTP installation. They now share the existing secure
`getRandomValues` UUID fallback in `app/static/uuid.js`. Ship that asset with the
updated base/request templates and client scripts; the source installer already
copies the complete application tree. Nine focused Chromium checks passed across
HTTP/HTTPS setup, requests/embedding, ads and production. The iframe regression
uses eager navigation to inspect nonce rejection before the no-fill timeout.
Microphone capture still requires HTTPS or localhost, and ad frames still require
HTTPS and retain their sandbox and nonce checks.

### Disposable VM endurance and regression evidence

The integration runs use `209.38.64.12` (`Freo-v1-Test-1`), Ubuntu 24.04.5,
Liquidsoap 2.2.4 and Icecast 2.5.0. The application remains `1.0.0-dev.1`.
Generated media, private test databases, credentials and raw evidence are kept
outside Git. Evidence is under root-only `/root/freo-v1-evidence` on that VM.
The development host's production installation is not part of these tests.

The broad browser run covered 155 cases: 151 passed initially, two file-picker
fixtures were corrected and passed, and the optional 30-round navigation-retention
case subsequently passed. The remaining skip is a screenshot-only diagnostic.
The 152-case real-engine group initially had 146 passes, two obsolete fade
fixtures corrected and passed, two intermittent observations described below,
and two opt-in skips. Separate checks passed for two-station stream lifecycle
and 180-second system endurance. External programme-shift fixtures requiring an
additional media bundle were not supplied. Large-catalog benchmarks and the
optional external mothership validator were not run.

Three sequential one-hour real-time integration runs passed:

| Run | Observed result |
| --- | --- |
| Scheduling | 1,066 confirmed starts, 355 mode changes across all six directed Simple/Blocks/Calendar transitions; maximum switch 2.856 seconds; no decoded silence lasting three seconds |
| Track editor | 1,237 confirmed starts, 177 live edits, 11,511 samples; maximum transition 2.906 seconds; no measured clock lag; decoded cue/fade/gain checks passed |
| Analytics | 3,600 seconds, 180 observations, 21,720 independent ledger assertions, 60 browser cycles and 12 CSV checks; all 32 sessions completed and reconciled; 2.723 listener-hours |

The analytics run used real private Icecast connections and generated media, with
fixture geography and desktop/mobile/tablet/player user agents. The longer-run
90-minute collector-gap injection and additional long-duration sessions require
the separate two-hour opt-in; those scenarios were not exercised by this one-hour
run. The existing backend statistics regressions cover gap and duration rules.

Two initial engine failures remain unconfirmed intermittent defects, not fixed
issues: the calendar-16 boundary case measured a 0.4-second programme gap against
a 0.25-second limit, and one short-show recording produced an empty file. Each
passed three serial reruns; the recording also passed an earlier focused repeat
and an approximately 20-second recording on the installed system. The original
failure evidence is retained under `intermittent-engine`. Passing repeats do not
establish a root cause or remove these findings from release acceptance.

Installed HTTP checks also passed for all public API read endpoints, pagination,
cross-station denial, private-field filtering, denied writes and invalid/revoked
credentials (18 requests). An actual DJ login could reach its assigned booth but
not administration, station settings, another station, privilege promotion or API
credential creation. Assignment revocation immediately denied booth access.
Temporary test credentials were revoked and temporary DJ accounts deactivated.
Alembic's read-only `flask --app app:create_app db check` also passed against the
installed PostgreSQL database: no new upgrade operations were detected.

Installed recovery acceptance confirmed the saved STATION voice track in actual
encoded output and the public listener request's single confirmed start after two
preceding music starts. Restarting automation, web, ingest, production, statistics
and microphone services preserved decoded programming. Restarting the station's
Liquidsoap process restored the stream and programme in 14.13 seconds; this is
recovery, not uninterrupted output during an engine restart. Removing the voice
file for 90 seconds and replacing it with invalid bytes for another 90 seconds
each allowed five valid automation starts. Two corrupt voice selections were
observably rejected. The audio probes detected neither silence nor emergency tone
lasting three seconds in those worker-restart/media-failure captures. Restoring
the original file returned it to scheduling without duplicating the completed
listener request. Generated fixtures and the original restored file remain on
the disposable VM only.

A full disposable-VM reboot also passed. A changed boot ID was verified; systemd
reported running after approximately 108 seconds. PostgreSQL, Nginx, Icecast,
web, automation, ingest, production, statistics, microphone and the required
timers returned healthy with no failed units. Station one resumed its persisted
ON state, station two remained stopped, and FFprobe plus decoded audio confirmed
192,000-bit/s MP3 programming. Existing administrator login and the DJ booth's
Live Monitor worked in Chromium after reboot. The listener request remained
completed exactly once. `scripts/validate-install.sh` passed again after reboot.

Overall disposition: **PASS WITH ISSUES for isolated V1 staging**. The two
intermittent engine findings above remain open, and public HTTPS/DNS, external
microphone connectivity and live provider/publisher accounts are not certified.
No production deployment, main merge, tag, stable release/index change or
0.3.2 → 1.0 upgrade bridge was performed. The development host's production
`/opt/freo`, database, services and media were untouched.

Acceptance limits remain explicit: the existing public API supports read scopes
and rejects write scopes; no new write API is implied. Real external ElevenLabs
calls were not made because no development key was configured; provider failures
and production workflows use mocks in the regression suite. Public DNS/TLS,
physical microphone and external-network ICE connectivity, and actual publisher
account creative fill require separate operator acceptance. Loopback WebRTC,
server-side credential boundaries and mocked ad-provider contracts were tested.

## Phase 2 — Track editor (5 October 2026)

Phase 2 extends the existing media editor, request/decision system, and Liquidsoap
mixer. Originals, compatible MP3 preview files, waveform bins, and loudness
measurements remain non-destructive. Nothing in these notes authorizes deployment.
Development is restricted to `/opt/freo-v1` on `develop/v1`; production 0.3.2 is frozen.

### Schema and compatibility

New additive Alembic revision `f206a1b2c3d4` follows Phase 1 `f106a1b2c3d4`.
It adds these `tracks` columns:

| Column | Initial value | Meaning |
|---|---|---|
| `audio_edit_enabled` | false | Explicit audio-editor save activates the policy |
| `audio_edit_revision` | 0 | Atomic revision check for competing saves |
| `fade_in_ms`, `fade_out_ms` | 0 | Linear fades within the selected cue interval |
| `gain_trim_db` | null | Optional −12 to +12 dB adjustment after normalization |

Existing `cue_in_ms` / `cue_out_ms` values are retained but initially inactive,
including automatically detected values. Analysis cannot activate edits or replace
saved blank boundaries. Metadata-only saves do not alter audio settings. An explicit
save activates the chosen boundaries; blank means file start/end. Reset is a draft
until saved and restores full-file playback, zero fades, and no manual trim while
retaining explicit operator ownership of the boundaries.

Nullable `audio_snapshot` JSON columns on `selection_decisions` and
`event_block_item_executions` retain the effective edit policy, duration and gain.
Finite block/playlist executions snapshot their items when created; other decisions
snapshot on preparation for submission. Workers persist the snapshot with existing
submission intent before engine queue mutation, including scheduling handoffs,
decks, carts and events. A crash after engine acceptance cannot lose the prepared
duration/gain policy. Reconciliation and display use that duration,
so later edits cannot change an already loaded request's playback or expected end.
Existing records remain valid with null snapshots and use the existing fallback.

All previous columns, media identifiers, membership, and airplay history are retained.
Downgrading to Phase 1 removes the new policy, revisions and snapshots; cue columns
remain. A downgrade does not recover lost Phase 2 configuration. Back up before any
future rollout and restore a matched code/schema/configuration set for rollback.

### Playback, settings and interfaces

Freo resolves policy and supplies bounded request annotations: `liq_cue_in` and
`liq_cue_out` in source-relative seconds, `freo_fade_in` / `freo_fade_out` in seconds,
and the existing `freo_gain` dB value. The socket adapter retains its strict command,
path, decision and shared-station authorization checks, including batch requests.

Liquidsoap decodes cue boundaries and applies linear envelopes with its existing
`amplify` operator against the source's consumed-audio position. This keeps pauses
from advancing fades and makes a zero envelope exactly unity. The installed 2.2.4
fade-in helper inserts initial silence at zero duration, so that helper is not used.
The track envelope precedes existing deck/transition/ducking gains and station
processing. Automated playback, leaders, decks, carts and events use the policy.
Unedited carts retain their previous gain behavior; edited carts opt into the common
normalization/trim policy. Legacy ImagingAsset playback is retained.

Manual trim follows existing LUFS normalization. The combined gain retains the
−1.5 dB measured true-peak ceiling and existing −60/+12 dB gain bounds. Without valid
analysis, attenuation is allowed but positive trim is suppressed. The editor shows
requested trim, effective gain and limiting. Shortening a track does not reanalyse
its loudness; the existing full-file measurements remain the basis of normalization.

Scheduling estimates, playlist totals, block/traffic capacity and Booth playback
information use the selected duration; file metadata, storage metrics, and waveform
coordinates retain full source duration. Existing programming refresh handles future
automatic requests without interrupting current audio, manual loads or finite events.
Calendar overlap warnings use the shared event estimator, including smart playlist
members, playlist leaders, and ONE/ALL playback policy.

Existing catalog responses add an `audio` object with saved/effective settings,
revision, source/playable duration and gain information. The new protected endpoint
`POST /admin/api/stations/<slug>/song/<uuid>/audio` accepts the existing form `csrf`
and JSON-encoded `data` fields, using integer millisecond boundaries/fades, numeric
`gain_trim_db`, and `revision`. Blank/null boundaries mean file edges. It returns
updated catalog state, 400 for invalid settings, or 409 for a stale revision or
decommissioned track. Existing station access rules and audit records apply.

### Editor and preview

The existing canvas gains cue/fade handles plus keyboard and numeric editing. Drafts
survive status polling. Saving is explicit and rejects stale revisions; reload obtains
the current version. Missing waveform data does not disable numeric editing.

Browser preview uses the existing audio element and Web Audio gain node. Ramps and
cue-out muting use the audio clock; pause, seek, buffering/resume and playback-rate
changes rebuild the envelope against source position. A fresh library audition
reloads saved settings, including when auditioning the same song again. Edited preview
can audition unsaved settings. Original audition bypasses edits and normalization.
Browser volume remains a listening control. Edited preview represents track policy
before station EQ/AGC, live mixing, limiting and output encoding; it is not an exact
render of the complete broadcast chain. Browser/codec seek precision can differ from
Liquidsoap. No new preview-rendering job or persistent derivative is introduced.

### Future rollout requirements — not executed

Apply the additive migration with the matching application code in an isolated V1
environment. Regenerate managed station Liquidsoap configurations from the updated
template, validate them using the installed Liquidsoap version, and restart the
relevant V1 web/automation/ingest/playout services through the existing lifecycle.
Do not activate track edits against an old engine template. Verify real cue/fade
playback and confirmed START/END before accepting a rollout.

The current managed updater rejects changed radio/proxy templates and checks a
release manifest's supported source revisions. This branch is not a production
upgrade package: a separately tested maintenance procedure and release compatibility
declaration are still required. Phase 2 does not weaken those updater guards.

No new environment variables, services, ports, users, filesystem roots, permission
changes, package dependencies or media transformations are introduced. Existing
worker/storage ownership remains unchanged. This development task does not apply
migrations to production, regenerate production configurations, restart production
services, deploy, publish releases, or merge to main.

### Validation and deferred work

Final results are recorded in `phase2.md`. Tests use temporary SQLite/PostgreSQL
storage, private HTTP/engine sockets and generated audio; no production database or
catalog is used. Deferred: destructive editing, segue/crossfade redesign, automatic
cue activation, complete station-processing emulation in preview, and production
rollout/long-running real-catalog acceptance.

The optional endurance test uses `FREO_PHASE2_SOAK_SECONDS=3600` and
`tests/test_phase2_soak.py`. This is a test-only setting, not a service configuration.
It renders the approved managed template with local generated audio and a private
file output, exercises actual worker/schedule transitions and editor saves, checks
confirmed starts and immutable snapshots, and retains only four rolling audio clips.
Run it after other heavy tests have finished. Both continuous decoded silence and
Liquidsoap wall-clock lag are checked; clock lag of three seconds fails the run.

## Phase 3 — DJ permissions, live shows and recording (5 October 2026)

This phase extends the existing booth, automation worker, mixer and WebRTC gateway.
It does not install an alternate broadcast state controller. All work is restricted
to `/opt/freo-v1`, branch `develop/v1`. No rollout commands below were executed.

### Schema and backward compatibility

Additive Alembic revision `f306a1b2c3d4` follows `f206a1b2c3d4`:

- `admin_users.role`: `ADMIN` or `DJ`, with `ADMIN` as the migration and legacy
  creation default. Every existing account retains its prior administrative access.
  `installation_admin` remains an independent, unchanged privilege.
- `dj_station_assignments`: composite account/station primary key and cascading
  foreign keys. A newly created DJ has no access without explicit assignments.
- `live_sessions`: durable ownership, station, DJ name snapshot, recording choice,
  creation/start/end timestamps, return request/reason and engine identity. A unique
  nullable `active_station_id` enforces one owner per station, including pending
  shows. History retains the station; account deletion nulls the account reference.
- `show_recordings`: one recording per opted-in show, with station/DJ references,
  generated storage key, capture timestamps, measured duration, bytes, status and
  error. Statuses are pending, recording, finalizing, complete, partial and failed.
- `live_queue_snapshots.show_observation`: the worker's sanitized observation of
  existing engine state and observation timestamp. No microphone token is exposed.

Downgrade removes these fields/tables, including permission restrictions and show
history, but leaves recording files. Consequently, old code would restore global
administrative access to DJ accounts: disable those accounts before any downgrade.
Use a matched code/schema/configuration rollback and preserve a database backup.
Station deletion retains show history and files rather than cascading their loss.

### Permissions and interface

`/admin/djs` lets administrators create DJs, explicitly convert eligible existing
accounts, enable/disable DJs and replace station assignments. The current account
and installation administrators cannot be converted there. Passwords use existing
scrypt hashing and the existing 16-character minimum. The root-run
`flask admin account-role EMAIL ADMIN|DJ` command provides explicit role recovery;
it does not grant station assignments or installation administration.

Assigned DJs can use the booth, decks, carts, station IDs, Cue, searches, previews,
artwork and live microphone. Administrative library edits, programming, settings,
account management and installation controls remain administrator-only. A closed
endpoint allowlist, station checks and filtered selectors enforce this server-side.
Public listener pages and previously public metadata remain public.

The DJ who enters DJ mode or requests GO LIVE owns the show. Other assigned DJs
can observe, but cannot change the booth or signaling. Administrators can request
`POST /admin/stations/<slug>/live/end-show` to return it to automation. Ownership
checks also apply when the worker executes queued manual selections/commands and
renews microphone leases. Revocation uses existing AUTO return and microphone lease
expiry/departure. A pending claim that never broadcasts expires after five minutes.

The existing live-status response adds `show`: confirmed source (`AUTO`, `DJ`,
`MIC`, `RETURNING`, or `UNKNOWN` when stale), owner/name, session ID, timestamps,
return status and recording status/error. The booth displays it without replacing
existing deck controls. Station overview also displays show state. Merely opening
the booth, preparing decks or testing a microphone does not count as broadcasting.
Booth and mic transitions share one session until confirmed automation return.
Older station templates retain booth operation using their existing mixer/mic observations; timestamps then reflect worker observation times, and recording reports missing capability until re-rendered. Observation freshness is ten seconds. Engine restart/interrupted station shutdown
retains the interruption reason without inventing an exact session end timestamp.

### Recording and storage

“Record this show” is unchecked by default and selected before entry/GO LIVE. The
choice is fixed for that show and resets afterward. Recording is not retroactive.
The worker arms the engine before takeover. Liquidsoap records the final mixed,
processed program, including audible carts, station IDs, mic and fallback, as
192 kbps MP3 (approximately 86 MB/hour). It does not capture off-air microphone
checks or create podcast/library assets.

Files use generated 32-hex keys under
`FREO_MEDIA_ROOT/<station>/recordings/<key>.mp3`. Existing storage path validation,
regular-file checks and symlink rejection apply to authenticated file delivery.
The worker validates closed files with existing `ffprobe`; completed and recoverable
partial files can be played/downloaded at `/admin/stations/<slug>/recordings`.
Administrators see all; DJs see only their own recordings on currently assigned
stations. Direct audio/download URLs repeat authorization and use private/no-store
responses. There is no public recording URL, automatic expiry, publishing or editor.

Recording startup failure, low space and interruption are visible separately from
broadcast status. Arming/renewal requires at least 256 MiB free; checks run on worker
observations. Liquidsoap stops capture on automation return or a 15-second worker
lease expiry. Interrupted captures become partial when decodable, otherwise failed.
Restart recovery never silently overwrites or resumes an existing MP3. Retained
recordings are included in existing storage inventory and its UI breakdown. Operators
must manage retention; files are not automatically deleted by this phase.

### Liquidsoap, services and future activation — not performed

The managed station template adds read-only `freo_show.state` and narrowly validated
`freo_record.arm/lease/stop/state` commands. File output is fallible and separately
startable/stoppable, with error handling independent of the final Icecast output.
Source observations derive directly from existing mixer standby, fade progress and
microphone phases. No new gateway, daemon, port or package dependency is introduced.
The existing automation worker owns all recording commands and finalization.

After applying the migration and matching V1 code in an isolated environment:

1. Provision recording storage for each participating station using the supplied
   root-run helper: `python scripts/recording-storage.py MEDIA_ROOT STATION_SLUG`.
   Use the installation's actual `FREO_MEDIA_ROOT`. The helper creates only that
   station's recordings directory, owned by `freo-playout:freo-playout`. The web
   account receives read access; the automation account receives read access plus
   directory write access for queued deletion. Existing audio directories remain
   read-only to playout. Narrow systemd drop-ins permit recording-directory writes
   for playout and automation; the helper does not start/reload any service.
2. Review the generated drop-in, reload systemd, render/validate the participating
   station configurations using the existing lifecycle, then restart matching V1
   playout/web/automation services in a maintenance window. End shows first.
3. Use consistent media-root configuration in renderer, web and worker. Repeat the
   provisioning step for newly added stations before recording there. The existing
   media web ACL repair helper now includes recordings.
4. Verify recording playback, file ownership, storage accounting and failure handling
   on the V1 station. Missing storage or old engine capabilities must not be treated
   as recording readiness.

No new environment variable is required. The deployment inventory includes the new
provisioning helper. The managed updater's existing template-change restrictions
remain intact; these notes do not authorize bypassing them or deploying this branch.

### Deferred external encoder integration

External encoders remain deferred. Future source admission should use the same
station assignment and exclusive session owner checks, expose confirmed engine
transitions through the existing observation path, and enter the program upstream
of final processing/recording. Browser microphone tokens must not become encoder
credentials. Authentication, mount/transport selection and source-loss handoff need
separate design. Also deferred: podcast feeds, editing, scheduled retention,
mid-show recording toggles, production deployment and physical/WAN microphone tests.

### Phase 3 validation results

168 distinct focused/regression cases passed across the completed runs:

| Coverage | Result |
|---|---:|
| Existing booth, automatic return, station rendering/audio, web, Cue and statistics regressions | 110 passed |
| Phase 3 permissions, ownership, sessions, recording access/storage and SQLite migration tests | 15 passed |
| Full PostgreSQL migration preservation and simultaneous-owner race | 2 passed |
| Existing gateway/browser scenarios plus new opt-in/ownership browser checks | 34 passed |
| Real Liquidsoap recording and WebRTC/microphone audio scenarios | 7 passed |

Real-audio checks measured deck, microphone and cart frequencies in the completed
MP3, verified automation-return closure and opt-out behavior, recovered a partial
recording after lease expiry, and forced file-open failure while the program output
continued growing. Existing microphone fades, cart ducking/takeover, intentional
page exit and abrupt-loss fallback also passed. Browser checks verified that other
DJs cannot control the show, recording choice resets, and the existing standby
indicator remains visible. An initial standby-label regression was corrected and
its original test passed on rerun. Initial sandbox socket restrictions were resolved
by running isolated local test servers; no production endpoint was used.

The PostgreSQL tests used a newly initialized cluster under `/tmp/freo-phase3-pg`
with private Unix sockets, then stopped it. Other tests used disposable SQLite
storage, generated audio, private engine sockets and disposable browser profiles.
Evidence directories are under `/tmp/freo-phase3-*`. JavaScript syntax checks,
Python parsing/imports and `git diff --check` passed. This is targeted validation,
not a claim that every repository test or production/WAN scenario was run.

Development remained in `/opt/freo-v1` on `develop/v1`. `/opt/freo` production,
production data/services, `main`, tags and releases were not modified. No deployment
or merge was performed. The pre-existing untracked `V1_AUDIT.md` was left intact.

### Phase 3 follow-up — local MP3 recording manager

- Added migration `f316a1b2c3d4` after `f306a1b2c3d4`. It adds recording
  names, optimistic revisions, deletion request timestamps/requesting account,
  deletion completion timestamps and deletion errors. Existing recording keys,
  media files, show history, account roles and station assignments are preserved.
  Downgrading this migration drops only manager metadata; it cannot recover an
  MP3 that has already been deleted.
- The existing Show recordings / My recordings page now supports local MP3
  playback and byte-range downloads, renaming, search by filename or DJ, status
  filters, sorting by name/date/size/duration, pagination and confirmed deletion.
  A rename changes the displayed/downloaded MP3 name, leaving the generated
  internal storage key unchanged. No arbitrary filesystem paths are accepted.
- DJs may list, play, download, rename and delete only their own recordings on
  currently assigned stations. Administrators may manage all station recordings.
  Renames/deletions require CSRF and the current revision; active shows and
  unfinished recordings cannot be edited. Deactivation revokes existing login
  sessions, including after later reactivation. Assignment changes are enforced
  on subsequent requests and again by the worker.
- Deletion is durable work for the existing automation worker, including stopped
  stations. Downloads stop immediately when deletion is queued. The worker
  rechecks current permissions, removes only a validated generated regular MP3,
  and retains show history, a deletion timestamp and audit entries. Missing files
  count as successful cleanup; symlinks and storage errors are refused and shown
  for an explicit retry. There is no automatic retention policy or recycle bin.
- **Storage permission update:** rerun `scripts/recording-storage.py MEDIA_ROOT
  STATION_SLUG` for each V1 station when activating this version. In addition to
  the existing playout override, it writes
  `freo-automation.service.d/recordings-STATION_SLUG.conf` with `ReadWritePaths`
  limited to that station's recording directory. Its ACL grants the automation
  account directory write access for deletion; the web account remains read-only.
  Reload systemd and restart the V1 automation service after provisioning. Use
  the unit names/paths for the isolated V1 installation; do not run against a
  production installation as part of development. These operations were **not**
  performed during this task.
- Operators can now manage retention through the manager's deletion flow. Local storage remains `FREO_MEDIA_ROOT/<slug>/recordings/<key>.mp3`,
  encoded by the existing final program branch at 192 kbit/s MP3. Recording still
  requires the Phase 3 Liquidsoap template and explicit opt-in before the show.
  No additional audio engine changes were needed for file management.
- Review fixes: draft website previews now require an administrator; disabled
  station logo/player artwork previews require station access; mixed-case DJ
  names work at login; booth controls recover after another show releases the
  station; revoked microphone preparations are rejected before engine admission;
  deleted recordings no longer appear as missing files in storage statistics;
  completed-import polling reuses its authorized station to avoid per-song queries;
  playlist navigation summaries retain leader/rule/weight metadata without
  loading track objects. The historical release-schema test now checks ancestry.
  Recovered worker-owned AUTO_CUE commands require their durable playback binding
  and valid show ownership; orphaned human commands remain denied. Arming AUTO_CUE
  now claims the operator's show through the same session infrastructure.
- See `PHASE3_REVIEW.md` for the verification report, test scope and remaining
  deployment requirements. External encoder input remains deferred; the existing
  ownership, engine observation and final-program recording boundaries remain
  suitable integration points for future encoder support.
- Follow-up validation includes 29 existing booth/browser cases, seven new
  browser cases across split runs with real account creation/login, 56 focused
  Cue/permission/scheduling cases, eight real audio cases and two real-engine Cue
  recovery cases. PostgreSQL migration/concurrency and actual service-account
  filesystem permission checks passed on disposable resources. The report lists
  additional results, resolved failures and the broad simulations that did not
  complete; these counts overlap and are not a whole-repository pass claim.

## Phase 4 — listener analytics improvements

- Extends the existing statistics collector, dashboard and CSV export with device
  groups, recognizable browser/player families, observed session starts,
  completions, average completed duration, duration bands and duration retention.
  Existing realtime/history, peaks, listener-hours, maps, music, resource and
  reliability reports remain available. No external tracking is introduced.
- **Schema:** migration `f406a1b2c3d4_listener_sessions.py` follows
  `f316a1b2c3d4`. It adds nullable JSON `stats_presence.listening` and the
  `stats_session_buckets` table keyed by station scope and UTC hour, with an hour
  index. The JSON contains fixed-category counters, durations and coverage;
  temporary presence contains normalized categories and an epoch hash, never raw
  agents or addresses. Downgrade drops only the new data/column and clears Phase 4
  checkpoint fields, preserving the original statistics and catalog.
- **Storage/retention:** anonymous session aggregates last five years. Existing
  presence cleanup remains one day. Collection and cleanup run in the existing
  `freo-stats` worker and transaction. No new daemon, package, configuration key,
  filesystem path or permission grant is required.
- **Measurement:** starts occur at first observation; completed durations use
  consecutive observations at most 45 seconds apart. A valid list confirms
  departure; gaps and epoch resets interrupt sessions and exclude them from
  completed-duration statistics. Active sessions are separate. Current categories
  use valid fresh stream lists; historical categories count observed starts.
  Website visitors remain separate. Session-history boundaries expand to UTC
  hours and are returned in JSON, displayed in the UI and included in CSV. Starts
  use the first-observed hour; completions/full durations and interruptions use
  the last-observed hour. Client-list coverage is distinct from audience coverage.
- **Compatibility/access:** existing JSON fields and CSV sections remain; new
  `sessions` and `devices` fields and CSV sections are additive. Administrator
  access and DJ denial are preserved, with selected-station filtering also applied
  to embedded channel metrics. Duration/device history starts with Phase 4;
  geographic session-hours cannot reconstruct earlier duration distributions.
- **Activation order for a future authorized V1 rollout:** back up the V1 database,
  stop its statistics worker, apply the migration, then start matching updated
  web/statistics workers. No playout restart is needed. This task did not run
  migrations on an installation or restart deployed services.
- **Deferred:** historical duration backfill, exact durations between polls and
  returning-listener identification. User-agent classification is best effort;
  unrecognized clients remain other/unknown. Full definitions are in
  `docs/statistics.md`.
- Work is confined to `/opt/freo-v1` on `develop/v1`, preserving prior uncommitted
  Phase 3 work. Production application files in `/opt/freo`, main, tags and releases are
  untouched; no deployment or merge was performed.

Phase 4 focused validation (2026-10-05; 73 distinct cases across these suites):

| Check | Result |
| --- | --- |
| Existing statistics accounting, maps, routes and export (`test_statistics.py`) | 15 passed |
| Classification, sessions, gaps/restarts, privacy, scope, retention and SQLite migration (`test_statistics_sessions.py`) | 37 passed |
| Existing DJ permissions and station ownership (`test_phase3_dj.py`) | 16 passed |
| Real Chromium statistics/device/session views, CSV, maps, navigation and mobile layout (`test_statistics_browser.py`) | 3 passed |
| Full PostgreSQL migration chain, downgrade/re-upgrade preservation and concurrent collector retries (`test_statistics_postgres.py`) | 2 passed |
| JavaScript syntax and patch whitespace | Passed |

Tests used `PYTHONDONTWRITEBYTECODE=1 FREO_ENV_FILE=/dev/null` and isolated SQLite
fixtures. Browser checks used a temporary loopback server. PostgreSQL checks used
a disposable cluster under `/tmp/freo-phase4-pg-*`, a private Unix socket on port
55484, no TCP listener, and automatic shutdown. Initial sandbox restrictions on
local sockets/directory ownership were resolved through approved isolated test
execution. An added PostgreSQL fixture's JSON binding error was corrected before
the final passing run. The remaining migration warnings are the existing
Flask-SQLAlchemy `get_engine` deprecation. These are focused results, not a
whole-repository test claim; no production database or service was used.

### Phase 4 statistics accuracy and visual review

- Fixed missing transfer intervals being drawn/exported as zero, stale peaks
  outside the report window, and incident totals being limited to the latest
  100 detail rows. CSV now also carries the existing summary metrics. Numeric
  legacy JSON fields remain; nullable transfer values/coverage and complete
  incident counts are additive.
- Automatic refresh preserves sorting and heading focus and uses the last
  applied filters. Charts retain readable labels on narrow screens; session
  cards, duration/category share bars, mobile tables and day/night maps were
  refined and checked in Chromium.
- No additional migration beyond `f406a1b2c3d4`, configuration, service, storage
  path or permission change is needed for these review fixes. Existing Phase 3
  work was committed separately as the required prerequisite.
- Focused reruns passed 58 statistics/session/reporting cases, six disposable
  PostgreSQL migration/concurrency cases, 31 DJ/recording regression cases and
  four Chromium cases. A further final visual check passed with 20 screenshots.
  The actual 7,200-second private-stack recording run reconciled all 1,164 stored
  listener samples and all six duration bands. Its final pytest assertion had a
  harness-only report-cutoff error; the corrected full-data reconciliation,
  targeted regression and fresh 90-second live confirmation passed. The original
  failed run status is preserved in `docs/statistics-validation-v1.md` and its
  linked evidence summary.
- No deployed services were restarted: this checkout has no separate deployed
  V1 service, and the existing host units point at production. Production
  application files, main, tags and releases remain untouched. This is a linked
  worktree, so authorized development commits use shared Git metadata under
  `/opt/freo/.git`; that metadata is distinct from the production checkout.

## Phase 5 — listener requests (5 October 2026)

Listener requests extend existing category/rotation, playlist and visual schedule
selection, including flexible music sections within shows and blocks. They create
normal `SelectionDecision` records and use existing queue, deck, programming-refresh
and confirmed START paths. No new scheduler, playout engine, daemon, dependency or
Liquidsoap template change is introduced.

### Schema and activation

Additive migration `f506a1b2c3d4_listener_requests.py` follows `f406a1b2c3d4`:

- `stations.request_settings`: JSON, initially `{}` (disabled defaults).
- `listener_requests`: station/track references, anonymous listener key and retry
  nonce, submission/expiry/played timestamps, status, reason and selection evidence.
  Station/status/time and nonce constraints support queue lookup and idempotency.
- `selection_decisions.listener_request_id`: nullable request binding; multiple
  historical attempts remain explainable through existing decisions. Only one
  outstanding attempt is admitted under the station lock.
- `request_rate_buckets`: short-lived station/network/action/minute counters.

Existing stations, playlists, decisions, history and media remain intact. Downgrade
removes only Phase 5 metadata and bindings; it cannot undo completed airplay.
For a future authorized V1 rollout, stop the V1 web/automation processes, back up the
V1 database, apply the migration, then start matching web/worker code. No engine
configuration regeneration is needed. End live shows and clear outstanding request
loads before rolling back. No installation migration, service restart or deployment
was performed during this development task.

### Settings and selection semantics

Station Settings adds enabled, delay in songs, extra track/artist separation in
songs, current-programming restriction, listener cooldown, per-listener maximum and
station maximum. Defaults are disabled, 3/10/3 songs, restriction on, 5 minutes,
2 per listener and 100 per station. Song values accept 0–1,000; cooldown 0–1,440
minutes; listener maximum 1–100; station maximum 1–10,000. The existing settings
fingerprint protects concurrent edits. Expiry is fixed at 24 hours.

Only confirmed program music starts **after submission** count toward the delay.
The already playing song, imaging, commercials, off-air loads and unconfirmed queue
entries do not count. Existing lookahead can make playback later than the minimum.
Current/recent tracks and artists are accepted and held. Request separation never
uses the normal selector's exhaustion relaxation; existing time-based automation
separation also applies. Artist comparison reuses Phase 1 normalization.

The oldest eligible request wins a flexible music selection, preserving the current
clock/rotation slot context and existing cursor checkpoints. Playlist/shuffle cursor
state is held so normal order resumes afterward. Restrictions use the actual source
or rotation category for that opportunity and current smart-playlist membership.
With restrictions off, other available station music can use a flexible music slot.
Leaders, explicit scheduled songs, finite event blocks, commercials and timed events
are preserved; an incidental fixed-item play does not fulfill a listener request.
Empty sources retain the existing scheduling/fallback behavior.

States are pending, eligible, queued, played, rejected and expired. Eligibility can
return to pending. Requests bind atomically to decisions, and only confirmed START
marks them played. Uncertain submissions wait for complete engine inventory and the
confirmation window before retry; recovery retains decision identity. Late START
is retained as actual airplay, even after expiry/rejection, and other future attempts
are withdrawn. Separate listeners' requests remain separate: one bound start fulfills
one request. A listener's duplicate outstanding request for the same track is reused.

Disabling pauses unselected requests until expiry and withdraws future request
selections through the worker. Rejection/expiry likewise cancels future selections;
currently playing audio finishes. Programming/settings changes use existing automatic
lookahead refresh; stopped DJ decks are cleared only by the worker. Eligibility and
ownership are checked again before loading/taking a request. Normal automation
continues when no request qualifies. Expiry/privacy housekeeping runs at most every
30 seconds in the existing worker, including stopped stations.

### Public access, DJs and privacy

- `/requests/<public-slug>` is a standalone, responsive request page that also works
  in an iframe. Station Settings supplies a link and embed code. Only this page gains
  permissive framing; administration keeps its existing framing policy.
- `GET /api/stations/<public-slug>/requests?q=...&offset=...` returns paginated
  UUID/title/artist records and a signed anonymous station token. Public discovery
  includes playable owned/shared station music, irrespective of current programming;
  unavailable/nonmusic/private metadata and media file URLs are excluded.
- `POST` to that API accepts JSON `track` and UUID `nonce`, with `X-Request-Token`.
  Requests use no admin cookies and check Origin/fetch context. There is no public
  request-history enumeration, login, listener name, comment field or fingerprint.
- A random station-scoped browser token lasts at most 48 hours. Local storage preserves
  it where available; the widget works with third-party cookies blocked. Limits are
  best effort for anonymous listeners: clearing storage can reset browser identity.
  Network throttling separately limits submissions to 30/minute and catalog/bootstrap
  to 120/minute per station/network, returning `429` and `Retry-After`.
- Rate counters contain a daily keyed address hash, never a raw address or user agent;
  counters expire after 24 hours. Terminal requests lose their anonymous listener key
  and nonce once the submission cooldown window has passed (minimum one minute).
  Sanitized lifecycle history remains. No analytics fingerprint or external service
  is added. Existing proxy/client-address trust configuration remains unchanged.
- Administrators and assigned DJs can open `/admin/stations/<slug>/requests` and see
  a short pending list in the booth. The inbox filters status and shows waiting
  reasons. Only administrators can reject/remove requests or change settings.
- The show owner can load an eligible request on a stopped A/B deck. This submits an
  existing durable `DECK_LOAD` command with play-on-load disabled; deck controls
  determine when it airs. Assigned DJs cannot change another station or another
  owner's show, and worker ownership checks remain in force.

### Validation and deferred work

Validation uses disposable databases, private sockets/loopback servers, temporary
browser profiles and generated audio. Initial template syntax and test-inventory
fixture errors were corrected. Sandbox restrictions on PostgreSQL ownership and
browser/engine sockets were resolved through approved isolated test execution.
Completed checks (run counts overlap; this is not a whole-repository pass claim):

| Check | Result |
| --- | --- |
| Request timing, strict separation, selection paths, fixed programming, recovery, API privacy/limits, permissions, DJ intent and SQLite migration | 27 passed |
| Automation, Phase 1 scheduling, programming refresh, playlists, DJ permissions and live-assist regression run (includes 23 earlier request cases) | 127 passed; 2 opt-in engine cases skipped |
| Station Settings and schedule regression cases in the follow-up run | 32 passed |
| Full PostgreSQL migration chain, downgrade/re-upgrade preservation, concurrent capacity and selection claims | 2 passed |
| Chromium cross-site iframe with third-party cookies blocked, settings save, mobile layout and DJ load intent | 2 passed |
| Private Liquidsoap request START/recovery and existing short/long playlist leaders with generated audio | 3 passed |
| Final automatic-tail cancellation and programming-refresh rerun | 13 passed |
| Python parsing, JavaScript syntax and patch whitespace | Passed |

The final request-only rerun includes the corrected mode-switch fixture (its first
run omitted a required existing field). A repeat PostgreSQL/engine run was terminated
by the test environment; fresh PostgreSQL and real-engine reruns passed. PostgreSQL retains the
existing Flask-SQLAlchemy `get_engine` deprecation warning; the playlist regression
retains its existing fixture-session warning. Browser screenshots and private engine
artifacts are under `/tmp/freo-phase5-*`; these are disposable test evidence.

Deferred: production rollout, long-running production-catalog/WAN acceptance,
listener accounts, CAPTCHA, configurable expiry and request deduplication across
listeners. These are not required for the anonymous V1 workflow.

Work remains in `/opt/freo-v1` on `develop/v1`. `/opt/freo` production application,
production databases/services, `main`, production tags and releases were untouched.
No deploy, merge or release operation was performed. The pre-existing untracked
`V1_AUDIT.md` was left intact.

## Phase 6 — Public API

The existing Flask application now serves a versioned, read-only API under
`/api/v1`. It reuses station permissions, confirmed player observations, scheduling
resolution, cached listener statistics, and library sharing rules. Existing UI,
unversioned public APIs, ingest, scheduling, automation and listener requests retain
their behavior. No separate API application, runtime dependency or service is added.

### Schema and credential management

Migration `f606a1b2c3d4_public_api.py` follows Phase 5's `f506a1b2c3d4` and adds:

- `api_credentials`: public identifier, name, SHA-256 token digest, read scope,
  issuing administrator, creation time and revocation time.
- `api_credential_stations`: explicit credential/station grants; newly created
  stations are never implicitly authorized.
- `api_rate_buckets`: shared, atomic request counters, indexed for expiry cleanup.

Apply the normal migration workflow before running this version. Downgrading Phase 6
removes these three tables and all API credentials; it preserves Phase 5 requests,
station settings and airplay history. Re-upgrading requires issuing new credentials.

Active ADMIN users manage credentials at `/admin/api-credentials`, linked from Radio
Station Ops. DJs have no credential-management permission. Creation and revocation
use existing browser authentication, setup checks, CSRF and audit events. The page
shows the token only in the successful creation response, with no-store caching.
Only the digest is persisted: tokens do not enter sessions, flash messages or audit
records. Credential metadata and revocation remain available to administrators.

Tokens combine a public random identifier and a 256-bit random secret. V1 accepts
them exclusively as `Authorization: Bearer …`, checks their digest in constant time,
and rechecks issuer authority and revocation on each request. Deleting/deactivating
the issuer, changing its role to DJ or requiring setup disables its credentials.
Credentials have read scope only, with no automatic expiration. Rotation and scope
changes use replacement followed by revocation.

### Endpoints and security boundaries

The seven GET routes are:

- `/api/v1/stations`
- `/api/v1/stations/<slug>`
- `/api/v1/stations/<slug>/now-playing`
- `/api/v1/stations/<slug>/schedule`
- `/api/v1/stations/<slug>/listeners`
- `/api/v1/stations/<slug>/library/tracks`
- `/api/v1/stations/<slug>/library/tracks/<uuid>`

Use canonical station slugs, not public aliases. Every station route requires an
explicit grant, including nested track lookups. Station lists contain only granted
stations; deleted/deleting stations are excluded. Music shared through Freo's existing
track/artist/album availability rules remains intentionally accessible to consuming
stations. Unavailable and private foreign tracks return 404.

Responses select fields explicitly and exclude file paths, storage keys, passwords,
infrastructure configuration, raw listener identity, and administrative internals.
Now-playing uses fresh confirmed observations. Listener counts use cached measurements
and return null for unknown/stale current audience. Schedule reads resolve active
programming without publishing, enqueuing or changing worker state.

V1 uses JSON data/error envelopes, bounded pagination/search, UTC timestamps,
consistent 400/401/403/404/405/429/500/503 responses, Bearer challenges on 401, and
no-store response headers. The API supports no data writes and no browser cookie
authentication. Existing endpoints retain their original response/error behavior.

Limits are 120 requests per credential per UTC minute and 300 per client network
address per minute, enforced atomically in the existing database across workers.
429 includes Retry-After. Proxy handling reuses `DMCA_TRUSTED_PROXY_IPS` and trusts
X-Real-IP only from configured peers. Rate records use a daily keyed address hash,
never a raw address, and request-time cleanup removes buckets older than 24 hours.
No new environment setting, background task or external rate-limit service is needed.

See [Public API v1](docs/public-api-v1.md) for endpoint fields, request examples,
pagination, schedule horizons, listener coverage and credential lifecycle details.

### Validation and deferred work

Validation uses temporary SQLite databases, a disposable PostgreSQL cluster, and a
private Chromium profile/loopback server. No production database or service is used.

| Check | Result |
| --- | --- |
| API credentials, authentication, station/library scope, safe fields, pagination, errors, limits, schedule modes/DST and SQLite migration | 52 passed |
| Existing web UI and player behavior | 23 passed |
| Existing analytics accuracy, library availability and Phase 5 listener requests | 47 passed |
| Existing visual scheduling | 21 passed |
| Disposable PostgreSQL full migration chain, Phase 5 preservation, downgrade/re-upgrade, revocation and concurrent counters | 3 passed |
| Chromium credential creation, one-time display, revocation and mobile layout | 1 passed |
| Final JSON OPTIONS/HEAD and UTC now-playing checks (overlap the API suite) | 3 passed |
| Phase 6 Python syntax and patch whitespace | Passed |

These are focused checks, not a whole-repository pass claim. Initial new-test fixture
errors were corrected. The environment terminated the first combined regression run;
the completed split runs above passed. Sandbox PostgreSQL ownership and browser socket
restrictions were resolved through approved isolated test execution. PostgreSQL tests
retain the existing Flask-SQLAlchemy `get_engine` deprecation warning. Temporary test
artifacts are under `/tmp/freo-phase6-*`; screenshots exclude the one-time token.

Deferred: public write operations, webhooks, OAuth, developer portals, SDKs, GraphQL,
automatic token expiry, and elaborate API management. No integration requiring a
safe public write operation was identified for V1.

Work remains in `/opt/freo-v1` on `develop/v1`, preserving the pre-existing Phase 5
changes and `V1_AUDIT.md`. `/opt/freo` production application, databases and services,
`main`, production tags and releases were untouched. No deployment or merge occurred.

## Phase 7 — Managed upstream relay streams

Relay is configured per station in **Station settings → Upstream relay**. Only
existing station administrators can change it; operator/DJ and public API credentials
cannot. Saves use CSRF protection, revision checks, and an audit entry without the
upstream URL. Enabling relay creates/enables the existing automation worker state so
local fallback can be prepared; current DJ control is preserved. Disabling relay
leaves local automation available.

### Migration and configuration

Migration `f706a1b2c3d4` follows Phase 6 (`f606a1b2c3d4`) and adds `station_relays`:
station-owned enable/URL/revision settings and safe runtime observations. No existing
station is opted in. Downgrading removes relay settings only; earlier phase data is
preserved. Apply migrations before running updated application/worker code.

New optional environment values, documented in `.env.example`:

- `FREO_RELAY_PRIVATE_NETWORKS`: comma-separated operator-approved private CIDRs;
  empty by default. Loopback requires an explicit allowance. Link-local, multicast,
  unspecified and cloud metadata link-local addresses remain forbidden.
- `FREO_RELAY_TRANSPORT_PORT`: default `8092`, bound only to `127.0.0.1` by the
  existing automation worker when the first relay is enabled. Do not expose this
  port through Nginx. No separate relay daemon, unit, or package is required.

Liquidsoap 2.2.4's HTTP decoder does not expose the redirect enforcement needed for
network scoping. A small transport guard in the existing worker therefore validates
and pins the resolved destination on every connection, verifies HTTPS certificates
against the original hostname, rejects redirects and playlists, and forwards audio
and ICY metadata bytes without decoding. Per-station random capabilities restrict
local access and are revoked on configuration changes. Only this local capability,
never the upstream URL, crosses the engine control socket. The decoder additionally
restricts protocols and audio formats. Web requests never proxy a live audio stream.

Stations using relay need the updated managed Liquidsoap template rendered through
the existing station runtime workflow and their playout process restarted once at
upgrade time. The automation worker must run the updated code. **No rendering into
installed runtime directories, service restart, deployment, or production migration
was performed as part of this development work.** Older engines show an actionable
pending/error observation while their existing automation continues. Subsequent
relay enable/disable/URL changes apply through the station socket without restarting
station output. Worker or engine restarts cause configuration reconciliation.

### Playback, fallback and status

Liquidsoap owns decoding, playback, source selection, mixing, reconnects, and the
existing station output. Relay replaces the Auto bus. DJ decks, microphone and carts
retain their existing priority, gains, and recording lifecycle. Off-air relay audio
is consumed so returning from live control does not replay buffered speech.

Local scheduled/default programming stays prepared and pauses while relay is fully
audible. Schedule changes refresh standby selections, and explicit fallback schedule
changes do not fade a healthy relay. Standby audio receives no fabricated START or
play history. Timed events wait during relay playback and expire under existing
windows; already queued/playing timed events hold off recovery until finished.

Connection attempts use a five-second retry delay and ten-second network timeout.
Loss of available relay audio immediately exposes the prepared local source;
continuous upstream silence is detected after three seconds. Recovery requires ten
seconds of continuous usable audio and uses a one-second handover. This delay does
not delay fallback. If neither local programming nor relay is usable, Freo retains
its existing final safety tone. Keep playable scheduled/default programming configured
for meaningful fallback; relay does not create replacement content.

Station settings and the existing live UI show enabled, connection/readiness, current
source, pending configuration, last failure/reconnect and observation freshness.
Unknown/stale status never claims a healthy connection. Artist/title are bounded and
rendered as text. Existing player/public now-playing displays upstream metadata only
while relay is the observed source, with null local track identities and no voting.
Metadata without an artist remains a title; no elaborate parsing or transformation
is introduced. Upstream paths/query strings are absent from status and audit records.

### Validation and deferred work

Validation uses temporary SQLite databases, a new private PostgreSQL cluster, private
Liquidsoap file outputs, local HTTP fixtures, and a disposable Chromium profile.
Detailed final results follow below. Initial fixture/validation issues were corrected;
network/browser/engine checks required approved execution outside the socket sandbox.

Deferred: upstream username/password authentication, redirect/playlist/HLS inputs,
metadata transformation, downstream distribution, CDN functionality, relay networks,
geographic routing, and additional transcoding infrastructure. Direct MP3, AAC, Ogg,
FLAC and WAV inputs use the installed Liquidsoap decoder; MP3/ICY is exercised by the
real-engine integration tests.

All work is confined to `/opt/freo-v1` on `develop/v1` and temporary test artifacts.
Pre-existing Phase 5/6 changes and `V1_AUDIT.md` are preserved. `/opt/freo` production
application, databases, services, `main`, production tags and releases were untouched.
No deployment or merge was performed.

Final validation results (focused suites overlap; these are not a full-repository
pass claim):

| Check | Result |
| --- | --- |
| Relay permissions, URL/network policy, status freshness, safe metadata, event expiry, worker reconciliation/lifecycle and SQLite migration | 26 passed |
| Relay + existing automation, listener requests and public API | 111 passed |
| Relay + programming refresh, live assist, player, recording manager and timed events | 94 passed |
| Relay + station settings | 42 passed |
| Earlier station settings/web compatibility check | 27 passed |
| Final relay/timed-event follow-up | 34 passed |
| Loopback transport guard, DNS pinning, original Host preservation, redirect/playlist rejection and Chromium settings workflow | 4 passed |
| Final mobile layout placement and escaped metadata browser check | 1 passed |
| Disposable PostgreSQL full migration chain, Phase 6 data preservation, downgrade/re-upgrade and concurrent edits | 3 passed |
| Real relay disconnect/stall recovery, standby schedule change, DJ return, existing schedule transitions and booth/cart regression | 15 passed |
| Final shared-clock WebRTC mic/cart/recording compatibility and relay disconnect/stall checks | 3 passed |
| Liquidsoap render/type check, Python/JavaScript syntax and patch whitespace | Passed |

The optional microphone engine check exposed incompatible forced input clocks. The
relay now joins the existing mixer clock, and the real microphone/recording test and
both relay failure scenarios passed after that correction. Tests also caught an
invalid-port validation edge case and asynchronous frame-boundary assertions; these
were corrected before the final runs. PostgreSQL retained the existing migration
extension deprecation warnings. No known failed check remains in the focused suites.
Test artifacts are under `/tmp/freo-phase7-*`; the private PostgreSQL cluster was
stopped after testing. HTTP transport and browser fixtures never used production
upstreams, and Liquidsoap tests wrote private audio files instead of Icecast mounts.

## Phase 8 — Voice Tracking and AI Station Imaging

### What changed

The station navigation and media library now open Voice Tracking / Station Audio.
DJs with an explicit station grant can record in the browser or upload a short voice
track, preview/retake it, save it, and place their own accepted audio into specifically
granted playlists. Existing scheduling determines when those playlists air. Playlist
placement uses revisions; replacing a take preserves the old track until the new take
has completed ingest. DJs cannot edit general schedules, other users' tracks, playlist
leaders, provider credentials, or administration. Administrator operations retain the
existing role boundaries. DJ account reassignment clears production grants through the
assignment foreign key, requiring an administrator to grant them again.

Recorded/uploaded voice tracks are limited to five minutes. Browser WebM/Opus, Ogg,
MP4/AAC and normal supported source formats are decoded by bounded FFmpeg operations;
recordings without container duration are measured through a bounded decode. Microphone
capture requires HTTPS or localhost; upload remains available without microphone support.

Create Station Audio supports station IDs, sweepers, liners, show intros/outros, promos,
and generic short imaging. Users may enter a spoken script or request an editable draft
from the station's configured Claude, OpenAI/ChatGPT API, or Grok API provider. Users
review the script before requesting ElevenLabs audio; script generation never schedules
or generates speech autonomously.

ElevenLabs integration includes searchable account voices, voice/model selection,
authenticated voice previews, stability/similarity/style/speed controls where supported,
prompt-only Voice Design previews, and administrator saving of designed voices to the
shared account. Music generation uses force_instrumental with a 3–60-second duration.
Sound effects support a prompt and 0.5–30-second duration. Optional capabilities depend
on API-key permissions and account access; connection testing does not claim that every
paid capability is available. There are no cloning or reference-audio endpoints.

The simple mix contains a voice plus an optional bed and effect, with levels, start
offsets, and fades. Defaults are voice 0 dB, bed -18 dB, effect -12 dB, one-second fades
on bed/effect, and zero start offsets. Output is a peak-limited 44.1 kHz, 192 kbps MP3.
Finished AI imaging is limited to 60 seconds; requested speech duration is approximate,
and overlong audio is rejected rather than silently truncated. Saving submits the exact
rendered preview to MediaIngestJob, classifies it as STATION before enabling it, and
waits for normal analysis. Analysis failures leave a disabled normal catalog track for
administrator recovery. Playlists, leaders, scheduling and automation all consume the
normal Track identity. No AI playback path or separate playable library was added.

### Migration and configuration

Migration `f806a1b2c3d4` follows Phase 7 `f706a1b2c3d4`. It adds provider_credentials,
station_production, production_grants, production_drafts and production_attempts.
Existing stations and DJs have AI/production permissions disabled by default. Existing
media and Phase 5–7 configuration are retained. New STATION labels are voice_track,
show_intro and show_outro; existing track editing recognizes them.

Provider keys are shared installation accounts, configured only by an installation
administrator at `/admin/providers`. Station administrators choose the script provider,
default ElevenLabs voice/model, station enablement, and per-DJ grants. Each script
provider needs a model ID available to that API account. No provider/model is silently
substituted. Configure separate provider API credentials; consumer app subscriptions
are not used by this integration.

`FREO_PROVIDER_ENCRYPTION_KEY` is a Fernet key in protected bootstrap configuration,
separate from Flask's SECRET_KEY. Generate it once with cryptography's
`Fernet.generate_key()`, and back it up separately from the database. Missing or invalid
encryption configuration disables credential use without disabling radio operation.
The browser accepts a newly entered key but never receives any stored key. Provider
records contain encrypted values only; generation records, status responses and logs
exclude secrets. To rotate the bootstrap key, remove all saved provider keys, replace
the bootstrap encryption key while the production worker is stopped, restart the
application/worker, and re-enter the provider keys. Do not discard the old encryption
key while any encrypted credential still depends on it. API-key replacement/removal
increments a credential revision so queued work cannot silently switch accounts.

An optional `freo-production.service` template is included. It runs as freo-ingest,
separately from ingest, automation and playback, with a single-worker lock, CPU/memory
limits, and write access only to upload storage. The checked-in template uses the normal
installed `/opt/freo` layout, like existing unit templates; it has NOT been installed,
started, or pointed at this V1 checkout. On a future authorized installation, apply the
migration, prepare storage, install the unit and start it alongside existing ingest.
The worker is also needed for recorded/uploaded voice-track conversion when no provider
key is configured. Provider API calls are never needed for manual recording.

The default private staging directory is `/var/lib/freo/uploads/production`, overridable
with `FREO_PRODUCTION_ROOT` (include custom paths in systemd ReadWritePaths). Provision it
with owner freo, group freo, mode 2770: the web user freo and freo-ingest's supplementary
freo group both need access. The shared group is necessary for web previews of worker
outputs. Generated/uploaded files use 0640 and opaque filenames. Do not expose this
directory through Nginx. Existing `/var/lib/freo/uploads` and media storage permissions
continue to govern ordinary ingest. No new Python dependency is required.

### Failure handling, records and recovery

Each paid action is explicit. Draft commands are idempotent, only one operation runs
per draft, and provider requests have time/size bounds. Errors report invalid keys,
quota/rate limits, restricted capabilities, missing models/voices or invalid settings
without forwarding provider response bodies. Paid requests are not automatically
retried after timeouts or worker interruption; check provider usage before explicitly
retrying. Failed regeneration retains the last successful audio and preview. Permission
and credential revision checks run before and after generation, and permissions are
checked again before ingest publication. A revoked user cannot publish playable audio.

Generation history retains station, creator, type, script/prompt, provider, voice/model,
settings, timestamps, status/errors, numeric token usage and returned request/billing
identifiers, plus ingest and resulting Track links. Usage is visible to administrators;
monetary prices are not guessed from credits or tokens. Deleting audio retains production
history but removes its playable-media association through normal catalog deletion.

Abandoned drafts expire after seven inactive days. Unreferenced temporary audio is
removed after seven days; active jobs and retained preview components are protected.
Saved assets remain subject to normal Freo media deletion. DJs cannot delete assets
referenced outside their playlist grants, queued/current audio, or assets with stale
playback observations; administrators use the existing media cleanup workflow.

Downgrading removes production configuration/history and encrypted provider records;
normal ingested STATION tracks remain. Save required metadata before downgrading, stop
the production worker first, and clear private draft audio separately if retiring the
feature. The downgrade does not contact providers or delete account voices.

### Validation and limitations

Automated validation mocks all external providers; no paid provider call or live API
key was used. Tests cover encryption/redaction, station/DJ/ownership boundaries,
permissions and credential revocation, connection failures, idempotency, worker recovery,
real FFmpeg conversion/mixing, ordinary ingest/analysis/STATION classification, playlist
placement/replacement/deletion, and duplicate-audio ownership protection. Browser tests
exercise actual MediaRecorder output and the prompt → voice → optional bed/effect →
preview → save flow, including mobile layout. Disposable PostgreSQL tests cover the
complete migration chain, Phase 7 data preservation, downgrade/re-upgrade, concurrent
playlist edits, concurrent submission, and assignment-grant cascade deletion.

Live provider-account capability and sound-quality verification remain operator checks
with the intended accounts. Advanced mixing, voice cloning, direct DJ calendar editing,
autonomous generation, AI DJs, podcast/full music production, and a separate AI media
library remain outside this phase. The shared account's designed voices are saved by
administrators only; external voice deletion remains in ElevenLabs.

All changes are in `/opt/freo-v1` on `develop/v1`; prior uncommitted work was preserved.
Production `/opt/freo`, production databases/services, main, tags, and releases were not
modified. No deployment or merge was performed. Test databases, browsers and media use
private `/tmp/freo-phase8-*` locations. Initial sandbox-only socket/ACL restrictions were
resolved by running the isolated checks with approved host capabilities.

Phase 8 final validation results (focused suites overlap; not a full-repository pass):

| Check | Result |
| --- | --- |
| Production/provider permissions, encryption, generation contracts, recovery, FFmpeg, ingest and placement | 19 passed |
| Production plus playlists, automation, programming refresh, station flags and DJ regression | 85 passed |
| Production plus catalog editor and station flags follow-up | 38 passed |
| Production plus visual schedule and programming harmonization | 49 passed |
| Existing media ingest/storage/ACL regression | 7 passed |
| Disposable PostgreSQL migration chain and concurrent commands | 3 passed |
| Chromium recording and AI assembly flows, including mobile layout | 2 passed |
| Python/JavaScript/shell syntax and patch whitespace | Passed |

Saved production previews resolve the normal catalog file. Catalog deletion blocks all
production previews for that asset and retires retained draft components on cleanup.
Administrators can inspect retained generation history after disabling station AI;
disabling AI still prevents new paid generation. Existing SQLAlchemy fixture and
migration-extension deprecation warnings remain; no provider credentials were used.

## Phase 9 — Platform polish & monetization

### Upgrade and output configuration

Apply Alembic revision `f906a1b2c3d4` after the existing Phase 8 revision. It adds
optional JSON discovery links to tracks/artists, dimension metadata to player
assets, and station-assignment-owned DJ profiles with optional image bytes. It
extends the stream bitrate constraint to 64/96/128/192 kbps and sets the database
and application defaults for **new** stations to **128 kbps**. Existing active and
pending station settings are preserved. This follows the Phase 9 clarification:
192 kbps is an explicit station-administrator choice, not an automatic upgrade.

Select 192 kbps in Station Settings → Stream quality. The existing queued audio
settings workflow renders the Liquidsoap `%mp3(bitrate=__BITRATE__)` output and
applies it with its existing restart/rollback handling. The normal broadcast
encoder supports 192; recording output was already 192 and remains unchanged.
The 64 kbps diagnostic test-stream template remains a diagnostic fixture.
192 kbps uses approximately 86.4 MB per listener-hour before overhead. No runtime
configuration is regenerated and no service is restarted by the schema migration.

Downgrade requires all active **and pending** 192 kbps settings to be cleared or
successfully applied at a lower rate first. The migration refuses downgrade
otherwise. Downgrading discards discovery/profile fields and dimension metadata;
export needed presentation data first. Existing media files are not relocated.
Player JSON configuration is additive and omitted values use compatible defaults.
No new worker or environment variable is required.

### Universal music and permissions

The existing `Track.available_to_all`, artist/album inheritance, and immutable
owner storage paths remain the source of truth. Import review supports individual
and selected/bulk universal-music choices and import-workspace defaults. A shared
song is a single Track/media asset; consumers use it in their own playlists,
categories/rotations, smart playlists, and scheduling. New stations inherit the
same availability. No audio is copied per consuming station. STATION and
COMMERCIALS audio remain station-specific, including when an artist/album is
shared; changing a song to non-music clears direct sharing.

Source metadata, artwork, audio edits, processing, broadcast enablement, sharing,
and deletion must be performed through the owning station. Consuming stations
retain their own playlist, category, tag, feedback, and programming controls.
Existing ADMIN accounts retain their existing station access; this phase does not
introduce a new administrator assignment model. DJs retain their existing closed
endpoint/assignment permissions and cannot edit these presentation settings.
Existing queue-aware unsharing and retained owner-media protections still apply.

### Advertising and asset storage

Station Settings and Player Settings edit the same two optional placements:
Top Banner and Bottom Banner. They have independent enable switches, schedules,
source selections, and desktop/mobile creatives. New image advertisements require
a valid destination URL; label/alt text is optional, with an accessible generic
label when omitted. Links open in a new tab with opener isolation.

Upload JPEG, PNG, or WebP, up to 10 MB; files are decoded and stored as PNG in the
existing `station_player_assets` table. Exact accepted input dimensions are:

| Placement | Desktop | Mobile |
| --- | --- | --- |
| Top | 728 × 90, 970 × 90 | 320 × 50 |
| Bottom | 728 × 90, 970 × 90, 300 × 250 | 320 × 50, 300 × 250 |

Settings display recommended and accepted dimensions beside each upload. Incorrect
sizes return the actual dimensions and accepted choices. Existing PNG creatives
without dimension metadata remain readable at their natural aspect ratio; new
uploads must meet the standard sizes. Desktop/mobile selection uses the existing
650 px breakpoint. Images may shrink proportionally, never stretch or upscale.
If a device-specific image is absent, the other may appear only if its natural
width fits. Otherwise the placement collapses. Network creatives are shown only
at configured sizes that fit the available width.

Disabled or incomplete placements emit no placement markup. Valid image placements
remain hidden until decoding succeeds; failures remove their visible contents.
Network placements remain collapsed until a fill is confirmed. Missing, blocked,
unfilled, timed-out, or invalid ads reserve no space. Top and bottom are independent.
There are no placeholders, default ads, sales processing, or ad-server components.

Google integration uses **Google Ad Manager**, configured with an ad-unit path
such as `/1234567/station/top` and accepted desktop/mobile sizes. It uses Google
Publisher Tag's `collapseDiv: BEFORE_FETCH` behavior and verifies the returned
creative dimensions. See Google's [empty-slot documentation](https://developers.google.com/publisher-tag/samples/collapse-empty-ad-slots).
This is not an AdSense account integration. Publisher account approval, inventory,
consent configuration and any required ads.txt hosting remain operator setup;
Freo does not create accounts or contact paid advertising APIs during validation.

Other networks can provide an HTTPS iframe adapter. Arbitrary pasted HTML/scripts
are not accepted. The frame has an opaque sandbox origin, no parent DOM access,
no top-navigation permission, and no referrer. The browser's `credentialless`
attribute is requested where supported; adapters must work without relying on
third-party cookies. The sandbox allows scripts and user-opened destinations.
The iframe receives these URL query parameters:

- `freo_placement`: `ad_top` or `ad_bottom`
- `freo_nonce`: unique per iframe load
- `freo_width`, `freo_height`: the selected creative dimensions

After it has valid creative content, the adapter calls:

```javascript
parent.postMessage({
  type: 'freo-ad-status', placement: params.get('freo_placement'),
  nonce: params.get('freo_nonce'), status: 'filled',
  width: Number(params.get('freo_width')), height: Number(params.get('freo_height'))
}, '*');
```

Here `params` is `new URLSearchParams(location.search)`. Send the same identity with
`status: 'empty'` to collapse. Freo checks the exact sending WindowProxy, opaque
`null` origin, nonce, placement, and configured dimensions. Iframe load alone is
not a fill signal. No response within ten seconds collapses/removes the frame;
late responses cannot restore it. Networks without this contract need an adapter.

Third-party code loads only on the public player. Admin settings and draft
previews never request network ads. Public-player CSP permits the fixed Google
script hosts and HTTPS ad frames/connections; authenticated administration keeps
its original policy. Entering/leaving public player documents uses full navigation
so third-party scripts and the public CSP do not persist into administration.

### Discovery, DJs, merchandise, and visuals

Track and artist detail pages support optional Spotify, Apple Music, purchase,
website, album/music, social-profile, and merchandise links. Labels are bounded
plain text; URLs require HTTP(S) without credentials. Track and artist links are
combined and deduplicated in public current/recent music. No discovery scraping
or relay-artist account guessing occurs. The existing player JSON API adds
`discovery_links` arrays without changing existing fields.

Station Settings → Public DJ profiles edits an assigned DJ's short bio, image,
and optional links for that station only. Images use the existing decoder and
are saved at up to 512 px without cropping. Profiles are stored in
`dj_station_profiles`, with a composite foreign key to the DJ/station assignment.
Unchanged assignments preserve profiles; revoked assignments cascade-delete them.
Inactive or unassigned DJs are omitted from public data and image delivery.
Live profiles require a fresh, confirmed DJ/MIC observation and live-session
ownership. Custom public schedule listings can select an assigned DJ; public
responses resolve current profile eligibility instead of publishing private
account data. The APIs add optional `dj_profile` objects; email and internal
account IDs are not included in those objects.

The optional station merchandise URL appears on the player and public station
card. Freo links to the store; it does not handle checkout.

Five Canvas 2D visuals are available: fractal, spectrum, waveform, particles, and
ambient/geometric. Ambient is the default. Station settings choose the initial
mode; a listener choice is stored per station in localStorage. Rendering caps
pixel density at 2 and animation at approximately 30 fps, pauses with playback
or hidden pages, and uses static frames for reduced-motion preferences. Where
supported, audio analysis reads `captureStream()` into an analyzer without
connecting it to the audio destination. Other browsers retain native audio and
use ambient/state-driven modes; spectrum and waveform remain neutral with an
accessible unavailable-analysis message. Canvas or analysis failure never replaces
or reroutes the existing audio element. Reconnects reattach observation to the
replacement element.

### Validation

Phase 9 tests use disposable SQLite/PostgreSQL databases, temporary media and
headless browsers. The PostgreSQL harness is `bash scripts/test-polish-postgres.sh`;
it creates a private `/tmp` cluster with no TCP listener or installation credentials.
No deployment, merge, production database migration, production service restart,
tag, or release operation is part of this phase. Production `/opt/freo` is untouched.

Phase 9 final validation results (focused suites overlap; not a full-repository run):

| Check | Result |
| --- | --- |
| Import sessions plus Phase 9 configuration, discovery, DJ and ownership boundaries | 39 passed |
| Phase 9, catalog editor, station settings, scheduling and station regressions | 83 passed |
| Final catalog, shared availability, homepage, Phase 9 and playlist regression | 61 passed |
| Stream settings/Liquidsoap plus station/custom-domain boundaries | 51 passed |
| Public player/browser checks, including image resizing, reduced motion, Canvas failure, iframe timeout, mocked Google fill/no-fill and admin navigation | 7 distinct checks passed across focused runs |
| Existing browser import, artwork, audition and catalog-edit workflow | 1 passed |
| Disposable PostgreSQL full migration chain, active-bitrate preservation, profile cascade and downgrade/re-upgrade | 1 passed |
| Changed Python/JavaScript syntax, shell syntax and patch whitespace | Passed |

Real Liquidsoap output was inspected with FFprobe at 64, 96, 128 and 192 kbps.
No external ad account or paid provider call was used; the Google browser contract
was mocked and network requests were blocked. Live publisher-account acceptance,
consent/account configuration, and each third-party adapter's actual creative fill
remain operator verification. Arbitrary ad scripts, automatic artist discovery,
merchandise checkout, an ad server, and a graphics engine remain out of scope.

Initial sandbox-only browser socket and media ownership/ACL restrictions were
resolved by running the isolated checks with approved host capabilities. Existing
migration-extension and SQLAlchemy warnings remain. Test corrections included new
standard-size creatives, explicit legacy 64 kbps fixtures, and waiting atomically
for replaced responsive images. A mobile screenshot is retained at
`/tmp/freo-phase9-player-mobile.png` for local review.

All work remained in `/opt/freo-v1` on `develop/v1`, preserving prior uncommitted
work. `/opt/freo` production files, databases, and services were not modified.
Main, production tags and releases were untouched. No deployment or merge occurred.

## Phase 10 — Broadcast Tools and Freo Studio

Developed from `33671a4ffbd3be46ea34c9c2f39d30a3c3220b51` on `develop/v1`.
This is still an unpublished V1 development build. No production deployment,
`main` merge, tag, or release is part of this phase.

### Processor and streaming

Station Settings now offers **Off, Light, Standard, Punchy**, plus Custom controls
under Advanced. Liquidsoap 2.2.4 supplies LUFS-based `normalize`, three-band
`compress.multiband`, and `filter.iir.eq.peak`; Freo implements no DSP algorithms.
Preset AGC targets are −18/−16/−14 LUFS, compression ratios 1.3/1.8/2.5, and AGC
excursion is bounded to ±6 dB. EQ is neutral in presets; Custom exposes only
AGC target, compression strength, and bass/mid/treble. Existing custom settings
are retained. Source loudness normalization and per-track gain remain independent.

Processing follows the combined program sources. The pre-existing −1.5 dB
final limiter remains active, including with Off. Off is verified against the
baseline PCM path. Constructor failure and source unavailability have an
unprocessed program fallback; invalid settings retain the prior configuration.
This protects processor failures, not a host, encoder, or whole-engine outage.

MP3 (LAME) and AAC-LC (Liquidsoap's FFmpeg encoder, ADTS) are available at
64/96/128/192 kbps. AAC-LC and MP3 were received and decoded from an isolated
Icecast instance. AAC+/HE-AAC is **not** offered: no suitable encoder was confirmed.
New stations default to MP3/192; existing formats and bitrates remain unchanged.
Stream URLs remain stable. Codec/bitrate changes use the existing validated
station-only restart and rollback and may reconnect listeners. Once the Phase 10
engine configuration is installed, preset-only changes apply through its socket
without restarting the station.

No codec package was added. Platform/player support for an AAC ADTS radio stream
can differ, so MP3 remains the compatibility default. Codec availability does
not establish patent or redistribution rights: FFmpeg's license depends on its
build configuration, and MPEG-related patent considerations depend on jurisdiction.
See [FFmpeg's official licensing notes](https://ffmpeg.org/legal.html).

### Broadcast Reports and External Bulletin

**Broadcast Reports** uses confirmed playback decisions, frozen metadata for new
performances, and existing audience/session observations. It includes performance
history, track summaries, nearby audience samples (within 45 seconds), ISRC,
source duration, observed session totals, peak audience, completed-session average
duration, listener-hours, coverage, and CSV exports. Date boundaries use station
timezone; session summaries retain their existing hourly resolution. Historical
metadata without a snapshot comes from the current library. New snapshots survive
master-library deletion; older history already deleted cannot be reconstructed.
Source duration is not verified airtime. Unique people cannot be derived from
existing connection rollups and are shown as unavailable. No ASCAP/BMI/SESAC/
SoundExchange or other licensing-compliance certification is claimed.

**External Bulletin** creates an ordinary timed event with private source settings.
Configure a direct HTTP(S) file or continuous stream, optional available STATION
intro/outro (up to 60 seconds each), and hourly/daily/weekly/one-time timing in the station timezone.
The default waits for the next track boundary, up to five minutes; Hard timing
may interrupt automation music. DJ control and live microphones stay protected.
Files are prefetched 60 seconds ahead with a 20-second download budget, 100 MB
limit, bounded local decoding, and ten-minute audio limit. Live sources require
readiness within ten seconds and a 5–600 second segment duration (default 180).
Live playback consumes the current feed, not an earlier captured recording.

An unavailable source skips the whole sequence. A live disconnect, depleted
buffer, or three seconds of silence releases the event bus and skips the outro.
Normal completion plays the outro and resumes automation. Engine leases recover
worker loss; occurrence identities prevent replaying a completed/failed sequence.
Private files are removed after playback; abandoned staging is reaped after a day.
Remote transport reuses the relay's URL, DNS, TLS, and private-network policy;
redirects, playlists, and embedded login credentials remain unsupported.
No new content provider, scheduler, worker service, or analytics collector was added.

### Freo Studio installation and offline behavior

The existing management UI has a manifest, standalone display, 192/512 maskable
icons, an Apple touch icon, and an `/admin/` service worker. Only icons and a
public offline shell are cached. Management navigation is network-only;
authenticated pages, API responses, streams, and control mutations are never
stored in the service-worker cache or replayed later. Offline/error navigation
shows a reconnect screen with no station controls.

Use HTTPS (or localhost for development). Android/desktop browsers expose their
Install/Add to Home Screen action; on iOS Safari, use Share → Add to Home Screen.
The IP-only HTTP test install remains usable in a browser but does not provide
the secure-context PWA experience. No native applications or UI redesign.

### Migration and installation impact

Migration `fa06a1b2c3d4` follows `f906a1b2c3d4`: it adds confirmed-performance JSON
snapshots and bulletin JSON on existing timed events, expands codec constraints,
and changes only the default bitrate for newly created streams. Existing station
values are preserved. Downgrade refuses configured bulletins, non-MP3 streams,
or pending audio changes.

The fresh V1 source-install command documented above is unchanged. Its normal
migration step applies the new head. Provisioning additionally creates
`/var/lib/freo/bulletins` as `freo-automation:freo-playout`, mode 2750, and the existing
automation unit receives write access only to this private directory. No new
Python/system dependency, environment secret, port, or service is required;
bulletin live transport shares the existing loopback relay listener.

For an **existing disposable V1 installation**, migrate the database, create that
private directory with the ownership/mode above, install the updated automation
unit and reload systemd, then restart the V1 application/automation services.
Regenerate station Liquidsoap configurations from this checkout and restart those
V1 playout instances once before using bulletins or live preset changes. The first
audio apply against an older engine also performs the existing station restart.
Do not rerun the fresh installer over existing state. These instructions apply
only to the disposable V1 installation, never the frozen production host.

Native iOS/Android apps, CarPlay/Android Auto, branded listener apps, podcast
publishing/editing, and push notifications remain deferred. Licensing-specific
report exports and AAC+/HE-AAC are not included.

### Phase 10 validation

- Existing audio, event/block completion, station, statistics/session, and deletion
  regression selection: **132 passed**, one opt-in test skipped.
- Focused reporting, validation, DST, CSV, pending-config failure, live processor
  apply/rollback, bulletin revision/idempotency/restart, and file-decoding checks
  passed. Real audio proved all four presets, AAC-LC decoding, exact Off PCM
  equivalence, and constructor-failure bypass equivalence.
- Private Icecast: both MP3 and AAC-LC streamed and decoded successfully. Private
  Liquidsoap: intro/body/outro confirmation and automation recovery passed for
  both disconnected and stalled live feeds. File ownership was tested using the
  actual automation/playout accounts against temporary storage only.
- Chromium at desktop and 390-pixel mobile widths: reports, bulletin editor,
  audio settings, service-worker installation, offline shell, reconnection,
  and the existing audio-settings save/status flow passed. The offline test
  disables both the page and service-worker network targets. Physical iOS/Android
  installation has not been exercised on this host.
- Isolated PostgreSQL: the complete fresh migration chain, baseline→Phase 10
  upgrade, guarded round-trip, and PostgreSQL report aggregation passed. The
  existing source-installer tests also passed with host commands stubbed in `/tmp`.
- All new runtime templates, icons, JavaScript and migrations are included by the
  existing installer inventory. No production services or installation paths were
  changed during testing.

### Final integration corrections

The disposable-VM integration pass reproduced missing/stale Now Playing during
an external bulletin. The engine now distinguishes bulletin intro/outro audio
from waiting automation, and the worker projects the confirmed bulletin body
into the existing playback snapshot. Public/player, booth and management history
use the bulletin's captured name; no source URL is exposed.

A stalled live bulletin and relay each reproduced an approximately eight-second
program clock delay. Their HTTP decoders now use dedicated Liquidsoap clocks and bounded
native buffer (0.5-second prebuffer, two-second maximum) before joining the program
clock. Tests monitor output-file growth throughout upstream failure and recovery,
in addition to checking eventual source state. This uses Liquidsoap's existing
[clock/buffer facilities](https://www.liquidsoap.info/doc-2.2.5/clocks.html).

Repeated real-engine tests also reproduced a bulletin EOF race: the background
readiness poll could clear the event reservation while the body completion
callback entered OUTRO, omitting the outro and leaving completion state stale.
Bulletin readiness/deadline checks now run on the program clock alongside the
end callbacks. The regression exercises three consecutive intro/body/outro
sequences after each disconnected or stalled live feed and confirms both station
audio performances in every sequence.

Consecutive installed recordings exposed a second clock race: explicit file
output start/stop calls from the observer thread could mark a valid recording
partial or leave the next short recording empty. An isolated consecutive-show
test reproduced the empty file. The recorder now gates its existing program
source and lets Liquidsoap's native fallible output open/close on its own clock;
the worker protocol, private storage and error isolation are unchanged. Tests
also verify that later shows do not change an already completed recording.

Repeated boundary tests reproduced the previously intermittent 0.4-second
calendar gap. Automatic programming refresh now resolves a successor through the
existing selector/queue before removing obsolete lookahead, so decoding and
subsequent event bookkeeping do not leave an empty queue at the current song's
end. Refresh recovery recognizes an already accepted successor after worker
interruption and retains confirmed playback history. A real-audio regression
delays event bookkeeping after a boundary refresh; the original path produced a
2.25-second gap under that delay, while the corrected path produced none.

The first soak attempt exposed a request starvation case and was stopped after
51 minutes 57 seconds, without an audio interruption. A later automatic repeat
in the queue could invalidate an earlier queued listener request, causing the
request to wait again while its song aired without the request binding. Queued
request revalidation now uses the engine's actual queue order. Audio behind the
request does not count as an earlier reservation; confirmed starts, earlier
queue entries and other live/deck sources still enforce separation. Focused and
real-engine tests cover that ordering and confirmed request completion. This
interrupted interval is excluded from the final six-hour acceptance run.

A follow-up multi-request cancellation regression also reproduced a worker
exception: retiring a rejected request's tail overwrote the queue-order list
before the next request was checked. The queue order now retains its own name
throughout reconciliation. The test covers both an ordinary successor and a
second listener request, including retirement of both while retaining current
audio. The intermediate soak was archived and the acceptance interval restarted
after this correction.

Disabling test events during cleanup exposed a PostgreSQL deadlock between an
event edit and the worker's scan of future occurrences. The worker now takes the
existing station lock before occurrence locks, matching the editor and selector,
and reloads each locked occurrence so a concurrent cancellation cannot be prepared
from a stale snapshot. Isolated PostgreSQL regressions reproduce both the lock
cycle and cancellation race and verify safe completion on the corrected path.

A later confirmed-history audit found an unrelaxed artist repeat after 90 seconds
despite a 120-second window. The first song had waited almost four minutes in
lookahead; its separation reservation had incorrectly aged from selection time
before it aired. Unheard selected/submitting/queued music now remains reserved
until it starts or is retired, including waits beyond the recent-history horizon.
Confirmed music still ages from its actual start, and the existing explicit
exhaustion relaxation remains available to avoid empty programming. Regressions
cover playlist, visual-schedule and category selection plus released reservations.

Regression expectations were updated for the intentional 192 kbps new-station
default and the three public PWA installation assets. The trimmed-duration
calendar test's fake events now include their actual playlist/track content types.
The domain browser case waits for workspace navigation to finish before its next
submission, matching the existing workspace tests; all routing/URL assertions remain.
The access matrix still
checks protected routes and verifies those public assets are identical for an
anonymous visitor and a DJ. No additional migration or dependency is required;
existing V1 installations need refreshed station engine configurations for the
runtime corrections. Full regression and endurance results follow after testing.

## Public-player record restoration and optional visualizer — 7 October 2026

The Phase 9 `.visual-deck` rules hid the original Freo record behind an always-on
canvas. The record markup and complete CSS were located at frozen production
commit `83200e6508654bea13f404e9d5699a8ad3eae19d`. That CSS remains an exact prefix
of the V1 stylesheet: spinning grooves/highlights, inner circular window, outer
color ring and glow are reused, not reconstructed. The reference used a lava
center and separate artwork; the restored player places current album artwork
in the rotating center, retaining lava when artwork is missing or fails to load.
Reduced motion and hidden-tab behavior remain respected.

VISUALIZER now opens a dedicated full-window dialog, with optional browser
fullscreen and a compact bottom-right artwork/song/station overlay. Metadata
comes from the existing player refresh. Closing or changing visualization never
replaces, reloads, pauses or routes the native stream. The existing captureStream
and read-only Web Audio analyser architecture is retained; there is no destination
connection or second playback path. Canvas/capture/analyser failures are contained,
and closing/navigation releases only the visualization resources.

All five existing mode IDs and station defaults remain compatible. Canvas 2D now
provides multicolor radial fractals, logarithmic spectrum bars with peak decay,
layered waveform ribbons, particle trails, and layered rotating geometry. Three
local palette presets (Aurora, Sunset, Electric) complement smoothed bass/mid/
treble response. Pixel count, particle count and recursion are bounded. Analysis
unavailability is displayed as a resting visual, rather than fabricated activity.

Only player presentation and shared artwork rendering changed. V1 reconnects,
stream settings, requests, discovery/commerce, DJ profiles, feedback, advertising,
analytics, PWA and public APIs are retained. Disabled ads still create no container.
No migration, runtime engine refresh, new dependency or station restart is needed.

Validation on isolated fixtures and native Chromium 153:

| Checks | Result |
|---|---|
| Player settings/API, ads, discovery, commerce and 192 kbps settings | 35 passed |
| Requests, audience sessions, public API, PWA metadata and broadcast tools/isolated audio engine | 138 passed |
| Existing desktop/mobile player, requests, PWA offline and workspace lifecycle browser regressions | 16 passed, 1 opt-in navigation-retention diagnostic skipped |
| Advertising adapters, all visualization modes and reduced-motion/audio isolation | 3 passed |
| Record/artwork rotation and changes; five distinct live-audio modes; palettes; fullscreen; mobile; metadata; repeated open/close; native-element continuity; capture/analyser/canvas failure isolation | 5 passed |

Total: **197 passed, 1 optional diagnostic skipped**. The migration tests emit 20
existing Flask-SQLAlchemy `get_engine` deprecation warnings. Initial screenshot
runs exhausted the shared two-minute audio sample; the long visual checks now use
a ten-minute deterministic fixture. The mobile launch target has scroll spacing,
and its browser check scrolls clear of the existing sticky transport. All final
runs above passed. JavaScript syntax and `git diff --check` also passed.

Deployment is limited to the V1 staging VM `209.38.64.12`: update its source
checkout and the four player presentation files plus these notes, preserve a
backup, update its installed commit marker, and restart only `freo.service`.
The station playout PID must remain unchanged. Verify public HTTPS assets against
the commit and exercise the real `v1-test-1` player, including natural metadata
transitions, live audio analysis and injected renderer failure. Production source,
database/services, `main`, production tags/releases and the 0.3.2 installation
remain frozen.

## Public player acceptance corrections — 7 October 2026

The Phase 5 request page/API existed but the public player omitted its entry
point. `REQUEST A SONG` now appears only when the station's existing request
settings enable it. Its dialog embeds the existing request page, keeping playback
alive and preserving the original search, submission, moderation, rate limits,
programming restrictions, separation, recovery and confirmed-start rules. The
public CSP permits this same-origin frame on HTTP installations as well as HTTPS.
Disabled requests and disabled advertising render no reserved controls/containers.

Phase 10's install manifest and service worker covered `/admin/` only. Public
players now advertise a station-specific manifest at
`/player/<slug>/manifest.webmanifest`, with a stable station identity, the station
player as start URL, existing validated Freo icons, and `/player/` scope. The
separate public worker `/player/sw.js` caches only an explicit offline message and
icons; audio, request submissions, metadata, APIs and authenticated content remain
network-only. Offline mode displays no simulated station controls. `INSTALL FREO`
appears only when the browser supplies its native install opportunity, and is
hidden in installed/unsupported contexts. iPhone installation uses Safari's native
Share → Add to Home Screen flow; Safari does not provide `beforeinstallprompt`.
Freo Studio remains a separate installation. Manifests preserve custom-domain
station boundaries.

The reported Safari/iPhone visualizer failure was reproduced on the real HTTPS
staging player: `HTMLMediaElement.captureStream` is unavailable in WebKit, while
Chromium captured real nonzero station samples successfully. The listener URL
redirects to a stream on the same HTTPS origin, so missing cross-origin permission
was not the cause and no Icecast/Nginx CORS relaxation is needed.

Chromium keeps its capture-only analysis path. Browsers without capture use one
playback-owned media-element source and output gain, unlocked in the Play gesture.
The analyser is a separate branch; visualizer close/fullscreen/render failures
never own or disconnect the audible output. Capture failures stop automatic
reattachment loops. The fallback uses the existing stream and handles replacement
media elements; no extra visualization stream is opened. Music audio-session
behavior is declared where the browser supports it.

The iPhone volume slider previously assigned `HTMLMediaElement.volume`, which
Safari on iOS does not apply. The fallback output gain now implements volume and
mute with short ramps, independently of whether the visualizer is open. Native
volume remains in use on browsers that support it, with volume/mute intent
preserved across pause/resume and reconnects. Physical device/system volume remains
under the listener's control.

The restored 0.3.2 record remains the default visual; the five-mode visualizer,
artwork/title/station overlay, fullscreen, advertising, discovery and V1 public
APIs are retained. No database migration or dependency change is required.

Deploy all changed application files and the three new player JavaScript assets
from one exact `develop/v1` commit. On the disposable staging VM, back up the
installed files and commit marker, restart only `freo.service`, and verify that the
station playout PID and 192 kbps stream remain unchanged. Temporarily enable
requests for the public submission acceptance check, then restore the original
settings. Never apply this staging procedure to production or the frozen 0.3.2
installation.

Validation: 246 tests passed across focused acceptance and relevant regression
suites; one optional retained-resource diagnostic was skipped. This includes
request submission and disabled-state rendering, public/Studio PWA boundaries,
actual Chromium installation and standalone launch, offline recovery, all five
visual modes, fullscreen, metadata, MP3/AAC-LC analysis, failure isolation, and
measured software volume/mute output. Chromium's native volume/mute preservation
was also checked after pause/resume. The restored record CSS still matches the
frozen 0.3.2 implementation. Candidate scripts were exercised against the real
HTTPS staging stream in desktop WebKit and iPhone emulation, with nonzero audio
samples and no additional stream loads when opening/closing the visualizer.
Physical iPhone hardware was unavailable; emulation is not a device certification.

Public-player controls now use two explicit rows: REQUESTS / VISUALIZER / INSTALL,
then SHARE / URL. Requests still require station enablement, and Install still
requires a native browser installation opportunity. Removed the Reduce motion
button and its event handler; OS/station reduced-motion preferences remain in
effect. Updated asset versions prevent stale player JavaScript after rollout.

## Advertising manager — 7 October 2026

Migration `fb06a1b2c3d4` adds display policy to existing Campaign records and a
campaign image table. Advertising now has its own station navigation entry;
Station Settings links to it and retains merchandise and visual defaults.
Configured legacy Top/Bottom slots become separate campaigns, including disabled
slots with saved creatives or network configuration. Their existing Public Player
exposure is preserved; Homepage and Visualizer are opt-in. Original player JSON
and images remain for recovery and unrelated settings saves preserve them.

Display policy is separate from traffic lifecycle, dates, and priority. Highest
eligible display priority wins; positive weights share selections at that priority.
Start/end inputs use the station timezone, store UTC, and use inclusive starts and
exclusive ends. One placement applies to all enabled surfaces. The shared homepage
uses its featured channel; station-domain homepages use their own station. Existing
exact image sizes, 10 MB limit, Google/adapter fill contract, and hidden-until-filled
behavior remain. 300 × 250 is Bottom only. Long-lived pages revalidate every minute
and when visible again, retaining eligible selections rather than rotating them.
The public, no-store revalidation interface is
`GET /api/stations/<slug>/advertising/<homepage|player|visualizer>/<top|bottom>`.

Linked audio is **convenience only**. Uploads use normal COMMERCIALS ingest and
remain disabled until enabled in the library. Existing station commercials can
be selected, previewed, replaced, or detached. Scheduler/Traffic still owns every
audio schedule. Campaign display edits, disabling, or deletion never change
existing audio schedules, media enablement, finalized traffic, or confirmed-start
history. Deletion archives the display entry; media and historical references are
retained. Existing traffic creatives are offered as the initial audio link.
There is no song-frequency policy or new playback/queue engine.

Deploy only to V1 staging `209.38.64.12`, verifying hostname `Freo-v1-Test-1` and
an exact `develop/v1` commit. Back up its database, installed changed files, and
release marker before applying the migration and restarting V1 Python services.
Liquidsoap configuration and playback services do not need to change. Roll back
with the matching database/files backup: downgrading alone discards new display
configuration and assets, and is not a data-preserving rollback. No production
release, tag, stable update, or 0.3.2 → 1.0 bridge is included.

Validation: 113 advertising/public-site regressions passed; 80 audio/scheduling
regressions passed, including isolated real-Liquidsoap playback and worker
recovery. Four browser checks cover desktop/mobile management, all three display
surfaces, zero-height empty slots, provider fill contracts, and listener playback
isolation. Two disposable-PostgreSQL checks verify migration preservation and
schema consistency. Linked-audio tests cover valid/rejected ingest, preview,
replace/remove, and preservation of existing traffic inventory and schedules.

## V1 player audio and atmospheric visualizers — 2026-10-07

The iPhone/iPad volume slider is now hidden and disabled, with a device-volume
hint. Native volume capability is probed before playback, with an Apple touch
fallback for builds which echo assignments without adjusting output. Desktop
Safari/Chromium and Android retain volume control. Mute intent survives element
replacement and reconnects, including when Web Audio initialization is unavailable.

Analysis is consolidated under the existing playback helper. Capture contexts
are created in the opening/Play gesture rather than waiting for a later track or
animation callback. A Safari graph that exists but initially remains suspended
can finish attachment after a later successful resume. Readiness/state events
notify the renderer. Optional analysers are detached on pause, resource reload,
close, hidden state, and reduced motion; the audible fallback is never owned by
renderer cleanup. Returning from reduced motion reactivates analysis instead of
remaining frozen behind a stale player class. No second audio stream is opened.

The universal desktop failure was not reproduced against the existing V1 live
player; these specific lifecycle defects were diagnosed and covered with
regressions. The actual listener redirect and stream remain on the same HTTPS
origin, and both Chromium and WebKit measured nonzero station samples. No server
CORS relaxation is required. Unknown external resources do not enter the audible
Web Audio fallback; unavailable analysis has a labeled resting scene.

Fractal, Spectrum, Waveform, Particles, and Ambient retain their rendering modes.
Aurora adds layered luminous curtains, Ethereal adds translucent line clouds and
light beams, and Space adds Earth, four stylized planets, and frequency-sensitive
wave fronts with planet illumination. All modes use real frequency/time-domain
samples. The three new modes use the existing selector and station-default
settings, without resetting existing defaults or adding a database migration.

Rendering has a 30 fps ceiling, bounded geometry, DPR up to 1.25, and pixel budgets
of 1,000,000 desktop / 600,000 narrow-screen pixels. The record behind the modal
pauses. No graphics framework is added. Isolated final measurements of the three
new modes recorded median JavaScript draw costs from 1.5 to 18 ms, with p95 at or
below 23 ms. Chromium delivered approximately 10–20 fps on this software test
host; headless WebKit delivered approximately 1–4 fps despite the lower draw
cost. Physical-device smoothness remains unverified.

Validation: 39 player/settings tests and 16 focused Chromium browser cases
passed (55 total). Coverage includes all eight modes, real decoded bass/mid/high
frequencies and silence, MP3/AAC, software mute output, unavailable contexts,
gesture/suspended-context recovery, repeated switching, pause/resume, bounded
reconnects, reduced-motion restoration, and canvas/capture/analyser failure while
audio continues. New station defaults round-trip through existing settings.

Read-only candidate assets were additionally tested against the actual V1 HTTPS
stream in desktop Chromium, mobile Chromium, desktop WebKit, and iPhone WebKit
profiles. Each profile passed all eight modes, nonzero station analysis, repeated
switching with one active context, reduced motion, pause/resume, and forced
renderer failure with continuing playback. An additional Android/Pixel profile
passed while retaining the volume slider. No JavaScript page errors were seen.
The retained `scripts/check-player-visuals.py` reproduces these browser checks
without deployment. Linux WebKit emulation is not actual macOS Safari or physical
iPhone/iPad testing. Browser failure of Safari's playback-owned AudioContext
remains an inherent limitation of the selected non-capture analysis route.

Only `/opt/freo-v1` on `develop/v1` is changed. Production remains frozen; no merge
or deployment was performed.


### 2026-10-07 — Remove public player motion suppression

At the user's request, the player no longer uses browser/OS reduced-motion
preferences, the saved `freo-motion` preference, or the station's old `motion`
setting to disable animation or audio analysis. Removed the station motion
checkbox, the still-scene notice, player CSS overrides, and JavaScript gates.
Shared CSS no longer suppresses animation inside public player pages. Old
station settings are ignored without a database migration. The default
visualizer remains unchanged. Hidden/closed visualizers and paused playback
still stop unnecessary animation and optional analysis.

Regression coverage verifies actual analyser activity and changing Canvas output
for all eight modes with all three retired preferences present, record animation,
settings validation, reconnects, and renderer failure while audio continues.
Public player/shared asset versions were bumped to `v1-audio-visuals-4`.

Validation: 39 player/settings tests passed. Four focused Chromium browser
checks passed, including all eight modes with retired motion settings,
reconnects, playback isolation, mobile advertising, and settings preview. The
older mobile advertising fixture was updated to use current campaign APIs and
the animated record grooves. Physical iPhone/Safari verification remains manual.


### 2026-10-07 — Richer fractal, particle, geometric, Ethereal and Space scenes

Implemented the approved classic-fractal / rich-and-fluid direction within the
existing player. `player_scenes.js` adds Mandelbrot/Julia zoom destinations,
evolving particle and geometric formations, pearl-white cloud depth and beams,
and comets, asteroid fields and UFO passes around Earth. Aurora, Spectrum and
Waveform retain their existing renderers. The selector identifiers, station
visualizer defaults and saved preferences are unchanged.

Scenes borrow real analyser measurements. They create no audio graph, stream
requests or separate animation loops. A single lazy WebGL surface serves classic
fractals; unsupported, failed or slow graphics falls back to bounded Canvas
escape-time fractals without touching stream playback. Object counts, raster
sizes, iterations and per-mode adaptive detail are bounded. Scene time stops
when inactive or silent; reduced-motion suppression stays removed. Asset
versions are `v1-audio-visuals-5`; no dependencies or database migration are added.

Initial validation: 25 settings/default tests and seven focused Chromium browser
checks passed. Extended live-stream video covers fractal transitions, five
particle formations, four geometric families, moving white clouds, and a full
minute of Space events without page errors. The headless software GPU triggered
the slow-render fallback as intended. Final forced-WebGL failure checks and
idle desktop/mobile Chromium/WebKit measurements are recorded separately below.

Final validation: all four forced graphics failures (missing WebGL, shader
compile, GPU draw and context loss) and measured frequency-band forwarding
passed: five browser cases. These checks require an actual software WebGL
context rather than passing through an unavailable-GPU path. The earlier seven
browser cases and 25 settings cases also passed. Syntax and whitespace checks
passed. No dependencies or production files were changed.

Real-station performance checks covered all five scenes in desktop and mobile
Chromium and Linux WebKit profiles, with live FFT peaks and no page errors.
Median scene rendering on Chromium was approximately 0.2–9.1 ms; Linux WebKit
software rendering was substantially slower. A targeted iPhone-sized WebKit
fractal check confirmed sustained slow GPU draws switch to Canvas (35 ms median,
69 ms p95 on this headless host). The fallback trades detail for bounded work;
these software-rendered frame rates do not establish physical-device smoothness.
A normal-speed live-stream video exercised complete formation/event cycles.
Physical Android, macOS Safari, iPhone and iPad checks remain for human testing.


### 2026-10-07 — Musical scene refinement, Kai and Safari recovery

Renamed the displayed Fractal mode to Kai in listener and station-default
selectors, retaining `fractal` storage/API compatibility. Kai now paces each
zoom journey over 32 beats when a stable 60–180 BPM estimate is available.
Positive measured spectral changes drive tempo and geometric pulses; silence,
sustained sound and unreliable beat detection do not fabricate a BPM. Added
Ocean, Amethyst, Rose Gold, Emerald and Solar to the three existing palettes.

Ethereal gains subtle blue/purple accents, stronger music-following strands and
a second ray fan. Geometric gains sweeping movement, beat expansion and color
waves inside shape contours. Aurora gains stars, comets and a lower-third lake:
one reusable sky surface capped at 350,000 pixels, bounded reflection strips
and adaptive detail. Existing mode/default identifiers remain unchanged. No
migration or dependency was introduced. Player asset version is v1-audio-visuals-6.

Spectrum's old logarithmic mapping repeated the lowest FFT bin across several
bars and averaged compressed byte values as linear power. Distinct contiguous
bands and peak float-decibel levels against a fixed −90 to −10 dB scale remove
that duplication without EQ or per-frequency gain changes. Equal-level decoded
80 Hz, 1 kHz and 6 kHz tones passed distinct-band/comparable-height checks;
silence settled the bars.

A pending AudioContext resume could prevent fresh Safari gestures from retrying.
Attempt generations now permit retry and ignore obsolete promise completions.
The non-capture graph gets a gesture-owned silent priming sample and an optional
zero-gain analysis sink separate from audible playback. Page/selector recovery
and an Enable visuals toolbar action handle interruption or missing samples.
Animation follows native media state rather than UI buffering classes. The
reported physical-device freeze was not directly reproduced: WebKit has known
interruption/sample-delivery limitations, and real iPhone/iPad Safari remains
for human verification. No fake activity or extra stream is used.

Validation: 25 settings tests and the corrected tempo unit acceptance passed;
periodic inputs at 90–180 BPM estimate within roughly one BPM and sustained sound
produces no beat. Eight Chromium browser cases passed across the initial and
focused reruns, covering all modes/palettes, reconnect, calibrated spectrum,
pending Safari resume, actual decoded 120 BPM zoom pacing, and canvas/capture/
analyser failure while audio continues. Four live-station desktop/mobile
Chromium/WebKit profiles passed with changed pixels in every mode, actual FFT
samples, repeated switching, bounded contexts, pause/resume and renderer failure.
A separate iPhone-sized WebKit interruption simulation recovered twice with
actual samples, changing pixels and continued playback. Reusable candidate/
deployed verifier scripts retain these checks. Syntax and whitespace checks pass.

Performance corrections remove full-frame geometry clipping and bound sky
resolution/reflection detail. Final headless desktop Chromium median frame
rendering was 9.2 ms Ethereal, 6.9 ms Geometric and 23.75 ms Aurora; iPhone-sized
Linux WebKit was 8 ms, 13 ms and 9.5 ms respectively. Observed frame rates remained
low on this software-rendered host (desktop 5.7–13.8 fps, WebKit 2.2–3.2 fps),
so physical-device smoothness is not established. No page errors occurred.
Production stays frozen; only develop/v1 and the designated V1 test server are
within this release's deployment scope.

### 2026-10-07 — On-device audio report and sample-confirmed retry

The visualizer toolbar now includes **Audio report**, with a copy button and a
selectable-text fallback for iPhone Safari. Use the player URL with
`?audio_debug=1` to collect observations before the first Play gesture. Play the
station, open the visualizer, wait ten seconds, and copy the report. Close the
report, tap **Enable visuals**, wait ten seconds, then copy a second report.
Include whether music was audible and the iOS version from Settings → General →
About. A Mac connection is not required.

The report identifies build `v1-iphone-debug-1` and includes the current audio
element/context/source/analyser identities, source binding, context and media
clock progress, frequency peak, float PCM RMS/peak, graph/read/media errors,
stream URL without query parameters, crossOrigin observed at loadstart, and
recent media/retry/context events. It retains at most 40 sample snapshots and
60 events in page memory. Sampling is opt-in, twice per second while the
visualizer is open, plus event snapshots. No report is uploaded automatically,
no second stream is fetched, and diagnostics never connect, resume, recreate or
stop the playback graph. Closing the report leaves collection enabled for the
next retry; navigation disposes its listeners and timer.

**Enable visuals** previously reset its no-signal timer and hid when a context
and analyser existed, even without usable samples. Once shown during playback,
it now stays visible until a real sample read detects signal. The visualizer's
`data-analysis` is `waiting` for a running analyser without signal and `live`
only after signal detection. A silent station can also produce zero samples;
the report explicitly avoids treating silence as proof of a browser defect.

The physical iPhone stream-to-Web-Audio failure remains unconfirmed. This change
repairs the demonstrated retry UI bug and supplies evidence for the audio-path
fix; it does not alter stream CORS or native audio routing. The existing WebKit
interruption helper now releases its simulated interruption inside the retry
click, avoiding the observed pre-click automatic-recovery race.

Validation: seven focused browser/math cases passed, including both capture and
media-element-source routes, real PCM/FFT signal, injected silence and read
failures, retry visibility, clipboard success/fallback, bounded history, URL
redaction, automatic reconnect and uninterrupted playback. Candidate mobile
Chromium and Linux WebKit checks against the real V1 stream passed with nonzero
samples, mode switching, report copy fallback, zero extra stream requests and
no page errors. Physical iPhone verification remains pending the on-page reports.
