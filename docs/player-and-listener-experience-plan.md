# Freo player and listener experience

Status: implementation prepared, 2026-09-16. See [operator and rollout guide](player-and-listener-experience.md) for delivered behavior, validation, and release requirements. This original design includes future refinements beyond the initial implementation, including drag-ordered social links, in-place custom-listing editing, and additional publication diagnostics.

## Product direction

Make the public station page feel like the listening side of the DJ Booth: a large spinning record, luminous moving color rings, strong station identity, immediate playback controls, and useful programming information. Listening stays central even when messages, advertising, schedules, and community features are enabled.

“User selectable” means station admins control publication and available features. Listeners choose among enabled schedule views, dismiss a message, and reduce animation. These preferences do not change the station's settings.

## Existing foundations and gaps

- `app/templates/player.html` and `app/static/player.js` provide live audio, volume, sharing, station details, and history. The headline currently comes from the last confirmed start and explicitly cannot promise that the song is still playing.
- `app/static/freo.css` and `app/static/live.js` contain the DJ Booth record treatment to reuse as a visual foundation.
- `app/routes/station_settings.py` already supports identity, timezone, public URL aliases, private contact details, and validated square logos. Cover artwork should be a separate asset.
- `ScheduleProgram`, clocks, categories, and playlists already provide scheduling inputs. `app/services/schedule.py` resolves programming; the existing public schedule endpoint exposes older assignment data and is insufficient for a complete public calendar.
- `app/services/airplay.py` provides confirmed station-specific play counts. Listener votes and comments need separate records and aggregation.
- The current public status request probes Icecast synchronously. A popular player needs cached worker observations so listener traffic does not multiply backend stream connections.

## 1. Player design

Desktop composition, in order:

1. Full-width top advertisement, when configured.
2. Station cover with logo, name, location, description, and social links.
3. Optional station message.
4. Main listening area: record and track details on the left; current program, next program, and recent songs on the right.
5. Public schedule with Day / Week / Month controls.
6. Full-width bottom advertisement, when configured.

Use a charcoal base, readable high-contrast typography, generous spacing, and a station-selected accent palette. A conic color ring rotates around the vinyl, while a quieter background glow shifts through that palette. Artwork sits in the record label; station artwork supplies the fallback. Keep the title and artist outside the rotating element so they remain readable.

The record spins only while the listener's audio is actually playing. Pause, buffering, offline, and stale metadata have distinct states. Provide a low-motion preference and honor the operating system's reduced-motion setting. Any decorative bars must not masquerade as measured audio levels. Use CSS transforms and opacity rather than a heavy rendering library.

Provide large play/pause, mute, volume, share, and vote controls. Mobile uses one column and a compact sticky listening bar after the main controls scroll away, with safe-area padding and no overlap with ads or dialogs. Schedule defaults to an agenda on narrow screens; month shows day summaries that open an agenda.

Keep the audio element alive while changing schedule views, submitting feedback, and opening player panels. Integrate with the existing page/audio lifecycle so public playback and the admin monitor cannot accidentally play together. Add browser Media Session metadata and supported transport controls. Reconnect with bounded backoff and a clear retry control; never autoplay before a listener gesture.

### Accurate track identity first

Introduce a public-safe now-playing response built from fresh worker observations, with station, song identity, playback occurrence, observation timestamp, output mode, and metadata freshness. Never expose private paths or admin control state. Fall back to explicitly labeled history when current identity is unknown.

DJ transitions can contain two audible songs; display both where appropriate and attach each vote button to an explicit song. During imaging or uncertain identity, disable current-song voting and offer recently played songs instead. Stream buffering means server identity can lead what a listener hears; retain recent-song voting as a correction path and avoid promising sample-accurate synchronization.

## 2. Station settings

Organize settings into Identity, Player, Schedule, Social links, Advertising, and Listener feedback. Provide a desktop/mobile preview using saved or draft configuration without publishing draft data to public APIs. Explicit Save/Publish actions, visible validation, and revision checks prevent accidental overwrite by concurrent admins.

| Feature | Admin controls | Public behavior |
| --- | --- | --- |
| Station message | Plain-text box, 1,000-character limit, show/hide, optional start/end time | Readable announcement card; listener can dismiss that message revision |
| Radio cover | Upload, replace, remove, focal-point selection | Responsive 16:9 source cropped behind the station header; separate from square logo |
| Player styling | Accent palette, motion default, artwork preview | DJ-inspired record and color treatment with accessible fallbacks |
| Social links | Platform, URL, label, order, individual visibility, master show/hide | Labeled accessible icons; missing and disabled links never render |
| Schedule | Source mode, enabled Day/Week/Month views, default view, publication horizon | Only published, public entries appear |
| Feedback | Voting on/off, optional comments on/off, public totals on/off | Simple song feedback with confirmation and editable choice |

Support Instagram, Facebook, TikTok, YouTube, X, SoundCloud, Mixcloud, Discord, and a website/custom link. Validate http/https URLs, reject executable schemes, escape all labels, and open external links safely. Use existing upload validation principles for covers and ads: bounded file/pixel sizes, real decoding, metadata removal, image re-encoding, and generated responsive variants. Keep contacts private under their existing setting.

## 3. Automatic and custom public schedules

Separate the **time range shown** (daily, weekly, monthly) from **how the schedule is created**. A monthly view is an expansion of scheduled occurrences, not an instruction to repeat the same day for a month.

Offer three source modes:

- **Automatic:** project the existing broadcast schedule into public entries. Default the title to the scheduled category or playlist name. For mixed clocks/shows use the program title or an admin-supplied public title; do not pick an arbitrary category from a mixed show.
- **Custom:** create public listings with title, description, start/end, one-off or weekly recurrence, optional category/playlist reference, and visibility. Make clear that these listings alone do not change what plays.
- **Automatic with overrides:** retain automatic times while allowing public titles, descriptions, hidden entries, and date-specific replacements.

Provide a guided “Build from categories/playlists” action when broadcast programming has not been configured: select sources, order, start times, durations, and repeat days; preview coverage and conflicts; explicitly apply to the existing broadcast scheduler. Names alone cannot determine airtimes. Do not introduce another playout scheduler.

Use station-local time, overnight blocks, date overrides, and the existing resolution rules. Validate daylight-saving transitions, missing/deleted sources, overlaps, and gaps. Label default/fallback coverage honestly. Show “Live DJ” or “Program changed” when observed output differs from the plan; never rewrite history to pretend the plan aired exactly.

Publication options:

- Manual preview and Publish creates an immutable public schedule revision.
- Opt-in auto-publish maintains a rolling horizon, initially 31 days, from valid saved broadcast changes and a scheduled refresh. Keep the last valid publication and show an admin error if regeneration fails.
- Copy resolved labels and source references into each publication so a later rename does not silently mutate published history. Republish to apply changes; preserve custom overrides until explicitly removed.
- Preview additions, removals, and overrides before manual publication. Unpublish hides listings without deleting broadcast programming.

Public APIs accept bounded date ranges and return only published fields. Cache by station, revision, and date range. Highlight the current program and next transition; avoid publishing exact future songs as guaranteed when automation has not selected them.

## 4. Advertising

Choose **5:1 desktop creative**, recommended 2000 × 400 pixels. It leaves more room for the music interface than 4:1. Each slot spans the viewport width, with a centered creative area capped at 1600 pixels on very wide displays; surround it with a matching background.

Provide independent top and bottom slots, each with enable switch, image, accessible description, destination URL, optional active dates, and a preview. Use separately uploaded **3:1 mobile creative**, recommended 900 × 300 pixels, so text stays readable. If mobile art is absent, contain the desktop creative without cropping and flag its small-screen readability in preview.

Label active slots “Advertisement.” Reserve image dimensions during loading, collapse unconfigured/inactive slots, and avoid sticky ads, automatic audio, and arbitrary script snippets. The initial release supports direct image sponsorships. Third-party ad serving and campaign reporting can follow as separate work.

## 5. Votes, comments, and song stats

Place thumbs-up and thumbs-down beside the current song and on recent-song rows. A vote saves immediately; “Add an optional comment” opens a compact form with a 500-character limit. Do not make commenting a prerequisite for voting. Announce save/failure accessibly and keep input on errors.

Default counting rule: **one active vote per listener, station, and song**. Listeners can switch or remove their vote; repeat plays do not multiply it. Store the originating confirmed playback occurrence for context, and pin that identity when opening the form so a track change cannot redirect feedback. Offer recent confirmed songs for a bounded period, initially 24 hours. Reject songs that were never confirmed on that station, imaging, and fabricated playback references.

Start with an opaque signed anonymous listener cookie, avoiding forced sign-in. Use server-enforced station-scoped uniqueness, transactional updates, request throttling, origin/CSRF defenses suitable for anonymous writes, and idempotent retries. Anonymous cookies reduce casual duplication but cannot guarantee one human per vote across devices or cleared cookies. Avoid invasive fingerprinting; introduce account verification only if abuse warrants it.

Comments are **private to station admins by default**. Show them in a feedback inbox with song, vote, time, and new/reviewed/spam state. Admins can exclude abusive votes with an audited reason; changing comment status alone must not silently change vote totals. Do not reuse internal song-review flags as listener comments. If public comments are added later, require moderation before publication.

Extend Music rows, the song inspector, and Sound Room stats with:

- Confirmed plays, thumbs-up, thumbs-down, net score, and approval percentage.
- Total accepted votes alongside percentages; show “No votes” rather than a misleading zero-percent rating.
- Optional comment count and a link into the private feedback inbox.
- Station-specific totals even when the same song is shared between stations.

Initial totals represent current active accepted votes. Keep vote-change events for later time-range analysis and moderation audit; define those reports separately so changing a vote does not produce ambiguous daily totals. Set a documented retention period for comments and abuse records and provide admin deletion controls. Votes inform programming decisions; they do not automatically skip songs or alter rotation weights.

## 6. Implementation structure

Use additive migrations and station-scoped services. Suggested records:

- `StationPlayerSettings`: visibility switches, message/revision/timing, palette, schedule preferences, feedback settings, revision.
- `StationAsset`: cover and advertisement images, variants, dimensions, content version, focal point. Preserve existing logo compatibility.
- `StationSocialLink` and `StationAdSlot`: ordered links and scheduled slot configuration.
- `PublicScheduleEntry`, `PublicScheduleRevision`, and published occurrences: custom inputs/overrides plus immutable resolved public snapshots.
- `ListenerVote`: station, track, pseudonymous listener key, value, originating occurrence, revision/timestamps; unique station/track/listener key and bounded value constraint.
- `ListenerComment` and feedback audit events: vote context, text, moderation state, timestamps; private serializers only.

Create public presentation, schedule publication, and listener-feedback services rather than adding these responsibilities to playout. Extend the existing settings UI and extract reusable player styling from the DJ visuals. Resolve public aliases/custom domains consistently; every endpoint must enforce station visibility and isolation. Hide unpublished configuration and private feedback even when a caller guesses IDs.

## 7. Delivery sequence and acceptance gates

| Phase | Deliverables | Acceptance gate |
| --- | --- | --- |
| 1. Foundation and settings | Migrations, validated assets, feature switches, message/social/cover editors, accurate cached public playback observation | Old stations still render; settings remain isolated; stale metadata never masquerades as a current song |
| 2. Player redesign | Responsive record design, rotating palette, mobile controls, message/social display, both ad slots, draft preview | Desktop/tablet/mobile work without overflow; controls are keyboard accessible; motion follows audio; no blank ad spaces |
| 3. Public schedules | Automatic projection, custom entries, overrides, source builder, publication worker, Day/Week/Month | Published labels and times match previews; overnight/DST cases pass; viewing or publishing listings cannot accidentally alter playback |
| 4. Listener feedback | Vote and comment endpoints, stable listener identity, feedback inbox, song statistics | Retries and concurrent vote changes count correctly; track changes do not move comments; shared songs remain station-specific |
| 5. Release polish | Performance, browser validation, migration rehearsal, operator documentation | Full feature journey passes on supported browsers; existing DJ, AUTO, monitor, playlists, and public URL behavior remain intact |

Validate services with deterministic schedule, publication, vote, moderation, and station-isolation tests. Add browser journeys for settings preview/save, message dismissal, social visibility, image replacement, ads, schedule navigation while listening, votes during song transitions, and reconnect behavior. Check mobile Safari and Chromium audio behavior, keyboard focus, screen-reader labels, reduced motion, long text, missing art, and slow connections.

Load-test public polling, cached schedules, and feedback writes; browser requests must not open new diagnostic audio streams. Generate appropriately sized artwork, lazy-load below-fold assets, pause visual work in hidden tabs, and avoid restarting audio on data refresh. Measure playback startup, metadata freshness, publication failures, and rejected/failed votes without logging comment bodies.

Deploy additively after database backup and migration rehearsal. Start with new optional features disabled for existing stations, enable on a demonstration station, then roll out by station. Feature switches can restore the simpler presentation without changing streams or deleting feedback. Validate schema/code rollback compatibility before release.

## Later enhancements

After the core release: calendar subscriptions, show reminders with explicit opt-in, shareable station/show cards, installable player experience, and a separate request queue for stations that want listener requests. Prioritize reliable listening, great visual identity, and trusted feedback before these additions.
