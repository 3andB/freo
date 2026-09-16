# LIVE MIC

LIVE MIC is a third DJ Booth view, separate from the existing AUTO/DJ engine mode.
Opening the tab has no broadcast side effect. CONNECT / TEST MIC captures a
browser audio input (including an OS-recognized USB microphone or the stereo USB
output of a mixer), displays its level, and establishes a WebRTC session. Audio is
drained continuously but gated off in Liquidsoap until GO LIVE.

The board shares the station's eight carts and four station ID slots. Software
gain ranges from -24 to +12 dB, with a post-gain peak meter, clipping indication,
and mute. Hardware gain remains on the USB device. Browser automatic gain,
noise suppression and echo cancellation are requested off for mixer audio.
Browser/driver support for these constraints varies; arbitrary multichannel
mixer channel routing is outside this first implementation.

## Broadcast behavior

- GO LIVE requires fresh engine readiness and arriving RTP audio, not merely
  browser permission or a signaling response. Zero-valued audio counts as a
  healthy connection: a quiet or muted mic must not trigger fallback.
- Liquidsoap fades the existing feed over the selected 0–10 seconds, then opens
  the microphone with a 20 ms smoothing ramp. The UI reports observed READY,
  FADING, LIVE, RETURNING, and FAILED states. Wait for ON AIR before speaking.
- The interrupted music sources pause at zero gain. END LIVE crossfades back to
  that feed and resumes its position; AUTO then continues normal scheduling.
  This preserves the outgoing feed rather than selecting a new song on return.
- Overlay carts duck the microphone by their assigned percentage. Takeover carts
  close the microphone while they play, then restore it. A browser-muted mic
  stays muted. Live speech during a takeover cart is discarded, not recorded.
- Program monitoring stops when GO LIVE is pressed. Monitoring may be re-enabled
  with headphones; hardware direct monitoring is preferable for the speaker.
- Changing tabs while live does not end the broadcast. Conflicting transport or
  engine-mode mutations are rejected until END LIVE finishes. Carts and their
  assignments remain available.
- A station admits one microphone session. It is owned by an authenticated user
  and an unpredictable per-tab token; a second tab cannot replace it. Access uses
  the existing `can_control_playout` boundary (currently all active admins, not
  a newly introduced station-role model).
- Closing/navigating away releases the session. A missing browser heartbeat
  expires it after 10 seconds. Missing RTP ends the PCM source after roughly two
  seconds; Liquidsoap also requires a worker-renewed six-second lease. Source or
  lease loss closes the microphone and returns the engine to AUTO without relying
  on the browser. Reconnection never automatically goes on air.
- Restarting the gateway loses its ephemeral sessions and safely ends broadcasts.
  No microphone recordings or microphone credentials are stored in the database.

## Architecture

Browser Web Audio gain/mute -> encrypted WebRTC/Opus -> `freo-mic` (aiortc) ->
bounded stereo PCM/WAV over loopback HTTP -> Liquidsoap mixer -> existing limiter
and Icecast output. PCM queues retain at most ten decoded frames and drop oldest
frames if a consumer falls behind, preventing a growing backlog of speech.

Flask authenticates and CSRF-checks same-origin signaling/control requests, then
proxies to the loopback-only gateway. Only the automation worker sends Liquidsoap
socket commands. The browser never receives Icecast or Liquidsoap credentials. Each loopback audio
URL is bound to the exact microphone session token, so a replacement session
cannot inherit an old open microphone gate.
The gateway binds **127.0.0.1:8091** and must not be exposed through nginx or a
public bind address. Its internal control API trusts local processes, just as the
existing playout control sockets do. No database migration is required.

## Installation and activation

The tab is available in the UI; microphone transmission is disabled until the
service and station configs are installed. This avoids claiming readiness on
servers without the receiver. Perform activation in a maintenance window because
station config changes require restarting the relevant playout processes.

1. Install `venv/bin/pip install -r requirements-live-mic.txt`.
2. Install `deploy/systemd/freo-mic.service` in `/etc/systemd/system/` and reload
   systemd. Set `FREO_LIVE_MIC=1` in the shared Freo environment.
3. Provide HTTPS for the booth. Configure ICE connectivity for the server's
   deployment. With a publicly reachable host, direct WebRTC requires inbound
   UDP to its negotiated ephemeral ports. Restricted networks/NAT may require
   TURN. Set `FREO_MIC_ICE_SERVERS` to a JSON array accepted by aiortc, and
   `FREO_MIC_BROWSER_ICE_SERVERS` to a browser RTCIceServer JSON array. For example,
   `[{"urls":"turn:YOUR_TURN_HOST:3478","username":"YOUR_USER","credential":"YOUR_PASSWORD"}]`.
   The browser configuration is supplied only to authenticated operators; use
   limited, managed TURN credentials. Do not commit actual credentials.
4. Enable/start `freo-mic.service`. Render each participating station using the
   existing root-run `flask station render SLUG` workflow, with the same environment
   loaded, then restart that station using `flask station restart SLUG`.
5. Restart `freo.service` and `freo-automation.service` with the updated environment.
6. Check input readiness with a real USB device on the deployed HTTPS origin and
   an external network. Confirm gain/mute, off-air test, GO LIVE, station IDs,
   END LIVE, and device unplug/browser-close fallback on a test station first.

Do not expose port 8091. WebRTC audio uses ICE-negotiated transports; putting the
HTTP gateway behind nginx alone does not establish audio connectivity. Input
readiness remains false on engines rendered with microphone support disabled,
even if the web and worker environment is later enabled.

Rollback: end microphone sessions, clear `FREO_LIVE_MIC`, re-render/restart the
station(s), restart web/automation, and stop the gateway. Existing AUTO and DJ
controls have no dependency on a running gateway while the feature is disabled.

## Validation

`venv/bin/pytest -q tests/test_live_mic.py tests/test_live_mic_browser.py` checks
authentication, CSRF, token privacy, ownership, readiness, generated WebRTC audio,
expiry, tab isolation and responsive layout. The receiver tests require the
optional dependencies and permission to bind local test sockets.

`FREO_ENGINE_TEST=1 venv/bin/pytest -q tests/test_live_mic.py` additionally launches
an isolated Liquidsoap process with a generated WebRTC tone. It measures the
received tone in the rendered WAV to test no pre-GO leakage, live audio, overlay
ducking, takeover muting, return, and loss-of-input fallback. It does not touch
production streams, service units, the production database, or station configs.

Before activation on a fresh VM, validate systemd startup after reboot, actual
ICE/TURN reachability from an external browser, two simultaneous stations,
permission denial, physical USB removal and reconnect, input channel mapping,
and audible end-to-end latency. Local automated tests cannot establish physical
USB compatibility or WAN latency.
