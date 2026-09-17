# Freo project homepage redesign plan

Status: implemented, 17 September 2026. The specification below records the design decisions; implementation and validation are documented in [homepage release review](homepage-release-review.md). Evidence: [feature and design audit](audits/2026-09-17-feature-homepage.md).

## Objective

Make the homepage the definitive introduction to Freo: a self-hosted internet radio platform that connects music, programming, live presentation, listening and station insight. A visitor should understand what Freo is immediately, see the real product in both appearances, explore its capabilities, and find a clear route to evaluation/setup.

The audience is independent station owners, music curators, DJs, community broadcasters and technically capable operators evaluating the project. Existing operators retain sign-in and listeners retain the station directory.

## Creative direction

**Concept: an independent radio studio, beautifully in control.** Retain Freo's record/deck character and Miami palettes, with a more deliberate editorial layout and much stronger product evidence.

- Day: warm off-white canvas, clean surfaces, deep ink typography, seafoam/teal accents and restrained coral/lavender details.
- Night: midnight blue and deep teal surfaces, warm white type, mint controls and restrained broadcast-status color.
- Use existing semantic `--theme-*` tokens and the existing Day/Night preference. Day remains the default; an explicit selection persists across navigation and tabs.
- Large, tightly composed headings; comfortable body text; small monospace labels for technical details; generous spacing and fine borders. Use the existing system typography initially so the page has no external font dependency.
- Give screenshots visual priority. Flat, crisp frames and subtle shadows preserve interface legibility. Record grooves, signal paths and schedule lines can appear as restrained CSS/SVG decoration.
- Motion is limited to short transitions and optional small reveals. Content is visible without animation or JavaScript. Respect reduced motion; do not autoplay audio or carousel slides.
- Keep the Freo wordmark. The premium impression comes from hierarchy, spacing, imagery and detail, not a separate brand system.

## Proposed opening copy

Eyebrow: **SELF-HOSTED INTERNET RADIO**

Headline: **The whole station. In your hands.**

Supporting copy: **Build your music library, shape your schedule, take the decks, and understand your audience. Freo brings the tools behind your station into one connected workspace.**

Primary action: **Explore Freo** → product tour. Secondary action: **Read the setup guide** → installation documentation. A smaller **Listen to a station** link opens the public directory. Existing operators use **Open studio / Sign in** in navigation.

Use a current DJ Booth screenshot as the main image, with the matching Day/Night asset and small captions pointing to decks, carts and live controls. Below it, a concise capability strip: **Music · Playlists · Scheduling · Live broadcasting · Listener experience · Statistics**. These are navigation labels, not invented adoption metrics.

## Page structure

| Order | Section | What it communicates | Visual / interaction |
| --- | --- | --- | --- |
| 1 | Compact project header | Freo, Product, Features, Technology, Setup, Listen, GitHub and operator sign-in | Desktop navigation; compact tablet/mobile menu; visible Day/Night control |
| 2 | Hero | Product category, central promise, evaluation/setup actions | Large current booth screenshot; theme-matched; one clear focal point |
| 3 | One connected station | Import → organize → schedule → broadcast → understand | Simple accessible workflow in HTML/CSS; anchors to the relevant sections |
| 4 | Music and playlists | Artist/album/song library, folder import, metadata/artwork, waveform and loudness tools; Straight/Random playlists and bulk organization | Large library and playlist images with short capability lists |
| 5 | Schedule your way | Calendar, Blocks and Simple; reusable Shows; default playlist; recurrence; Events | Scheduler image, Show editor detail, and a three-mode comparison table |
| 6 | Take the booth | Auto, two-deck DJ Booth, optional Live Mic; private preview, Take Air fades, monitoring and 12 shared cart/ID slots | Booth close-up with Auto/DJ/Live Mic tour selectors; cart and microphone details |
| 7 | Know your station | Audience and approximate geography, confirmed plays, listener preferences, transfer/storage and reliability | Statistics overview/map pair; accurate metric descriptions; explicitly labeled demo data |
| 8 | Give listeners a home | Branded player, artwork/covers, schedule, announcements, socials, ads, votes/private comments and custom domains | Desktop player plus authentic phone capture; link to real directory |
| 9 | Capability tables | Complete feature coverage, including imaging, events/sequences, traffic, multi-channel sharing and operational tools | Grouped semantic tables; concise benefit, included tools and relevant qualification |
| 10 | Built to broadcast | Self-hosted architecture, dedicated workers, independent station engines, persistent programming/history and local analytics | Small accessible architecture diagram and technology/responsibility table |
| 11 | Explore the project | Setup requirements, project maturity, source/docs, useful FAQ | Clear install-status note, documentation links and final setup CTA |
| 12 | Footer | Freo identity and useful destinations | Source, docs, listen, sign-in and existing reporting route where appropriate |

The tour uses feature detail sections as its screenshot gallery, avoiding a second long gallery that repeats every image. Provide a compact screen selector near the hero and an enlarged-image viewer from each product image. Essential feature content remains in the document and searchable even when JavaScript is disabled.

## Required feature tables

### Scheduling comparison

| Mode | Best suited to | What to show |
| --- | --- | --- |
| Calendar | Programming tied to dates and times | Day/Week/Month/Agenda, recurring placements, individual/series changes, Shows and music sources |
| Blocks | Repeatable daily formats | 24-hour compositions, weekday assignments, rolling daily patterns and selected dates |
| Simple | Continuous playback from a chosen source | Repeat a Show, playlist, artist, album, category or song, with explicit source changes |

Below the table: Shows are reusable building blocks; Events add scheduled moments across modes; the default playlist fills unassigned/unavailable periods when configured and playable. Avoid conflating schedule Blocks with event sequences.

### Complete capabilities

Group rows under Music & playlists; Programming; Booth & live audio; Audience & listening; Station operations. Columns: **Capability / What Freo includes / Notes**. Use real feature descriptions rather than rows of unexplained checkmarks. Include the full inventory from the audit, with secondary functions summarized compactly and linked to their documentation.

Keep qualifications close to affected rows: optional Live Mic service, operator-configured custom-domain HTTPS, advanced traffic without invoicing, and separation rules belonging to the rotation engine. Do not invent pricing tiers or competitor comparisons.

### Technology

| Layer | Technology | Benefit to explain |
| --- | --- | --- |
| Web workspace | Python, Flask, Gunicorn | Browser-based management and authenticated control requests |
| Station state | PostgreSQL | Library, schedules, durable command intent and confirmed history |
| Audio engine | Liquidsoap, one process per managed station | Per-station playback, transitions, carts, microphone integration and fallback |
| Stream delivery | Icecast and Nginx | Public listener streams with private engine/admin services |
| Media preparation | FFmpeg/ffprobe and dedicated ingest worker | Validated import, metadata and background analysis |
| Operations | Ubuntu 24.04 and systemd | Explicit service lifecycle and separate workers |
| Optional live input | WebRTC/Opus and aiortc gateway | Browser microphone or OS-recognized USB mixer input |

Architecture diagram: browser workspace → Flask → PostgreSQL → automation worker → station Liquidsoap → Icecast → Nginx → listeners. Show ingest and statistics as separate supporting paths, and optional microphone input entering the audio engine. Provide an equivalent text description.

## Day and Night screenshot production

Capture the running application against a disposable, seeded demonstration database. Use coherent fictional station/show/artist names and generated or appropriately licensed audio/artwork. Do not manipulate UI controls or paint nonexistent capabilities into screenshots. Seeded analytics and playback observations must be identified as demonstration data in the page captions.

| Screen | Required content | Appearances / formats |
| --- | --- | --- |
| DJ Booth | One live deck, one prepared deck; readable transport; fade control; carts in a supporting detail | Day + Night desktop masters and detail crops |
| Live Mic | Input test/gain/mute and Go Live workflow, with valid demo readiness if shown | Day + Night detail capture |
| Music | Populated library with artwork, categories/tags, waveform/preview detail | Day + Night desktop |
| Playlists | Named playlist with populated ordered songs and editing controls | Day + Night desktop |
| Calendar | Current scheduler with a convincing week of varied programs and source browser | Day + Night desktop |
| Shows / Blocks | Reusable composition timeline and 24-hour programming example | Day + Night desktop/detail |
| Statistics | Audience curve, local world map, music/feedback/resource examples | Day + Night overview/map; caption “Demonstration data” |
| Public player | Branded station, current track, schedule and listener controls | Day + Night desktop and native phone viewport |

Capture matched pairs with identical data, viewport, selected period and scroll position so switching appearance compares the design directly. Baseline desktop capture: 1600×1100 CSS pixels, with higher-resolution masters where feasible; player phone capture: 390×844. Wait for fonts, images, maps and asynchronous data before capture. Preserve source screenshots separately from optimized delivery assets.

On the homepage, screenshots follow the global Day/Night choice. The enlarged viewer also offers labeled Day/Night controls, uses the same preference, supports Escape and keyboard navigation, and returns focus to its trigger. A normal image link provides a no-JavaScript fallback. Do not implement a before/after drag handle as the only way to compare skins.

Export responsive WebP versions, with PNG fallback where useful for interface text. Use explicit width/height, meaningful alt text, `srcset`/`sizes`, eager/high-priority loading for the single hero image, and lazy loading below the fold. Load only the needed theme/size initially; full-size captures load on demand. Cropping/resizing is mechanical asset preparation, not a generative image task.

## Responsive and accessible behavior

| Viewport | Layout decisions |
| --- | --- |
| Desktop, 1200px+ | Approx. 1280px content width; composed two-column hero; large product sections; two/three-column supporting grids |
| Tablet, 768–1199px | Content-led header collapse; fewer columns; full-width screenshots; comfortably sized gallery controls; no hover-only interactions |
| Mobile, 320–767px | Single-column reading order; compact header; visible product identity and CTA early; full-width actions when needed; authentic phone screens and legible detail crops |

Use content-based breakpoints rather than assuming a device from its width. Test 320, 390, 430, 768, 820, 1024, 1440 and 1920 pixels, including tablet landscape and long labels.

Feature tables must retain captions and header associations. At narrow widths, keep two-column tables wrapping naturally; place wider comparisons in clearly labeled, keyboard-scrollable regions with visible overflow cues. Essential notes must remain readable without opening a dialog. Never hide page overflow to conceal a broken layout.

Provide a skip link, one H1, logical heading order, visible focus, descriptive controls, sufficient contrast and approximately 44px touch targets. Verify keyboard menu/gallery operation, focus restoration, 200% text zoom, reduced motion, no-JavaScript content, and failed-image behavior. Preserve existing monitor playback across theme switches and navigation.

## Technical implementation scope

1. Replace `app/templates/home.html` with the new project narrative, feature tables and progressive gallery markup. Use partials if they improve readability; keep claim text easy to review against the audit.
2. Add homepage-scoped `app/static/home.css` and small `app/static/home.js` only for menu/gallery interactions. Reuse theme tokens and `_appearance.html`; avoid a framework or third-party carousel dependency.
3. Add optimized captures under `app/static/product/`, plus a repeatable isolated capture script/fixture and an asset manifest recording screen, theme, viewport and demo-data origin.
4. Prefer the existing template header override for the project header. Make only narrow shared-template changes if needed for footer/SEO blocks. Do not disturb admin/player styles or the persistent monitor mount.
5. Integrate with `workspace.js`: styles can persist after navigation and page scripts run again. Scope every selector to the homepage, register disposable event listeners through the existing page lifecycle, and verify forward/back navigation has no duplicate handlers or audio interruption.
6. Add a useful title, description, canonical URL derived from configured installation origin, and social-preview metadata using a real product image. No invented rating, customer count, price or software license in structured metadata. Confirm direct page requests and workspace navigation behavior.
7. Make the project homepage primarily static/server-rendered. Link to `/stations` for live listening. If retaining featured station cards, cap the list, align lifecycle filtering with the directory, and handle zero stations honestly. Custom station domains must continue to show their assigned player at `/`.

No database migration or audio-engine change is required for the homepage. Existing statistics and deployment edits in the working tree must remain intact.

## Implementation order and review gates

1. **Content:** turn the audit into final section copy and tables, with every claim traced to implemented behavior. Resolve outdated names and optional-feature labels before design polishing.
2. **Screenshots:** build the consistent demo fixture and capture all required Day/Night pairs. Review every image for legibility, current navigation, accurate state and exposed private data.
3. **Desktop composition:** implement header, hero and the Music → Schedule → Booth → Statistics → Listener narrative, followed by capability/technology tables and setup.
4. **Responsive behavior:** compose tablet/mobile layouts, usable tables, detail crops, accessible navigation/gallery and complete Day/Night styling.
5. **Verification:** run focused route/theme/homepage-browser checks; verify public/custom-domain routing and persistent audio when shared code changes; inspect screenshots at the target widths; check links, console, assets, no-JavaScript rendering and loading performance.
6. **Design review:** assess whether a first-time visitor understands the product in the first screen, can find every major capability, can actually read its screenshots, and sees one coherent Freo identity across desktop/tablet/mobile and both skins. Fix issues before presenting the implementation.

## Acceptance criteria

- Every capability group in the audit has an intentional location on the homepage or a clearly labeled advanced-capability row with documentation.
- The current DJ Booth, scheduler, playlists, statistics, music library and player are represented by real current screenshots; Day and Night are both usable and visually reviewed.
- Features, scheduling modes and technology have substantive tables, readable on narrow screens.
- All visitor CTAs resolve to useful public content or clearly labeled authentication; no placeholder links, fake signup, fictional testimonials or inflated metrics.
- No page-level horizontal overflow at the target widths, including 320px; no clipped headings, inaccessible menus, unreadable CTA labels or screenshots presented as interactive controls.
- Keyboard and touch use work; reduced motion is respected; essential content is available without JavaScript.
- Existing theme preference and active monitor audio survive navigation; directory/player/custom-domain behavior remains correct.
- Set performance targets of mobile Lighthouse performance/accessibility ≥90, LCP ≤2.5s and CLS ≤0.1 in a documented local test profile. Treat these as targets, measure them, and report the environment/results rather than claiming field performance. Aim for ≤1MB initial compressed transfer and ≤20KB compressed homepage-specific JS/CSS, with noncritical images deferred.
- Setup copy accurately states the project's maturity and links to installation status. No claim of a selected open-source license, one-command production readiness, unlimited scale or guaranteed broadcast uptime.

## Questions resolved by the plan

“Day and night screenshots” means real paired screenshots of Freo's existing two appearances, integrated with the site's switcher. “High end, sleek” means a refined evolution of Freo's own visual language. The project homepage remains on the main installation host; station custom domains retain the listening experience. The audit and specification informed the implemented homepage and its release review.
