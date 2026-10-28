# Station homepage and Website CMS

Status: implemented and deployed to freo.world, 17 September 2026. See the [owner guide](station-website.md) and [release verification](station-website-release.md). The specification below records the agreed scope.

## Outcome

Replace the Freo software marketing homepage completely with a beautiful, listener-focused station website. freo.world becomes a working demonstration of this same website feature. Every installation gets it at `/`, without a separate theme installation or external CMS.

The station's identity, imagery, music and channels lead the experience. Freo attribution is a small footer link. Remove the existing product tour, feature copy and homepage-only marketing assets from the project during implementation; do not retain a second marketing page.

## Design direction and page structure

Create an editorial radio identity: generous photography, confident typography, generous spacing, subtle borders and a clear listening action. A warm ivory day theme and deep charcoal night theme provide starting points, with station-selected accent colors. Avoid a dashboard appearance and excessive animation. Typography and fallback artwork are bundled locally.

| Order | Section | Content and behavior |
| --- | --- | --- |
| 1 | Station header | Station logo/name; Channels, Schedule and About anchors where applicable; compact mobile menu; discreet owner sign-in. |
| 2 | Image-led hero | Wide hero photograph, separately managed square station image/logo, station name, short tagline, location/genre and introduction. Primary action opens the featured channel's player; secondary action jumps to all channels. Owner-adjustable image focal point and overlay keep mobile crops and text readable. |
| 3 | Station numbers | Real song-library, artist and active-channel counts; optional confirmed plays over the past 30 days. Owners choose which metrics appear. |
| 4 | All channels | Artwork, name, description/genre, availability, current song when known, and a prominent Open player link for every eligible channel. Featured channel gets visual priority. Cards adapt to one, two, three or more channels. |
| 5 | On the schedule | Upcoming published programs, channel identity, local time and timezone; channel filter when useful and a link to the existing full player schedule. Hide when there are no published listings. |
| 6 | About the station | Longer station story, optional editorial image, location and music identity. |
| 7 | Station announcement | Optional compact announcement with a title, text, link and start/end dates. |
| 8 | Contact and footer | Visible social links, explicitly published contact information, copyright text and subtle Powered by Freo attribution. |

The hero and channels are core sections. Owners can hide and reorder supporting sections. Empty optional sections disappear cleanly. Audio starts in the existing player after listener interaction; homepage links do not introduce another audio controller.

## Automatic channels and reliable public data

- Interpret active as enabled, provisioned (`lifecycle_state == 'ready'`), non-deleted channels with an enabled public stream. Temporary broadcast downtime does not remove their cards. Exclude pending creation, failed provisioning, disabled and deleting/deleted channels.
- Automatically include new eligible channels, and remove ineligible ones on refresh. CMS ordering and featured selection cannot hide an otherwise eligible channel. New channels append in stable name/ID order; invalid saved references are ignored.
- Separate channel eligibility from on-air status. Show On air, Off air or Status unavailable using existing observed state and freshness rules. Never infer On air from the desired running state alone.
- Use existing public player routes, public slugs, aliases and verified preferred URLs. A temporarily offline channel still links to its player. If the featured channel becomes ineligible, select the first eligible channel deterministically.
- Reuse the public player presentation service for current music and artwork. Clear stale current-song information and recover gracefully when observations are unavailable. Do not expose internal queues or private scheduling data.
- Count distinct accepted, enabled, non-deleted, non-decommissioned tracks available to at least one displayed channel, honoring artist/album/song sharing. Shared tracks count once across the website. Count artists by catalog identity, not display-name strings. Label counts clearly as the station's available music library.
- Use published schedule revisions only, respecting each channel's schedule visibility and timezone. Use confirmed playback history for any play totals, with the period stated.
- Render identity, channel links and cached counts on the server. Refresh changing status asynchronously with bounded requests; pause polling in hidden tabs. Avoid per-card runtime socket checks in the initial page request.

## A simple Website CMS

Add an installation-level **Website** entry to the authenticated admin navigation, accessible even before a channel exists. Freo currently models channels as `Station` records; website branding needs its own settings rather than attaching the whole homepage to an arbitrary channel.

| Editor area | Owner controls |
| --- | --- |
| Identity | Website/station name, tagline, short introduction, about text, location and genre; initial values can be copied from a selected existing channel. |
| Images | Hero image, station image/logo, optional about image and favicon; upload/replace/remove, alternate text, crop/focal position and hero overlay. |
| Appearance | Curated palettes plus custom background, surface, text and accent colors; day/night/system default, visitor theme choice, and a small selection of bundled font pairings. Validate contrast for text and controls. |
| Sections | Supporting-section visibility and order; headings; metric visibility; announcement text, link and publication dates. |
| Channels | Featured channel and card order. Channel artwork, descriptions and enabled state continue to come from existing channel settings, with direct editor links. |
| Contact and sharing | Public social links and explicitly published contact details; page title, search description and social sharing image. |

Use structured fields and limited safe formatting, without a general page builder, arbitrary HTML or custom JavaScript. Show desktop/mobile previews with the actual renderer. Provide Save draft, Preview, Publish, Discard draft and Restore previous publication. Warn about unsaved edits and reject conflicting updates from another editor.

Website fields are authoritative for the overall station identity. Channel identity remains authoritative for each channel card/player. Copying channel identity into website settings is an explicit initial action, not ongoing synchronization. Existing private contacts must remain private unless explicitly published.

## Implementation approach

1. Add a singleton `WebsiteSettings` model with validated draft configuration and an optimistic revision. Store immutable published snapshots and a pointer to the current publication, retaining a small bounded history for restoration. Separate published image references from draft uploads so an unpublished replacement cannot leak onto the live site.
2. Add website asset storage using the project's existing validated-image patterns: decode/re-encode, strip metadata, constrain dimensions and byte size, and generate responsive hero/card variants. Serve published assets with versioned URLs and caching; authenticate draft assets and previews. Clean up unreferenced assets only after retained publications no longer need them.
3. Add a homepage service to assemble published settings, eligible channels, batched aggregate counts and public schedule snippets. Keep website publication atomic and independent of live channel/status refreshes.
4. Replace `home.html`, `home.css` and `home.js`; remove `product_screens()`, `_product_screen.html`, `_home_capabilities.html` and obsolete homepage-only imagery after checking references. Keep the existing Flask/Jinja stack and shared admin shell.
5. Add Website routes, forms and preview rendering with existing admin authentication, CSRF protection, field/URL validation, revision conflict handling and audit events. Private previews use no-store and noindex responses.
6. Update shared public navigation/footer so players and public pages no longer link to removed marketing anchors. Make `/stations` a compatibility redirect to the homepage's channels section on the installation host.
7. Preserve verified custom-domain behavior: those roots currently open the associated channel player and remain station-scoped. They must not expose every channel on the installation. Ensure new asset/status routes respect the same host boundary. A separate per-custom-domain website editor is outside this first release.
8. Generate canonical URLs and sharing metadata from configured/verified origins and published website content. Website branding does not change the authenticated workspace theme.

## Defaults, migration and demo setup

- A fresh, migrated installation with zero channels renders the finished station design with neutral starter identity, bundled imagery/fallbacks and a considered Coming soon state. Show no fabricated music, listeners, schedules or live indicators. The owner can open Website settings immediately and add the first channel through the existing workflow.
- When channels already exist, bootstrap unset website identity from the first eligible channel using a stable selection, preferring a running channel, and let the owner change it. Once saved, the identity does not switch when a channel stops or is removed.
- Keep missing database/schema setup distinct from an empty installation. Provide a controlled setup/unavailable response rather than swallowing operational database failures or rendering a broken page. Replace the old test that assumes the marketing page needs no database with explicit setup and empty-install tests.
- Configure freo.world through the same CMS with polished Freo Demo station copy, hero imagery and its real channels. Demo branding is site data, not hardcoded defaults inherited by other owners. Use actual library counts and observed status.
- Ship a database migration, update installation/owner documentation, and remove superseded marketing plans, release notes, screenshot-generation scripts and audits whose sole purpose was the deleted homepage. Retain shared test helpers or screenshots only if another feature actually uses them.

## Delivery sequence and acceptance

1. **Foundation:** settings/publication schema, assets, default configuration, channel eligibility and aggregate-count service.
2. **Station design:** full responsive homepage, real channel/player links, schedule and station information; review desktop and mobile captures using zero-, one- and multi-channel fixtures.
3. **Owner CMS:** editing, responsive preview, publication, restoration, image handling and accessible appearance controls.
4. **Integration and cleanup:** station-themed public navigation, existing URL/domain compatibility, removal of marketing content/assets and documentation updates.
5. **Validation and demo configuration:** migration rehearsal, focused integration/browser tests and freo.world content preparation through the CMS.

Acceptance requires:

- Every eligible channel appears automatically and opens the correct player; offline, disabled, provisioning and deleted states behave as specified.
- Song totals are correct across shared libraries and omit unavailable music. Only published schedule/contact content appears publicly.
- Saving drafts never changes published text or images; Publish applies one complete revision; restoration works; concurrent saves cannot silently overwrite changes.
- Owner changes to imagery, colors, content and section layout survive restart and produce the same output in preview and publication.
- Public channel/player aliases and verified custom domains continue to work without exposing unrelated channel data.
- Fresh installs and empty optional content remain attractive and functional. Existing station, stream and library records survive migration unchanged.
- Keyboard navigation, focus states, text contrast, reduced motion, responsive image crops and layouts pass review at 360px, 768px and 1440px. Core content and player links work without JavaScript.
- Focused homepage/CMS tests, existing player/domain/appearance/workspace regressions and migration upgrade/rollback rehearsal pass. Capture final desktop/mobile screenshots and check image payloads and layout stability.

This is one complete first release: station homepage, automated channel discovery, live public data, owner CMS, fresh-install defaults, demo configuration and removal of the previous marketing homepage.
