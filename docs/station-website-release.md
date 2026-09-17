# Station website release — 17 September 2026

The installation homepage is now a station website with a hero photograph, separate station image, identity/story, automatic channel cards and player links, fresh broadcast observations, real library/artist/channel totals, optional 30-day play counts, published schedules, dated announcements and contact/social information.

Admin → Website provides images, curated/custom day/night palettes, typography, image focal position/shading, section visibility/order, channel ordering/featuring, metadata, saved drafts, desktop/mobile preview, atomic publication and restoration from six retained versions. Draft content/assets require authentication. Updates use revision comparisons to reject concurrent overwrites.

The old project homepage, product gallery, screenshot assets, capture script and dedicated marketing documentation/audits were removed. `/stations` redirects to the homepage's channel section. Existing channel player aliases and verified custom-domain roots remain functional. Website style is independent of workspace appearance. Existing persistent monitor navigation is preserved.

Fresh installations use neutral station defaults and an honest empty state. freo.world's **Freo Radio** identity, headline and story were published as installation data using the same validation/publication service; they are not hardcoded into the distributable defaults. Its two existing channel descriptions were updated from test placeholders. No station lifecycle, audio configuration, song library or scheduling data was changed.

## Verification

- Combined focused regression run: **162 passed, 1 skipped**, covering the homepage, web routes, app setup, station domains, player settings, appearance, station settings, channel sharing, lifecycle, station experience and central integration. Tests used `FREO_ENV_FILE=/dev/null` to isolate installation configuration.
- Expanded homepage suite after adding real image-decoder and custom-domain asset checks: **9 passed**.
- Chromium homepage/editor, custom-domain, player and appearance suites: **10 passed**. Includes 360–1440px homepage layouts, both themes, working links without JavaScript, a mobile editor layout fix, private previews, publication and monitor persistence.
- Disposable PostgreSQL: full upgrade to the previous head, website upgrade, downgrade/re-upgrade and retained station/stream verification passed.
- Concurrent first publications against PostgreSQL: one HTTP 303 success and one HTTP 409 conflict; no lost update.
- Bundled hero WebP payloads: about 132 KB desktop and 40 KB small. Original prompt/provenance is in the owner guide.

## Deployment

Database and prior committed application backup: `/var/backups/freo/website-20260917T132920Z` (`database.dump` verified with `pg_restore --list`, and `application-before.tar`). Applied migration `d91f3a26b807`, published Freo Radio content, and restarted only `freo.service`. Broadcast engines were not restarted.

At publication, the website reported **6 available songs, 3 catalog artists and 2 channels**, calculated from actual station data.

For rollback, restore the previous application together with the database backup, or export website content before downgrading the three website tables. Website publication history is the normal way to undo content changes without a deployment rollback.

Live HTTPS smoke checks passed for the homepage, theme stylesheet, bundled photograph, player, login-gated Website editor and readiness endpoint. A bounded stream read confirmed audio delivery after rollout. Anonymous Chromium checks found both channel links, fully loaded images, no horizontal overflow and no severe browser errors at 390px/1440px in both appearances. Final captures: [desktop](audits/station-website/desktop.png) and [mobile](audits/station-website/mobile.png).

## Navigation correction

Fixed the top section links blinking and jumping to the top. Native fragment clicks emit `popstate`; the shared workspace previously treated those events as page navigation and replaced the document. It now leaves history changes within the rendered page to the browser and retains requested section fragments when navigating between pages. The script URL was versioned to refresh browser caches. Targeted Chromium tests passed for desktop/mobile section links, Back/Forward, cross-page section destinations and persistent monitor playback (2 passed).
