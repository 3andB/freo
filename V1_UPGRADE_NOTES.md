# Freo V1 upgrade notes

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
