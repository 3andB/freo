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
