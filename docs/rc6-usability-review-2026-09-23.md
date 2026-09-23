# RC6 administration and listening experience

Development branch: `feature/rc6-candidate`, based on main `fa4d476`.
Application version: `0.3.0-rc.6.dev1`. This is development work, not a frozen or signed release candidate.

## Changes

- Installation: padded sections, readable text width, bounded input widths, consistent headings and spacing.
- Feedback: aligned filter controls and buttons, responsive spacing and moderation actions.
- Station settings: one transactional save for identity/logo, default playback playlist, audio processing, and directory preference. Failed validation preserves the browser draft. Concurrent edits are detected. Audio and directory application remain durable background work, distinguished from saving. Directory publication and domain operations remain explicit actions, guarded against discarding a draft. Playback and shortcuts share the page container.
- Tags: consistent modern controls; vertically stacked Save/Delete actions and edited/saved feedback, including newly created rows.
- Categories: searchable list with descriptions, membership counts, confirmed plays, programming references, and enabled status. Creation is collapsed so the list is prominent.
- Music library: avoid loading artists/albums unnecessarily in the songs view; eager-load relationships in their respective views. Playlist navigation uses one aggregate SQL query instead of loading every member track. Idle polling slows to 15 seconds, remains faster during processing, avoids overlapping background requests, and preserves open menus.
- Song editor: controls stay inert until the catalog and handlers are ready, preventing early clicks from being ignored. Initialization failures provide a reload link.
- Import: visible playlist selection includes Playlist 1/2 and custom playlists. Automatic Station/Commercials collections remain controlled by audio type. Successful completed imports reset to a fresh workspace, retaining history and a visible link to imported songs. Failed, unfinished, or unsaved items prevent automatic reset. Done returns to Music.
- Player: restored the pre-RC4 vinyl texture from `1c60439`, with a slow CSS lava/LED center. Cover artwork appears separately below the transport at 144 pixels and never rotates. Reduced-motion preferences and hidden tabs pause animation.
- Statistics: larger markers, explicit update/aggregation guidance, refresh on tab return, uncached requests, and background refreshes that do not continually abort slower requests.
- Website: existing save/preview/publication/restore and responsive features checked. Publication history actions now confirm before discarding unsaved page edits.

## Validation

Isolated SQLite databases, temporary media, and headless Chromium were used. No tests used the preserved RC5 VM.

- Initial affected backend suite: 84 passed (statistics, settings, RC4/website, imports, catalog, tags, media).
- Updated backend suite: 119 passed (settings, catalog, import sessions, library, playlists, version reporting).
- Final atomic-save, pending-directory, category, playlist protection, and aggregate-query checks: 6 passed. Playlist summaries match existing results with one SQL query and no Track objects loaded.
- Browser acceptance passed for station settings and validation preservation; desktop/mobile installation, feedback, tags, and categories; stationary artwork and reduced motion; map/graph rendering and navigation; website publishing/responsiveness; import destinations/reset/duplicate handling; audio save/application status; and library availability editing.
- Browser tests uncovered an editor initialization race and a completion link hidden by the empty-import layout; both were corrected and their focused regressions passed. Async browser waits were corrected for changing DOM and normalized statistics URLs.
- JavaScript syntax checks, the schedule-editor Node test, Python parsing, and `git diff --check` passed.
- The recovery workflow now includes RC6 backend and browser acceptance checks. It has read-only repository permissions, runs tests, and uploads an unsigned development source-review artifact. The tag-triggered signing workflow is unchanged.

## Live statistics observation

Read-only production database transactions and a temporary authenticated browser session verified the user's two active test streams. Each station reported one listener. Both connections had coordinates at the same approximate location, so the combined map correctly displayed one point with count two. Fresh samples continued arriving; the latest chart interval reached peak two overall and one per station. The actual live page rendered its map and chart with no severe browser console errors. The 24-hour chart averages intervals; the past-hour view is more useful for short tests.

No production settings, code, services, or website publications were changed for this review. No restart was performed. Main remains the deployed baseline. No RC5 tag, package, signature, hash, artifact, or preserved VM was changed. This branch requires a separate reviewed deployment.
