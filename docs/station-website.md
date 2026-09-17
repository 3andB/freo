# Station website

Every Freo installation opens at `/` with a station website. freo.world uses the same feature as its demonstration station. There is no separate marketing homepage or external CMS.

## Owner workflow

Open **Admin → Website** (`/admin/website`). This is an installation-wide editor, available before the first channel exists.

- Set the station name, hero headline, introduction, genre and location.
- Upload a hero photograph, square station image/logo, story photograph, browser icon and sharing image. JPEG, PNG and WebP up to 10 MB and 3000 × 3000 pixels are accepted. Add image descriptions; choose hero focal position and shading.
- Choose Olive, Ocean or Clay, or customize day/night background, surface, text and accent colors. Text and accents require 4.5:1 contrast against both surfaces. Pick editorial or modern typography and a day/night/device default. Listener theme preferences are separate from workspace preferences.
- Choose a featured channel and reorder channel cards. Every enabled, ready, non-deleted channel with an enabled stream appears automatically, including channels temporarily off air. Edit channel descriptions and artwork in Station settings / Player settings.
- Edit the station story, optional dated announcement, search/sharing metadata and social links. Email and phone stay private unless **Publish contact email and phone** is selected. Announcement dates include a timezone, for example `2026-10-01T09:00+08:00`.
- Toggle and reorder station numbers, schedule, story and announcement. Hero and channels always remain. Station numbers appear before channels when first; other supporting sections follow channels. Empty optional content is omitted.

**Save draft** keeps changes private. **Save & preview** opens the actual renderer in a desktop/mobile preview. **Publish website** atomically publishes text, appearance and image references. **Discard draft** returns to the live publication. Publication history retains six versions; restoring one publishes it and replaces the draft. Concurrent editors get a conflict instead of silently overwriting another save.

Website identity belongs to the installation. Channel identity belongs to each channel. Initial website values use an existing ready channel when available, preferring one configured to run; saving freezes that identity until the owner edits it. A new installation with no channels has neutral starter branding and a Coming soon state. It never fabricates tracks, listeners or programs.

## Public data and links

Library totals count distinct accepted, enabled, non-deleted, non-decommissioned songs available to at least one displayed channel, including inherited sharing. Shared songs count once. Artist totals use catalog artist IDs. Optional play totals count confirmed music starts in the past 30 days. Song files and library administration remain private.

Cards display observed on-air status separately from enabled state. Unknown/stale signals say Status unavailable; current music is refreshed from the existing public player service. The homepage does not start audio. Player links honor public aliases and verified preferred domains.

Schedules use the latest published revision of channels with public schedules enabled, show up to 18 current/upcoming entries in the next seven days, and label each channel's timezone. Unpublished programming stays private. `/stations` redirects to `/#channels` on the installation host. Verified channel domain roots retain their station-only player; the installation website's assets are not served on those domains.

## Upgrade and rollback

Back up the database and run `venv/bin/flask --app wsgi:app db upgrade`, then restart the web service. Revision `d91f3a26b807` adds `website_settings`, `website_publications`, and `website_assets`. It does not alter channels, music or broadcast configuration. Existing installations get a usable default without a data-seeding command; the demo site's editorial configuration is data specific to freo.world.

Back up website content before downgrading. Downgrading to `c84a2e019b36` drops these three website tables and their content; restore the previous application version at the same time. No radio engine restart is required for a website deployment.

Uploaded images are decoded/re-encoded and stored as immutable content-addressed assets with a smaller derivative. Public access requires a reference from the current publication. Draft images and previews require an active administrator and use private/no-store responses. Six retained publications preserve their referenced images; unreferenced assets are removed after a successful edit.

## Bundled artwork

`app/static/station/listening-room.webp` and `listening-room-800.webp` were generated using the built-in image generation tool, then encoded as WebP for the website. `identity.svg` is a code-native record illustration. Owners can replace all of these through Website settings.

Generation prompt: “Use case: photorealistic-natural. Create a beautiful editorial photograph for an independent radio station website hero, panoramic landscape composition. A sunlit analog listening room with a walnut turntable and black vinyl record in the lower right foreground, a softly lit wall of vinyl records behind, leafy plant at far right, warm amber late-afternoon light and muted olive tones. Real tactile wood, subtle film grain, beautiful natural shadows, sophisticated music magazine photography. Keep the left half relatively quiet with dark shaded shelving suitable for an overlaid large white heading; turntable and sunlight are strongest on the right. No people, no lettering, no logos, no UI, no watermarks. Wide cinematic 3:2 or wider crop, high resolution. This is a reusable locally bundled station homepage photograph.”

## Verification

`tests/test_homepage.py` covers eligibility, deduplicated totals, publication/restoration, authorization, private draft assets, contact privacy, link/color validation and public-only schedules. `tests/test_homepage_browser.py` covers responsive layouts, both themes, no-JavaScript listening links, editor publication, mobile preview and persistent monitor navigation. Run with `FREO_ENV_FILE=/dev/null` to keep installation-specific configuration out of isolated tests.
