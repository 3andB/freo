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
