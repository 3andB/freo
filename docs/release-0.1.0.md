# v0.1.0 release

This release closes the two recovery timing failures identified in the final
September 21 live run, without changing Station Control or DJ Booth workflows.

## Corrections

- PAUSE/CLEAR prepares scheduled music before stopping the last playing deck.
  The engine owns the existing two-second grace, so a delayed worker cannot
  extend the silent interval. A new deck operation cancels the pending return;
  request identity and stop timestamp prevent an older timer from acting on a
  later pause. Another playing deck, microphone, cart or event retains control.
- Natural EOF authorization lasts 15 seconds instead of five. The measured live
  failure had a ready successor but authorization expired 1.81 seconds before
  EOF. Identity checks and immediate manual cancellation remain, and an absent
  worker still loses authorization. This changes internal handoff tolerance,
  not the audio acceptance thresholds.
- The stress runner protects queued/playing and boundary-reserved station IDs
  beyond their nominal deadline. Previously it entered DJ mode after a soft
  ID's deadline and cleared the ID before its legitimate end-of-song boundary.
  Normal station-ID timing policy is unchanged.

## Validation

Evidence: `/tmp/freo-v010-20260921/`.

The final focused unit batch passed all 98 checks, covering deck operations,
return eligibility/adoption, Cue behavior, runner restoration/event protection,
and the authoritative 0.1.0 version.

All 23 final real-engine audio cases passed. A/B PAUSE/CLEAR resumed scheduled
music after 2.00–2.05 seconds, including early stops with an injected 800 ms
selection delay and the worker stopped throughout recovery. Manual takes
cancelled the pending return on both decks. Natural endings, brief and longer
worker stalls, restart, schedule edits, Cue ownership, inaccurate duration
metadata and long-absence lease expiry passed. Measured EOF/recovery gaps were
0–100 ms; backup tone does not count as programme audio. Existing limits of
250 ms for prepared EOF and 2.75 seconds for stopped recovery were unchanged.
Final focused total: **121 passed**.

Final source is retained in `audio-final/source/`; structured results, waveform
measurements and recordings are in the same evidence directory. Deployment and
post-restart live checks are recorded in `deployment.json` and
`live-verification.json` at the evidence root.

The preceding two-hour production run completed with findings; it is not a
clean release test. Three stale-worker observations and two fallback observations
with unconfirmed duration remain recorded in its evidence. No additional
multi-hour soak is implied by these focused regression results.

Pre-deployment database/configuration backup:
`/var/backups/freo/v010-20260921T204218Z`.
