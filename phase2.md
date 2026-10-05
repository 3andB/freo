# Freo V1 — Phase 2 completion, fixes and testing report

Review date: 5 October 2026 UTC. Workspace `/opt/freo-v1`, branch `develop/v1`.

**Status: complete for review. Full-hour evidence verified; corrected harness passes.**

## What Phase 2 delivers

| Requirement | Implementation |
|---|---|
| Cue in / cue out | Explicitly saved boundaries control Liquidsoap decoding on automation, leaders, decks, carts and events. |
| Fade in / fade out | Per-track linear envelopes precede existing mixer gains and station processing; pausing preserves fade position. |
| Manual gain trim | Optional −12 to +12 dB trim follows LUFS normalization and retains the measured peak ceiling. Unanalyzed tracks allow attenuation but suppress positive boost. |
| Waveform editing | Pointer/keyboard cue and fade handles, numeric fields, draft preview, original audition, Save, Reset and Reload. |
| Preview accuracy | The existing browser audio graph applies cue boundaries, fades and effective gain. Listening volume stays independent of saved settings. |

Original media remains intact. Existing cue suggestions stay inactive until an explicit audio-editor save. Unconfigured tracks retain their previous playback; unedited carts retain their previous gain behavior. Analysis preserves saved boundaries, including blanks, and metadata saves cannot overwrite audio edits.

This extends the existing editor, scheduling estimates, SelectionDecision records, queue adapter, programming refresh and confirmed START/END flow. Liquidsoap remains responsible for playback/mixing. Prepared audio retains its duration/gain policy when the library track is edited.

## Corrections made during review

1. **Preview timing:** buffering cancels scheduled ramps; playback resumes them from the actual source position. Seeking and playback-rate changes rebuild the envelope.
2. **Preview freshness and retry:** a fresh library audition fetches saved settings even for the same song. Failed fetches no longer cache incomplete song state.
3. **Waveform keyboard editing:** a blank cue-out field starts at file end when moved with arrow keys. Keyboard values stay within source duration, and draft cue/fade validation requires whole milliseconds, matching the API.
4. **Calendar estimates:** overlap warnings use the shared event estimator, including trimmed smart-playlist members, leaders and ONE/ALL playback policy.
5. **Crash durability:** workers persist audio snapshots in their existing pre-submit transactions before engine queue mutation. A crash after acceptance cannot lose the prepared duration/gain. This covers automation, manual loads, decks, carts, events and scheduling handoffs.
6. **Soak validation:** decoded audio alone can hide wall-clock lag. The harness now checks Liquidsoap clock lag as well as silence; heavy regression jobs finish before the acceptance soak starts.

## Migration and upgrade requirements

Additive migration **`f206a1b2c3d4`**, following Phase 1 `f106a1b2c3d4`, adds:

- `tracks.audio_edit_enabled`, `audio_edit_revision`, `fade_in_ms`, `fade_out_ms` and optional `gain_trim_db`.
- Nullable `audio_snapshot` JSON on selection decisions and event execution items.

Existing rows default to unchanged playback. Disposable PostgreSQL tests verify upgrade/downgrade/re-upgrade preservation and concurrent revision-checked saves.

[V1_UPGRADE_NOTES.md](V1_UPGRADE_NOTES.md) records schema, endpoint, Liquidsoap, compatibility and rollback requirements. A future rollout needs matching code/schema and regenerated, validated V1 engine configurations. No new production service, port, package, user, storage root or permission requirement is introduced.

## Regression results

Implementation and review evidence currently contains **411 distinct passing pytest cases**, including 34 short real-Liquidsoap cases, four browser workflows, two PostgreSQL cases and the soak case. Overlapping runs count once. The full-hour recording is independently verified below; its original pytest result is retained with the corrected harness assertions explained.

| Review verification | Result |
|---|---|
| Broad affected backend regression | 327 passed; two temporary-ACL cases passed on authorized rerun (329 cases total) |
| Final crash-durability and integration regression | 234 passed |
| Browser editor workflows | 4 passed; final Phase 2/browser-clock rerun 3 passed |
| Deterministic preview-clock checks | 5 JavaScript cases passed, covered by one pytest wrapper |
| PostgreSQL migration and concurrent saves | 2 passed; private cluster stopped |
| Phase 2 engine and normalization review | 7 passed initially; two startup timeouts passed on rerun (9 cases total) |
| Final actual-worker deck lifecycle | 1 passed: load/play/pause/repeat/clear/mode |
| Corrected soak harness, end to end | 75-second check passed; pytest completed in 88.89 seconds |
| Python/JavaScript syntax and Git whitespace | Passed |

Coverage includes invalid/oversized input, station access, CSRF, revision conflicts, reset, analysis/save races, duration SQL parity, snapshots, annotation injection, smart-playlist estimates and crash recovery. Browser tests cover actual playback, gain, cue-out muting, seek/pause/resume, zero fades, polling, keyboard/pointer edits, missing waveforms, stale saves, reset and mobile layout.

Real Liquidsoap measurements cover AUTO, A, B, CART and EVENT using distinguishable intro/body/outro tones. They verify omitted boundaries, fade levels, gain and existing START/END callbacks where supported. A pause-during-fade case checks held source time and the resumed audio envelope. Neutral output and the unedited track following an edited track are native-PCM sample-identical to the original decoder path. Earlier broader engine regressions also cover leaders, crossfades, soft insertion, skip, event handoff, deletion and scheduled return.

Two ACL tests initially hit the filesystem sandbox's `setfacl` restriction; both passed with temporary files and the required test permission. Two engine processes exceeded their 60-second startup deadline during overlapping heavy runs; both passed with the same deadline on rerun. Existing SQLAlchemy fixture and migration deprecation warnings remain. An early concurrent pytest temporary-directory cleanup also warned; final runs use separate explicit temporary directories.

## One-hour soak

**Full-hour evidence: verified.** Application code stayed unchanged throughout this interval.

| Observation | Result |
|---|---|
| Start / finish (UTC) | 01:00:35.921 → 02:00:36.641 on 5 October 2026 |
| Measured wall-clock duration | 3,600.720 seconds |
| Continuously decoded audio | 3,600.71 seconds |
| Confirmed starts observed | 1,237 |
| Schedule transitions | 355, covering all six directed mode changes |
| Successful audio-editor saves | 177 |
| Worker observations | 10,329 |
| Longest schedule handoff | 3.752 seconds (limit: 10 seconds) |
| Maximum reported engine clock lag | 0 seconds (limit: 3 seconds) |
| Sustained fallback / silence ≥3 seconds | None detected |
| Maximum engine RSS | 164,780 KiB (160.92 MiB) |
| Final audio inspection | 1,814 frames of 50 ms, including 188 intermediate fade-level frames |
| Body / omitted intro / omitted outro peak | 0.044269 / 0.000194 / 0.000157 |

The hour's original pytest execution finished its full interval, then failed its old
save-count assertion: 177 saves versus a minimum of 179. That assertion assumed
negligible accumulated polling/API time. The corrected criterion allows one second
of overhead per nominal twenty-second interval, without changing the duration,
continuity, clock, transition or snapshot requirements. The original failure remains
in `soak-final.xml`; it has not been rewritten as a passing pytest execution.

Independent validation checks the original completed interval, UTC timestamps,
engine START events, decoder duration/logs, all six transition directions and retained
audio. It writes `soak-validation.json` separately from the raw `soak-result.json`.
A 120-second diagnostic additionally confirms both policies in accepted saves and
confirmed starts: nineteen 4-second/−6 dB starts and eighteen 3-second/−9 dB starts.

The recorder also needed a calibrated gain reference: FFmpeg's PCM16 mono downmix
measures 3 dB below direct float-mono decoding. The same known −6 dB engine output
measured 0.044269 through the recorder and 0.062605 through direct float decoding,
a ratio of 1.414210. The final spectral check uses the PCM16 reference. No playback
code change was needed for either of these test-harness corrections. The final
WAV-pipe shutdown reports a truncated last packet; retained clips decode successfully
and the decoder measured the complete interval.

The test uses generated audio, a fixture database, private sockets, actual worker refill/schedule handoffs and revision-checked editor saves. It switches among SIMPLE, BLOCKS and CALENDAR every ten seconds and alternates two cue/fade/gain policies approximately every twenty seconds. It checks confirmed starts and immutable prepared snapshots.

Audio is decoded continuously with a three-second silence threshold. The test also rejects sustained fallback, stalled audio output, handoffs over ten seconds and engine clock lag of three seconds. Four rolling recordings bound storage; final samples are checked for the selected body tone, omitted intro/outro, bounded gain and intermediate fade levels. Resource observations are retained.

The initial diagnostic run was stopped: while browser, database and engine tests ran concurrently, Liquidsoap reported a maximum **20.16 seconds of clock lag**. Decoded audio had not detected that timing problem. It is not counted as a successful hour. A subsequent short run was stopped for the crash-durability correction. Final acceptance starts from zero on corrected code, after other test jobs finish.

Reproduce with the repository's existing test dependencies:

```sh
PYTHONDONTWRITEBYTECODE=1 FREO_ENV_FILE=/dev/null DATABASE_URL=sqlite:// \
FREO_PHASE2_SOAK_SECONDS=3600 python -m pytest -q tests/test_phase2_soak.py \
  --basetemp=/tmp/freo-phase2-soak --junitxml=/tmp/freo-phase2-soak.xml
```

Local evidence is retained under `/tmp/freo-phase2/`: JUnit XML, logs, `soak-final/test_edited_track_endurance0/soak-result.json` (raw), `soak-validation.json` (verified), engine events and bounded recordings. Temporary evidence is excluded from the Git payload.

## Deferred and practical limits

Preview represents track policy before station EQ, AGC, mixing, limiting and encoding. Browser/codec seeking is approximate; edited preview requires Web Audio. Loudness and peak analysis remain based on the original full file. The soak uses generated audio and local output, not a live Icecast/network listener or production catalog.

Destructive editing, segue/crossfade redesign, automatic cue activation, production rollout and real-catalog broadcast acceptance remain outside this phase.

## Safety and delivery boundary

The required directory and branch were verified before changes. Production `/opt/freo` and its `main` checkout remain frozen at `32495f607711a432c08973abeaf979973c9ee2ad`. No production migration, file/configuration change, service restart, deployment, main merge, tag or release operation was performed. The installed interpreter was used read-only with bytecode writing disabled.

The pre-existing `V1_AUDIT.md` is unchanged and excluded from the commit. Delivery is restricted to reviewed V1 changes on `develop/v1`; the commit/push outcome is confirmed separately in the final delivery message.
