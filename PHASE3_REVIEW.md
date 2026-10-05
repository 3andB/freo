# Freo V1 Phase 3 — implementation and review

Work is confined to `/opt/freo-v1`, branch `develop/v1`. No deployment, merge,
production migration, service restart, tag or release was performed. `/opt/freo`
production code, configuration, databases and media were not modified. The existing
Python environment was used read-only with bytecode writes disabled. Test processes,
accounts, databases, browser profiles and audio were isolated under `/tmp`.

## Delivered behavior

- Administrators can create DJ accounts, enable/disable them, explicitly convert
  eligible existing accounts and assign stations at **DJ accounts and access**.
  Existing accounts migrate to ADMIN, preserving access. Installation administrators
  and the acting administrator cannot be converted through this page.
- A DJ sees assigned booths and their own recordings on those stations. Requests
  to other administration features or unassigned station controls are denied on
  the server, including direct URLs and POSTs. Assignment changes take effect on
  subsequent requests; worker execution rechecks access. Disabling an account
  revokes its existing login sessions, even if the account is later re-enabled.
- One operator owns a show. Other assigned DJs can view the booth while controls
  are locked; administrators can request the show's end. Control becomes available
  again after the observed return to automation. The existing deck/mic engine
  supplies source state and timestamps; stale observations are shown as unknown.
- Recording is an explicit choice before entering DJ mode or going live. The
  station's final program output is captured locally as 192 kbit/s MP3, including
  deck, WebRTC microphone and cart audio. It closes on automation return. Recorder
  failure is reported independently and does not stop the broadcast output.
- **Show recordings / My recordings** is a station recording file manager. It
  provides playback, downloads with byte-range support, filename changes, filename
  and DJ search, status filters, date/name/size/duration sorting and pagination.
  The display/download name changes on rename; internal UUID filenames remain
  stable to match Freo's storage conventions.
- Confirmed deletion is queued for the existing automation worker. The worker
  validates access and file type again, deletes the MP3, and retains metadata/audit
  history. Pending deletion blocks new downloads. Missing files are safely treated
  as already removed. Failed deletions can be retried. Active or unfinished captures
  cannot be renamed or deleted. Deletion is permanent; no recycle bin is provided.

Public listener pages, published assets and existing public metadata APIs remain
public. Station permissions govern private DJ/administration operations; they do
not make the station's public broadcast private. Existing deliberately shared music
also remains available through the assigned station's normal catalog rules.

## Review findings fixed

1. Unpublished website theme/assets accepted any authenticated account. They now
   require ADMIN, closing draft preview access for DJs.
2. Disabled-station logo and player artwork previews accepted any authenticated
   account. They now require access to that station.
3. Login lowercased the entire identifier, preventing sign-in by mixed-case DJ name.
   Login now recognizes the entered username while retaining normalized email login.
4. Some static booth controls remained disabled after another operator released
   the show. The ownership refresh now restores those controls.
5. A pending microphone preparation could reach the engine before the worker
   checked revoked access. Authorization now precedes preparation/admission.
6. Account deactivation left durable login sessions available for later revival.
   Disabling through DJ administration now revokes those sessions.
7. Recording storage inventory needed to exclude deleted-file tombstones from
   expected files. Deleted MP3s no longer produce false missing-file counts.
8. File management now protects against cross-account/cross-station access,
   missing CSRF, stale revisions, unsafe names, active-file mutation, symlinks,
   revoked queued permissions and failed file removal.

9. The broader regression run found repeated station/permission lookups while
   serializing completed imports (318 SELECTs for 100 songs). Serialization now
   reuses the already-authorized station, restoring the existing query-count bound.

10. Playlist navigation summaries omitted metadata present in the full summary.
    They now include the same leader/rule/weight fields without loading tracks.
11. A historical migration test assumed its old revision was still the current
    head. It now verifies that revision remains in the single release migration
    chain, allowing later additive migrations. No release version was changed.

12. Worker recovery now distinguishes durable AUTO_CUE commands from orphaned
    human commands. Cue playback bindings preserve automatic recovery; revoked
    show ownership still blocks it. Arming AUTO_CUE claims the operator's show.
    Older operator-interruption fixtures now supply their real test operator.

## Schema and activation

- `f306a1b2c3d4_dj_sessions_and_recordings.py`: account roles, station assignments,
  single-owner live sessions, recording metadata and engine observations.
- `f316a1b2c3d4_recording_manager.py`: recording names/revisions and durable deletion
  request, requester, outcome and error metadata. Existing history and storage keys
  survive upgrade. Downgrade removes manager metadata, not media files, and cannot
  undo completed deletion.
- Recordings use `FREO_MEDIA_ROOT/<station-slug>/recordings/<uuid-hex>.mp3`.
  The recording directory is owned by playout; the web process has read access.
  The provisioning helper grants automation directory write access and narrow
  systemd `ReadWritePaths` entries for deletion. No new daemon, gateway, port,
  package or podcast service is introduced.
- Activation requires applying both migrations, provisioning participating V1
  recording directories, installing the matching Liquidsoap template, and restarting
  matching V1 services. Read `V1_UPGRADE_NOTES.md` before doing so. These activation
  steps were not performed here. An old engine or missing recording directory is
  reported as unavailable recording capability, without denying the DJ show.

## Verification

Checks run with `PYTHONDONTWRITEBYTECODE=1 FREO_ENV_FILE=/dev/null DATABASE_URL=sqlite://`.
Browser/audio tests use disposable files and loopback/private sockets. PostgreSQL
checks use a temporary cluster on `/tmp/freo-manager-pg`, port 55474, with no TCP
listener and automatic shutdown. Dependencies absent from the read-only interpreter
were installed offline from existing pinned wheels into `/tmp/freo-manager-test-deps`;
production's Python environment was not changed.

| Check | Result / evidence |
| --- | --- |
| Existing booth/browser compatibility | 29 passed (`/tmp/freo-manager-booth-browser.log`) |
| Show ownership, recording manager and mobile browser | 3 passed in the final combined run (`/tmp/freo-manager-final-browser.log`); later account-switch failures were rerun below |
| New DJ accounts: decks, Cue, carts/IDs and microphone navigation | 4 passed (`/tmp/freo-manager-dj-workflows.log`) |
| Focused DJ, manager and microphone unit/API checks | 37 passed, 3 engine opt-ins skipped (`/tmp/freo-manager-focused.log`) |
| Final manager/permissions/dependency/import-query checks | 39 passed (`/tmp/freo-manager-final-unit.log`) |
| Cue recovery, DJ permissions and scheduling interactions | 56 passed (`/tmp/freo-manager-cue-recovery.log`) |
| Real Liquidsoap Cue cycling, reordering and restart recovery | 2 passed (`/tmp/freo-manager-cue-engine.log`) |
| Actual MP3 program, WebRTC, fallback and loudness | 8 passed (`/tmp/freo-manager-audio.log`) |
| PostgreSQL migrations and simultaneous show claims | 3 passed (`/tmp/freo-manager-postgres.log`) |
| Concurrent recording rename | 1 passed (`/tmp/freo-manager-rename-concurrency.log`) |
| Real service-account filesystem ACLs | 1 passed (`/tmp/freo-manager-storage.log`) |
| Pagination, storage provisioning, retry and latest fixes | 2 + 2 + 3 + 1 passed in `final-extra`, `retry-proof`, `last-fixes` and `location-chain` logs |
| Final web and visual-schedule regression batch | 30 passed, 1 long simulation deselected (`/tmp/freo-manager-regression-tail.log`) |
| JavaScript checks | Changed files pass `node --check`; preview harness passes `node --test` |

These run counts overlap; they should not be added as a unique-test total.
The private-route matrix covers **132 route/method pairs**, each denied both for
an unassigned/restricted DJ and an anonymous visitor, with additional resource and
positive-access tests.

The broader non-browser sweeps recorded **609** and **473** completed passing cases,
with **79** and **41** opt-in skips. Their **11** observed failures were addressed:
four missing-dependency environment checks, import polling query count, a loudness
timeout under load, two outdated migration-head assertions, playlist-summary
metadata, and two operator-command fixtures lacking an operator. The relevant
checks passed on subsequent runs listed above. No production dependency changes
were made to resolve the environment checks.

The first sweep was stopped during unrelated four-week scheduling simulations;
the second process ended before a final summary while reaching a long legacy
calendar simulation. Pass counts for that second sweep are the completed pytest
progress markers in its retained log. Remaining ordinary web/scheduling tests were
run separately. This is **not** a claim that every repository test or long-running
simulation completed. Other PostgreSQL, system and soak opt-ins remain outside this
DJ-focused validation.

New browser account-switch tests initially cleared cookies while the old booth was
still polling, producing login-CSRF races. They now exercise the real Sign out flow.
Long combined runs also ended before final summaries; the new DJ workflows were
repeated in smaller batches. All seven new browser cases passed across these split
runs: three show/manager cases and four newly created DJ workflows. The final
real-engine Cue recovery run also passed both cases. The first combined browser
run itself was not a clean pass, and is not counted as one.

Fake account matrix used an administrator, a DJ assigned to station A, a second DJ
also assigned to A, a DJ assigned only to B, an unassigned DJ and a disabled DJ.
Accounts were created through the administrator route and signed in using real
password/CSRF/session flows. A separate Chromium workflow creates a DJ through the
visible form, signs in by DJ name and manages an actual local MP3.

The access sweep enumerates all registered private administration route/method
pairs relevant to denial, instead of relying on a short hand-selected URL list.
Allowed station routes are tested with an unassigned station. Resource-specific
checks separately cover own/other recordings, administrator overrides, stale forms,
assignment changes and deactivation. These are application acceptance/regression
checks; they are not a claim of a formal penetration test or production soak.

## Deferred and operational limits

- External encoders remain deferred. Future encoder ingress can reuse station
  permissions and show ownership, feed into the existing final program source, and
  expose observed connect/disconnect transitions through the existing live lifecycle.
  Encoder authentication, mount allocation, takeover policy and disconnect recovery
  still need their own implementation; no external input was enabled here.
- No podcast publishing, editing, automatic retention, arbitrary filesystem browser,
  external storage backend or automatic transcoding of imported files was added.
- Storage provisioning is explicit for each station. Deletion requires the matching
  automation worker and directory/service permissions; a queued deletion remains
  pending if the worker is stopped. Existing downloads already in progress may
  finish after a deletion request.
- Test fixtures validate actual encoded audio separately from the browser's
  controlled engine observations. Production audio devices, network paths, service
  isolation and long-running resource use require validation during a later,
  separately authorized V1 activation.

### Reproduction commands

Use an isolated checkout/database/media root. All commands below assume the safe
test environment variables described above; do not point test database variables at
an installation database.

```sh
python -m pytest -q tests/test_phase3_dj.py tests/test_recording_manager.py
python -m pytest -q tests/test_phase3_browser.py
FREO_ENGINE_TEST=1 python -m pytest -q tests/test_phase3_engine.py \
  tests/test_live_mic.py::test_real_microphone_fade_return_and_disconnect \
  tests/test_live_mic.py::test_real_microphone_page_exit_restores_interrupted_feed
FREO_TEST_POSTGRES_URL='<disposable database URL>' python -m pytest -q tests/test_phase3_postgres.py
FREO_STORAGE_TEST=1 python -m pytest -q tests/test_phase3_storage.py
```

The storage permission proof needs the existing Freo service UIDs and root privileges;
its files and service override fixtures remain under `/tmp`. Browser checks need
Chromium/ChromeDriver and loopback sockets. Engine checks need installed Liquidsoap,
FFmpeg and the existing WebRTC dependencies.
