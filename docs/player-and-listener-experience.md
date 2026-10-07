# Player settings and listener feedback

The public player now uses a DJ-inspired record with animated color rings, three palettes, cover artwork, track artwork when available, accessible live controls, and a compact mobile listening bar. Animations follow actual browser playback. The player has no reduced-motion option or automatic motion override. Current-song metadata comes from fresh worker observations; unavailable observations fall back to labeled recent plays. Public requests do not probe Icecast or open diagnostic streams.

## Station admin

Open **Player settings** from the admin navigation or the link in **Station settings**. The existing identity page continues to manage the name, description, timezone, logo, contacts, and public URL.

- **Station message:** up to 1,000 plain-text characters, a show/hide switch, and optional start/end timestamps including timezone. Listeners can dismiss a message; editing the message or its schedule makes the revised announcement appear again.
- **Cover and colors:** separate cover and logo, three palettes, top/center/bottom cover focal point. Record and visualizer animations run during playback.
- **Social links:** supported platform links with individual visibility and a master switch. Only http/https URLs are accepted.
- **Advertisements:** independent top and bottom slots, descriptions, optional links, and active dates. Use 5:1 desktop art (recommended 2000 × 400) and optional 3:1 mobile art (900 × 300). Empty slots collapse. Ads are labeled and contain no third-party scripts.
- **Feedback:** enable voting, optional private comments, and optional public totals independently.

Uploads accept JPEG, PNG, and WebP up to 10 MB and 3000 pixels per side. Images are decoded, metadata stripped, and re-encoded as PNG. Player images are bounded to 2000 pixels and mobile ad images to 900. Preview player opens an unpublished page in another tab; new uploads appear after saving. Preview schedule does not publish or save the draft.

Settings use revisions: if another admin changes the configuration, reload before saving. New optional features start disabled for existing stations.

## Public schedules

Choose which Day, Week, and Month views are available and the default view. Times always use the station timezone. Mobile uses an agenda for the week. Changing views does not replace the audio element.

**Automatic** projects the existing broadcast calendar and weekly defaults. A single-category or single-playlist program uses that source's title; mixed programs use the program or clock title. Uncovered time is labeled Station mix. To create a broadcast schedule, follow the Calendar link and select categories/playlists, airtimes, and repeat days using the existing program builder.

**Custom** uses the listings entered below the settings form. Add a weekly entry or a specific date, title, description, and start/end time. End times at or before the start cross midnight. These entries describe public programming and do not alter the audio engine.

**Automatic with custom overrides** replaces automatic windows with custom listings. Dated listings override weekly ones; same-priority overlaps are rejected. A hidden custom window removes that period from the public schedule. Remove and recreate an entry to change it.

**Save & publish schedule** creates an immutable 31-day publication with resolved labels and times. Renaming a category does not change an existing publication until republished. **Unpublish & hide schedule** hides the timetable and disables automatic publication without removing broadcast programming or historical publications.

With **Automatically publish** selected, saving player settings publishes immediately. The separate `freo-public-schedules.timer` refreshes broadcast changes and the rolling horizon about once a minute. It does not create duplicate publications when the content is unchanged. If regeneration fails, the last valid publication remains available and the service logs the failure. Watch the publication timestamp and `journalctl -u freo-public-schedules.service` when diagnosing stale listings.

## Votes and comments

Listeners vote on explicitly identified current songs or recent confirmed starts from the preceding 24 hours. The feedback dialog captures its song; a live track change cannot redirect the vote/comment. During DJ mixes, audible identified decks can each receive feedback. Imaging and unconfirmed songs cannot receive votes.

An opaque signed browser cookie identifies a listener. There is one active vote per listener, station, and song, including shared songs. A listener can switch or remove a vote. Retries are idempotent, conflicting edits are rejected, and the server applies CSRF/origin checks and write limits. This prevents casual duplication but does not establish one human per vote across devices or cookie resets. A daily keyed network hash adds a second throttle; raw addresses are not stored in feedback events. Behind a reverse proxy this limit may apply to multiple listeners sharing the proxy address.

A vote saves immediately. Comments are optional, limited to 500 characters, and private to the author and station admins. Choose a vote before adding a new comment. Removing a vote preserves its comment until the author clears it, an admin deletes it, or retention expires.

**Listener feedback** lists private comments and votes, with reviewed/spam status. Changing comment status does not change totals. Exclude an abusive vote with an audited reason, or restore it. Feedback can be filtered by song from Music, the song inspector, and song details.

Song statistics include thumbs-up, thumbs-down, accepted total, net score, approval percentage, and comment count. Percentages always accompany the vote count; an empty sample displays No votes. Feedback never automatically skips songs or changes rotation weights.

The maintenance timer removes comments after 90 days without listener updates and feedback event records after 30 days. Active vote totals remain. Admin moderation actions continue to use the existing audit log.

## Upgrade and rollback

This change adds migration `f84c1d92be30` after `f73b8c9012ab`. It adds player configuration/assets, published schedule revisions, votes, and feedback events. It does not rewrite audio, existing schedules, or play counts.

For an existing installation:

1. Back up the database and retain the previous code version.
2. Run `venv/bin/flask --app app:create_app db upgrade` with the installation environment.
3. Install `deploy/systemd/freo-public-schedules.service` and `.timer` under `/etc/systemd/system/`; run `systemctl daemon-reload` and `systemctl enable --now freo-public-schedules.timer`.
4. Restart the web service to load the registered routes. The broadcast engine configuration is unchanged.
5. Validate a demonstration station: identity/old URLs, cover, announcements, links, both banners, custom and automatic schedule publication, actual stream playback, voting, comments, and song statistics. Check the timer's logs and confirm its service executes successfully.

The installer now installs/enables this timer, and installation validation checks it. The publisher runs as `freo-automation` with no engine socket group added; it stays off the audio worker's timing path.

For a code rollback, disable the new timer and restore the previous application code; keep the additive tables to preserve settings and votes. A database downgrade to `f73b8c9012ab` deletes all new player settings, assets, publications, and feedback and must only follow a backup and an explicit decision to discard that data.

Fresh-VM validation: run the installer on a disposable Ubuntu host with PostgreSQL, create two stations, apply the migration, enable the timer, exercise the demonstration journey above, verify cross-station isolation and custom-domain routes, then test code rollback with the additive tables retained. Repeat backup/restore before using the sequence on production.

## Verification

Focused service tests cover settings/image validation, public privacy, aliases, fresh/stale observations, schedule previews/publications/overrides, overnight DST transitions, immutable labels, vote retries/revisions/rate limits, moderation, retention, and song artwork access. Chromium browser tests cover real local audio, uninterrupted calendar navigation, voting/comments, mobile overflow, announcements, preferences, and admin settings. PostgreSQL tests exercise the full migration upgrade/downgrade/re-upgrade and simultaneous conflicting vote submissions.

Mobile Safari, production-scale traffic, and deployment on a fresh VM still require release-environment verification. No sample-accurate promise is made for metadata arriving ahead of a buffered stream.

Verification recorded on 2026-09-16: full non-browser suite 298 passed / 15 skipped; isolated PostgreSQL suite 5 passed; player/custom-domain/workspace browser run 8 passed / 1 skipped, followed by 3 passing final player browser checks including mobile ads and draft preview. The final focused player suite passed 13 tests, including audible DJ sources, artwork, unpublishing, malformed feedback, retained drafts, and multiline text. These checks do not constitute a production deployment.

## V1 audio analysis and visualizers

The existing visualizer offers Fractal, Spectrum, Waveform, Particles, Ambient,
Aurora, Ethereal, and Space. All eight use decoded samples from the playing
station, never random or synthetic audio activity. Aurora draws layered luminous
curtains; Ethereal draws translucent line clouds and rays; Space places Earth at
the center with four stylized planets and expanding frequency-sensitive wave
fronts that illuminate planets as they arrive. Station defaults and listener
preferences use the existing visual-mode settings.

On iPhone/iPad, the native media volume property cannot reliably adjust output.
The player hides and disables the slider and displays “Use your device volume
buttons.” A native-property probe also handles unsupported browsers; iPadOS's
Mac-style identity is covered. Desktop Safari and Android retain volume control.
Mute remains available independently of the visualizer, including when Web Audio
initialization fails.

`player_audio.js` owns analysis and the playback fallback. Capture-capable
browsers analyse a captured media stream without a destination connection.
Browsers without capture use one playback-owned media-element source and gain,
with the analyser on an optional branch. Creation/resume starts in the Play or
visualizer-open gesture; later readiness/state events complete the connection.
A context which initially remains suspended can subsequently finish attachment.
The public `/listen/` route redirects to the same-origin `/stream/` proxy. Unknown
external media are not routed through the playback fallback. Restricted capture
or unavailable browser features produce an explicitly labeled resting scene.

Closing, hiding, or pausing releases optional analysis
and stops animation. The audible fallback remains playback-owned. Renderer and
analyser failures do not disconnect its output. Reconnects and replaced elements
reattach analysis; obsolete contexts and capture tracks are disposed. Browser or
saved reduced-motion preferences and legacy station motion settings do not
disable player animation. A browser-level failure of the audible
AudioContext remains a limitation of Safari's non-capture route.

Rendering uses Canvas 2D plus an optional fractal WebGL surface, a 30 fps ceiling,
bounded geometry, and a canvas budget
of one million pixels on desktop / 600,000 on narrow screens, with DPR capped at
1.25. The obscured record pauses while the visualizer dialog is open. No graphics
framework, additional audio stream, or database migration is introduced.

For a read-only live-stream check, install Playwright and its Chromium/WebKit
browsers in a disposable test environment, then run:

```sh
python scripts/check-player-visuals.py --url https://YOUR-STAGING-HOST/player/YOUR-STATION
```

By default the verifier serves repository candidate assets only inside its test
browsers; it does not deploy or modify the server. Add `--deployed` to verify
assets actually served by the target server without interception. It checks desktop/Android Chromium and
desktop/iPhone WebKit, all modes, real analyser samples, repeated switching,
animation with OS reduced motion enabled, pause/resume, resource bounds, and
renderer failure while playback continues. Automated WebKit/mobile profiles are not physical Safari/iPhone tests.


## Rich visual scenes (V1)

`player_scenes.js` supplies optional scene rendering to the existing visualizer.
It borrows bass/mid/high energy and waveform RMS from `player_visuals.js`; it
never creates audio nodes, requests streams, or owns an animation loop.

- **Fractal:** five Mandelbrot/Julia destinations, continuous Julia deformation,
  bass-sensitive zoom, rotation and blended transitions every 20 seconds.
  A lazily created WebGL surface is reused between switches. Desktop rendering
  is capped at 400,000 pixels/96 iterations; narrow screens at 180,000/64.
  Missing WebGL, insufficient precision, shader/draw errors, context loss or
  two consecutive draws above 80 ms or a sustained draw average above 40 ms
  select a bounded Canvas escape-time renderer.
  The Canvas fallback is intentionally lower resolution/detail, refreshed at
  most roughly 8 Hz during ordinary playback, with immediate palette updates.
- **Particles:** galaxy, vortex, torus, ribbons and constellation formations
  blend on nine-second cycles, with projected depth and trails. A rolling bass
  baseline detects actual transients for expansion/ring accents. Counts are
  bounded at 420 desktop / 220 narrow-screen particles.
- **Ambient / geometric:** mandalas, projected polygon structures, lattices
  and curved ribbons blend on ten-second cycles, with layered surfaces and
  audio-driven deformation, expansion and edge light.
- **Ethereal:** predominantly pearl-white strands, soft mist, moving god rays
  and luminous motes. Perspective, layer parallax, scale and depth fading
  create dimension using Canvas rather than a volumetric rendering framework.
- **Space:** Earth/planet audio-wave behavior is retained, with up to 72 desktop
  / 36 mobile asteroids, a comet pass on a 15-second cycle and a UFO flyby on a
  24-second cycle. Lights, tails and expansion react to measured audio.

Scene time advances only during active playback with measured non-silent audio;
silence settles the effects and unavailable analysis retains a resting scene.
Each mode retains its own adaptive quality. Sustained expensive rendering reduces
geometry counts or raster resolution; the existing responsive main-canvas limits
remain in place. Hidden/closed/paused scenes stop their rendering loop. Page
cleanup releases the single graphics context, buffer, shader program and fallback
raster. No visualizer identifiers, settings API, default precedence or database
schema changed. Reduced-motion suppression remains removed at the user's request.


## Scene refinement and Safari recovery

The fractal selector and station-default label are now **Kai**; the stored
`fractal` identifier is unchanged. Kai's 20-unit zoom journey spans 32 beats
when a stable 60–180 BPM estimate is available. Positive spectral changes drive
an onset tracker; periodic intervals set a smoothed speed, without resetting the
zoom position. Sustained tones and missing beats do not invent a tempo. Without
a reliable estimate, the existing gentle zoom speed remains. Silence and
inactive playback still stop the scene clock.

Ethereal adds fixed, subtle blue/purple accents to its white strands, stronger
music deformation and two ray fans. Geometric adds sweeping depth movement,
transient pulses and traveling gradients inside shape contours. Aurora adds stars,
comets and a lower-third lake using one reusable sky surface and bounded
reflection strips. Five palettes join the original three: Ocean, Amethyst,
Rose Gold, Emerald and Solar. Palette preference storage is unchanged.

Spectrum now assigns each FFT bin to one contiguous band, excluding DC and
ending at 20 kHz or Nyquist. Its 64 bars use peak floating-point decibel levels
against a fixed −90 to −10 dB scale. The old mapping repeated the lowest bins
across several bars and treated compressed byte levels as linear power. No
frequency EQ or automatic normalization is applied to the display or playback.

For Safari's non-capture path, a new gesture can retry a pending context resume
without waiting for an earlier unresolved promise. A one-sample silent source
primes the audio unit in the gesture, and the optional analyser connects through
a zero-gain sink; audible playback retains its separate gain route. The sink is
removed with analysis. Page restoration and selector gestures retry attachment.
Rendering uses native media/context state rather than the UI buffering class.
Missing samples show an Enable visuals action instead of pretending that an
AudioContext reporting running guarantees a useful signal. Zero samples can
also mean station silence. These recoverable cases do not establish that every
physical iOS Web Audio issue is fixed; see
[WebKit's interruption report](https://bugs.webkit.org/show_bug.cgi?id=273511).

The read-only `scripts/check-player-safari-recovery.py --url URL` reproduces a
pending initial resume and a second interruption in an iPhone-sized Linux WebKit
profile. Add `--deployed` to check actual served assets. It requires changing
Canvas pixels, nonzero real stream samples, one active context, a zero-gain
analysis sink and continuing audio after closing the visualizer.

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

### 2026-10-07 — Isolate silent native-source delivery on iPhone

The first physical iPhone report (build `v1-iphone-debug-1`) shows stable
media/context/source/analyser identities, matching bindings, advancing media
and context clocks, a running 48 kHz context, no reported errors, and exactly
zero FFT and float PCM samples. Repeated resume attempts therefore do not
address the observed failure. The report alone cannot distinguish an analyser
connection issue, source sample delivery, origin enforcement, or actual silence;
confirmation that music was audible still matters. Linux WebKit uses a different
media backend and passing it does not establish that native iPhone Safari works.

Build `v1-iphone-debug-2` adds two explicit controls:

- `?audio_debug=1&audio_cors=1` sets `crossOrigin="anonymous"` on each new audio
  element before any source assignment, and preserves it across automatic
  reconnect. The report records the mode and loadstart value. The report's
  comparison link reloads the page; Play must be pressed again. This is an
  experiment, not a claimed CORS fix. Normal requests retain existing behavior.
- **Run source check** fetches at most 192 KiB of the same station, with a six
  second capture limit and eight second decode deadline. It records the final
  same-origin URL, redirect, status and exposed headers, decodes the MP3 in the
  existing context, and measures real PCM. A fresh, muted analyser first measures
  the current live source (`nativeTap`), then the decoded station buffer
  (`control`). Comparing these with the original analyser separates missing
  source samples from a problem confined to the original analyser. These samples
  are never provided to the visualizer.

Opening/copying the passive report still makes no additional stream request.
The source check runs only on its button, adds no context, does not resume,
reload or replace playback, and disconnects only its own temporary source edge
and nodes. Cancel, page cleanup, hidden state, changed playback or errors clean
up the probe. This explicit diagnostic adds one short listener request. No
report or captured audio is uploaded or persisted. A failed/zero control is
inconclusive, not evidence of a browser defect.

The V1 server's actual Icecast and Nginx stream responses lack an
Access-Control-Allow-Origin header. The observed `/listen/` redirect and final
`/stream/` response are both on the player's HTTPS origin, so that header's
absence alone does not establish a CORS failure. Server headers and audible
routing are unchanged. No continuous second-stream workaround or synthetic
visualization data has been introduced.

On iPhone, open the CORS comparison URL, press Play, open a visualizer and wait
ten seconds. Open Audio report, run the source check, wait for completion and
copy the report. Include whether music stayed audible and whether visuals began
working. If necessary repeat through the default-request comparison link. The
actual stream-to-Web-Audio fix remains dependent on this controlled evidence.

Validation: all three final diagnostic browser cases passed, covering default
capture/native routes, CORS set before load, nonzero station samples, original
analyser versus source-delivery fault injection, HTTP/decode errors, cancellation
while connected and during capture, retry visibility, clipboard behavior and
reconnect without lost playback. Six candidate real-MP3 checks passed across
Chromium and Linux WebKit: normal delivery, original-analyser silence and absent
live-source delivery each produced their distinct expected result while media
time advanced. JavaScript syntax and diff whitespace checks passed. These
controls still need the affected physical iPhone; no native Safari fix is claimed.

### 2026-10-07 — Make the iPhone source check independent of MP3 decoding

The second physical iPhone report confirms `crossOrigin="anonymous"` at
loadstart, a same-origin basic 200 MP3 response, stable source bindings and
advancing playback/context clocks, but all live analyser samples remain zero.
Changing request mode did not restore sample delivery. The diagnostic's captured
192 KiB fragment failed `decodeAudioData` with `EncodingError` before the fresh
live tap ran. This is a diagnostic design flaw: a live fragment is not a complete
audio asset, and accepting it in Chromium/Linux WebKit did not establish native
Safari compatibility. The error does not establish corrupt station audio or
explain the live media-element-source failure. See
[WebKit's decodeAudioData asset limitation](https://bugs.webkit.org/show_bug.cgi?id=106658).

Build `v1-iphone-debug-3` removes the fragment request and decode dependency.
**Run source check** first measures the existing live source through a fresh,
muted analyser, then feeds a deterministic PCM calibration buffer into that same
analyser. Calibration is explicitly labeled `known-pcm-self-test`; it goes only
through the probe's zero-gain branch and never into the player's analyser,
visualizers or audible output gain. No additional stream request or context is
created. The original live analyser is measured separately before/after. All
probe nodes and its specific temporary input edge are removed on completion,
cancellation, changed playback or failure. The audibility selector records the
listener's observation as `heardMusic`; its default is `unknown`.

`live-source-silent-calibration-passed` means both live reads were silent while
the same context/analyser processed the known input. If station music was
confirmed audible, that isolates missing delivery through the native source;
it does not identify Apple's internal backend defect. A positive fresh live tap
with a silent original analyser instead identifies the original analysis branch.
A failed calibration remains inconclusive. Native live-stream delivery problems
are also documented in [WebKit bug 180696](https://bugs.webkit.org/show_bug.cgi?id=180696),
but that external report alone is not proof of this device's underlying cause.

The visualizer still requires actual station samples. This revision fixes the
diagnostic; it is not a claim that the iPhone visualizer has been repaired.
Playback routing, stream headers and the sample-confirmed Enable visuals action
remain unchanged. To obtain the missing evidence, play music, open Audio report,
run the source check, select whether music was audible, and copy its result.

Validation: three browser regression cases passed. Coverage includes both player
source routes, retry visibility and clipboard behavior, pre-load CORS, injected
native-source/analyser faults, calibration isolation, decoder independence,
allocation failure, inconclusive calibration, cancellation in both probe phases,
zero additional stream requests and automatic reconnect with continuing playback.
Six candidate real-station checks passed in Chromium and Linux WebKit, with the
fragment decoder deliberately unavailable. JavaScript syntax and whitespace
checks passed. Physical iPhone confirmation remains required.

### 2026-10-07 — Bypass confirmed iPhone native-source sample loss

The physical iPhone report from build `v1-iphone-debug-3` establishes the failing
boundary: music was audible (`heardMusic=yes`), the original live analyser and a
fresh tap on the same media-element source both returned zero, while the same
context/fresh analyser measured calibration peak 0.125 and RMS 0.088388. Media
and context clocks advanced, bindings matched, and the playback graph did not
change. Earlier CORS comparison reports still failed with anonymous mode set
before load and a same-origin basic 200 response. The observed root cause is
missing PCM delivery from Safari's live MP3 MediaElementAudioSourceNode, rather
than a suspended context or Freo retaining a retired analyser. This matches the
class of native streaming problem tracked in
[WebKit 180696](https://bugs.webkit.org/show_bug.cgi?id=180696); the reports do not
identify Apple's exact internal defect.

Earlier gesture/resume/priming fixes exercised context recovery, which cannot
restore PCM that never enters the graph. Linux WebKit's media implementation did
not reproduce the physical-device failure. The original sample-capture control
also incorrectly relied on decoding a partial MP3 asset; build 3 corrected that
diagnostic independently. The sample-confirmed Enable visuals behavior remains.

Build `v1-iphone-stream-1` adds an optional analysis-only fallback. On **Enable
visuals**, an already running, silent native analyser can use a separate fetch of
the same station's same-origin MP3. A dedicated worker with pinned mpg123-decoder
1.0.3 decodes actual incoming bytes. Those PCM samples feed a Web Audio analyser
through their own zero-output-gain branch. Native audio continues on its existing
element/context/source/output path; no playback reload, replacement, extra
AudioContext, fabricated samples or audible duplicate is introduced. Healthy
native/capture analysis does not load the worker or request a second stream.
No CSP relaxation, server-side audio process, migration or Python dependency is
required. Decoder notices and corresponding source are shipped under
`app/static/vendor/mpg123/`.

The selected fallback is retained for this player page across visualizer switches,
close/reopen and audio reconnect. Its reader, worker and scheduled buffers stop
on close, hidden page, pause, native buffering, source change, graph disposal or
analysis failure. Reconnect starts analysis only once native media is ready to
play. One decode request runs at a time; PCM scheduling is bounded to roughly
2.3 seconds and 32 nodes, with decoder and stream-stall timeouts. HTTP, decoder,
worker and rendering failures never call the native player's pause/reconnect
methods. The retry action stays visible until nonzero actual station samples
arrive, and is offered immediately for fallback errors.

The fallback consumes a second station connection only while it is active. This
also counts as a listener connection and adds the stream's bitrate to network
use. It receives actual station audio, but independent native/fetch buffering
means exact synchronization with the audible stream is not guaranteed. No replay
of old samples or synthetic activity masks a stalled or silent fallback.

The report identifies `graph.route=stream-decoder`, with bytes/samples decoded,
worker status/error, queue/buffer counts, source sample rate and muted output gain.
The effective analysis input and native media source have separate identities.
The optional native-source self-test does not run against an active fallback,
which would otherwise mix the meaning of the two routes.

Physical-device confirmation (2026-10-07): after deploying commit
`80927c239fb2835076a60af09c0178c7724a9b2d` / build `v1-iphone-stream-1` to
`v1.freo.world`, the user confirmed that the visualizer works on their iPhone
17 Pro Max in Safari. This confirms the workaround on the previously failing
physical device. The confirmation did not separately enumerate every reconnect,
backgrounding or mode-switching check; automated coverage is recorded below.

Maintenance note: preserve the native audible playback path. The successful fix
bypasses Safari's silent media-element source for analysis by decoding actual
station MP3 bytes in `player_stream_worker.js`; `player_stream_analysis.js` feeds
that PCM into a separate muted analyser branch. `player_audio.js` owns activation
and cleanup, while `player_visuals.js` hides Enable visuals only after usable
samples arrive. Do not replace this with repeated context resumes, source-node
recreation or synthetic visualizer samples. Healthy desktop analysis retains its
existing route. Keep decoder resources bounded and release the extra stream when
visuals stop. The second connection and independent buffering remain the known
bandwidth/timing tradeoffs.

Post-deployment checks also passed against the public V1 player in Chromium and
Linux WebKit at 48 kHz, covering real station samples, all eight modes, reconnect,
close/reopen and continued playback. Public assets matched the committed files;
the V1 station playout process was not restarted. Production and main were not
changed.

Validation: ten targeted browser regression cases passed (805.79 seconds),
including the new real-MP3 fallback lifecycle/silence/HTTP/stall/worker-failure
case, three source-diagnostic cases, all eight desktop visualizers/fullscreen/
mobile layout, three visual-failure cases, reconnect/gesture recovery and pending
Safari resume recovery. Candidate live-station checks passed in Chromium and
Linux WebKit with mode switching, native reconnect, close/reopen, continuing
playback and worker cleanup. Linux WebKit also passed with a 48 kHz AudioContext
and the station's 44.1 kHz decoded PCM. These browser checks deliberately force
the silent native-analysis condition; they do not emulate Apple's media backend.
Changed JavaScript syntax and application/documentation whitespace checks passed.
Vendored upstream bytes, including their original whitespace, remain unchanged.

### 2026-10-07 — Keep diagnostics available without listener-facing test controls

The normal player no longer renders Audio report or the report/source-check/CORS
comparison controls, and does not load their diagnostic scripts. Add
`?audio_debug=1` to the player URL to restore all investigation controls and
collect from page load. The source test still requires an explicit click; its
calibration remains isolated from the visualizer. Code comments document these
entry points and safeguards. Enable visuals remains available when needed to
activate the confirmed iPhone real-stream fallback. Normal status text no longer
refers listeners to the hidden report. Playback and analysis routing are unchanged.

Validation: normal, disabled-debug and CORS-only URLs omit diagnostic markup and
scripts; the debug URL restores both. The existing media-source diagnostic
browser regression passed, including retry, reconnect and clipboard behavior.
JavaScript syntax and whitespace checks passed.
