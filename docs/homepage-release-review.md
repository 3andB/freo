# Freo homepage release review — 17 September 2026

The project homepage now introduces Freo through its actual music, programming, live broadcasting, statistics and listening workflows. It replaces the obsolete two-image landing page with an editorial product tour, a scheduling comparison, five capability tables, a technology table, setup guidance and a keyboard-accessible screenshot viewer.

## Product and visual review

The [feature audit](audits/2026-09-17-feature-homepage.md) and [design specification](homepage-redesign-plan.md) informed the content. Calendar, Blocks and Simple are distinguished from reusable Shows; optional Live Mic, sampled analytics, custom-domain setup and project maturity are explained alongside the relevant features. The project route no longer queries the station catalog. The directory and station-domain player routes retain their responsibilities.

The layout uses Freo's existing Day/Night palettes, record imagery, generous editorial spacing and responsive product frames. Thirteen real product views have matched Day/Night captures, including an authentic 390px player. The entire page, desktop/tablet/phone opening screens, gallery behavior and sample product screens were visually reviewed. Narrow tables have visible scroll instructions and keyboard-scrollable regions. Each screenshot has a direct image-link fallback, descriptive text, explicit dimensions and responsive WebP variants; noncritical images load lazily.

Run `venv/bin/python scripts/capture-homepage.py` to reproduce the imagery using a disposable SQLite catalog, generated tone audio and explicitly fictional Sunroom Radio observations. It never reads the installation environment or commands a production engine. Delivery assets and provenance are in `app/static/product/`; lossless masters default to `/tmp/freo-product-masters/`. The seed provides all analytics aggregation levels and refreshed demonstration observations. Fixed viewports prevent oversized captures from reflowing during screenshot capture.

## Verification

- 49 route, homepage, app, appearance and custom-domain tests passed.
- 96 statistics, listener experience, station settings, health, station API and Central integration tests passed. One optional check was skipped because the pinned external API contract source was not supplied.
- Seven public-player and appearance browser tests passed.
- Statistics dashboard/map and homepage audio-continuity browser checks passed.
- The final five-test homepage run passed: all asset/anchor checks, configured canonical origin, public-page behavior, responsive gallery/no-JavaScript behavior, and repeated workspace navigation with the same playing monitor audio.
- Both appearances were checked at 320, 390, 430, 768, 820, 1024, 1440 and 1920 CSS pixels. No page overflow, clipped headings/actions or overlapping header items were found. Menu Escape behavior, gallery Enter/Escape, theme switching and focus restoration passed. Homepage CSS is scoped for persistent workspace navigation and honors reduced motion.
- Python dependencies are consistent (`pip check`); JavaScript and provisioner syntax checks and `git diff --check` passed. Installation validation confirmed PostgreSQL at migration `b185c9a027d6`, healthy web/automation/ingest/statistics services and timers, private listeners and Icecast 2.5.

## Loading and accessibility

Homepage-specific CSS and JavaScript together are approximately 7 KB gzipped. A Lighthouse 12.8.2 mobile run against the uncompressed isolated Flask server identified a menu initialization layout shift and an unnamed compact menu button. Both were corrected; the subsequent measurement reported CLS 0 (previously 0.188). The public Nginx asset location now compresses text assets and caches release assets for one hour. Streaming responses are outside that location.

Laboratory scores depend on server/browser contention and simulated throttling; they are not field performance or a guarantee on physical devices. The deployed measurement and service verification follow.

## Deployed result

The full project update was committed as `f4cd306` and pushed to `origin/main`. Freo and the statistics worker restarted successfully at 04:36 UTC; Nginx reloaded its validated static-assets configuration. The database was already at the current migration, so no schema change was needed. Existing station playout remained running.

The production HTTPS homepage returns the new content, all 14 screenshot placements and the corrected accessible menu. CSS delivery returns `Content-Encoding: gzip` with a one-hour cache lifetime. Full installation validation passed again after restart. Reading the public `/stream/freo-demo` endpoint returned HTTP 200, `audio/mpeg`, and 8,192 audio bytes.

Lighthouse 12.8.2 measured `https://freo.world/` from this server with its default mobile profile (412 × 823 CSS pixels, simulated mobile network/CPU throttling). The [machine-readable measurement](audits/2026-09-17-homepage-lighthouse.json) records the browser, profile, timestamps and metrics.

| Measure | Deployed result |
| --- | --- |
| Performance | 95 / 100 |
| Accessibility | 100 / 100 |
| Best practices | 100 / 100 |
| SEO | 100 / 100 |
| First contentful paint | 2.0 s |
| Largest contentful paint | 2.1 s |
| Cumulative layout shift | 0 |
| Total blocking time | 0 ms |
| Initial measured transfer | 166 KiB |

The mobile laboratory targets in the design specification were met. Native-device Safari testing and real-user field data are outside this Chromium-based release verification.
