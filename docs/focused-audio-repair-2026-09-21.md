# Focused audio recovery repair

Scope: the owner narrowed the follow-up to the two audio recovery paths, short
repeatable checks, and one final two-hour live run. No UI redesign or broader
monitoring framework is included.

## Changes

- Reuse the existing AUTO successor preparation during the two-second stopped-DJ
  grace. PAUSE/CLEAR no longer waits until after that grace to begin selecting
  and loading replacement audio.
- Begin natural-EOF preparation with 30 seconds remaining instead of eight,
  leaving room for selection and a cold worker restart. Existing event, schedule,
  Cue and manual-operation eligibility checks still apply. The identity-scoped
  handoff lease is still five seconds and is not extended by absent audio.
- Preserve a valid prepared successor while the outgoing request disappears at
  EOF, including when a restarted worker lacks its earlier in-memory marker.
- Add one compact engine handoff record at a DJ ending, with outgoing/target IDs,
  lease remaining and gate results. It uses the existing event log and is ignored
  by the numeric playback-event parser.
- Small runner corrections: retain a fallback observation across a blocking UI
  wait, explicitly marking its duration unconfirmed; attach the current engine
  snapshot before reporting findings; observe the Calendar boundary before
  switching away. No new monitoring service and no relaxed audio thresholds.

## Validation

Evidence root: `/tmp/freo-focused-repair-20260921/`.

- Deck/return unit regressions: 60 passed.
- Runner regressions: 14 passed, including recovery following a 25-second gap in
  polling without incorrectly claiming 25 seconds of continuous backup tone.
- Focused real-engine audio batch: eight passed. Early PAUSE/CLEAR with an
  injected 800 ms loading delay measured 2.10 and 2.35 seconds, within the existing
  2.75-second allowance. Ordinary A/B EOF gaps measured 50 ms and 0 ms. Calendar
  and understated-duration variants also passed.
- Cold interpreter/app/worker restart plus existing repeat, lease-expiry,
  worker-delay, programming-edit and Cue guards: ten passed. Both cold-process
  deck endings measured 50 ms audio gaps. Brief worker-delay/restart gaps were
  also 50 ms; long-absence expiry remained effective. Final focused total: 92
  passed (74 unit/runner checks and 18 real-audio cases).

These checks use private real-engine/Icecast audio fixtures. The cold-restart
cases use fresh worker subprocesses against the private SQLite stack; the final
live run is needed to validate both stations together on production PostgreSQL.
The checks do not establish that every historical EOF miss had one identical
cause. The retained handoff trace makes any recurrence attributable.

Verified pre-deployment backup:
`/var/backups/freo/focused-repair-20260921T181623Z`.
Application commit `ba64f38` was pushed and deployed. Both station configurations
validated and the web, worker and both station engines restarted; deployment
finished at 18:23:21 UTC. Post-deployment health/UI/asset checks passed. Both
stations had fresh AUTO observations and ten seconds of decoded audible music.
Evidence: `deployment.json` and `live-verification.json` under the evidence root.

The final two-hour observation started at **18:25:04 UTC** and is due to finish
at **20:25:04 UTC**, followed by restoration/audio checks. It runs application
commit `ba64f38` under `freo-live-final-2h-20260921.service`, with the existing
watchdog and independent restoration hook. The first checkpoint is clean and
all four timed event fixtures are installed. Evidence/progress:
`/tmp/freo-live-final-2h-20260921/run.json`. No completed live-test result is
claimed here. This documentation follow-up changes no tested application code.
