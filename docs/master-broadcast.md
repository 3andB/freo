# Master broadcast

Station Control's MASTER BROADCAST switch persists the station's existing
`desired_state`: ON is `running`, OFF is `stopped`. A revision prevents stale
browser tabs from overwriting a newer request. The browser queues the change;
`freo-provision.timer` applies it through the root worker every five seconds.
Only this station's systemd unit is started/enabled or stopped/disabled. OFF also
cancels pending DJ and schedule-transition commands. Saved programming remains.
Failed changes remain visible and can be retried. A newer request supersedes an
in-flight change without losing the pending request.

The complete Liquidsoap mix falls back to the station's tone at startup or after
three seconds below -55 dB. Audio returning for 100 ms restores the mix. This
covers automatic playback, empty or paused DJ decks, and lost live audio. The
short delay avoids inserting tone into ordinary pauses and fades. The approach
uses Liquidsoap's [blank detection and fallback](https://www.liquidsoap.info/doc-dev/blank.html).
The mixer observation reports whether tone is active.

Live indicators use the newest fresh worker/Icecast observation, never the master
switch position or browser monitor state. Red means online (including tone),
black means offline; unknown observations use black with an explicit unknown
status description. Station Control's indicator pulses slowly, except with
reduced motion enabled. All admin pages show each station's name, ON AIR indicator
and MONITOR button. Monitoring one station persists across workspace navigation;
selecting another monitor switches the listening audio without changing broadcasts.

## Rollout

Back up the database and use the normal release procedure. Apply
`flask --app wsgi:app db upgrade` before restarting the web and automation
services; the new station columns are required by both. Keep the provisioning
timer enabled. No new service privileges are introduced.

Existing generated Liquidsoap files must be re-rendered with
`flask --app wsgi:app station render <slug>`. Restart each currently running
station with `flask --app wsgi:app station restart <slug>` during an agreed
broadcast interruption so it loads the new fallback. Keep stopped stations
stopped. Changing the template alone does not update already running engines.
The migration preserves all existing running/stopped choices.

## Fresh-VM validation

1. Upgrade a database from revision `e92b740a613f`; verify existing station states
   and content survive. Check a fresh installation reaches the same schema.
2. Provision two stations. Turn both ON with empty libraries; confirm both Icecast
   mounts produce audible tone and both banner indicators turn red.
3. Play scheduled audio, then empty the queue. Repeat with DJ play/pause and a live
   microphone disconnect. Confirm source recovery, tone and observed status.
4. Turn one station OFF while the other plays. Verify its mount disappears, its
   unit is disabled, pending commands cannot resume it, and the other station
   remains online. Restart the server and verify these choices persist.
5. Exercise OFF during an in-flight ON, worker restart during application, and a
   service start failure. Check latest intent wins and errors/retries are visible.
6. Verify both monitors and all indicators on desktop/mobile, across navigation,
   with stale observations and reduced-motion enabled.

Automated checks include `tests/test_master_broadcast.py`,
`tests/test_master_broadcast_browser.py`, and opt-in real audio tests:
`FREO_ENGINE_TEST=1 pytest tests/test_master_broadcast_engine.py`.
