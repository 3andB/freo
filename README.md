# Freo

[Radio Station Operations](docs/operations-navigation.md): **Admin → Overview** covers all stations, system health, freo.live connection, and aggregate statistics. Use the sidebar station selector and **Switch** to open an individual station’s controls. Website, player settings, feedback, installation, and audit tools are available in the operations context.

[Station website and Website CMS](docs/station-website.md): every installation opens with a customizable station homepage, automatic channel cards, real library counts, published schedules, images, colors and draft/publish controls. Manage it in **Admin → Website**.

[Central API integration](docs/central-api-integration-plan.md) covers installation registration, permanent station UUIDs, aggregate hourly reports, cached licensing, setup and recovery.

[Copyright identification and DMCA reporting](docs/copyright-and-dmca.md) documents permanent public Track IDs, optional ISRC metadata, private copyright reports, admin review, and upgrade instructions.

[Player settings and listener feedback](docs/player-and-listener-experience.md) add station messages, cover art, social links, published Day/Week/Month schedules, top/bottom ad slots, and song votes with private comments. The public player uses a responsive DJ-inspired record design.

Phase 9 adds first-class station imaging and carts: private validated uploads, station-scoped groups, exact-cart and group clock slots, and confirmed imaging history. See [Imaging and carts](docs/imaging.md). The authenticated [DJ Booth](docs/live-assist.md) provides two modes: focused Auto and paired-deck DJ Booth; observed Now Playing and Up Next; persistent cue; in-booth music/category browsing; twelve assignable cart/identity controls; worker-observed Program and optional browser Monitor meters; fixed Skip/Fade; and worker-mediated crossfade takeover. Phase 11 adds [timed events](docs/timed-events.md): one-time and weekly events, HARD/SOFT/NON_INTERRUPTING behavior, timing windows, occurrence history, permitted automated-music interruption, and booth event awareness.

Freo is an early-stage public internet radio automation and station management project. Freo has PostgreSQL-backed stations, one isolated Liquidsoap process per managed station, and an Artist → Album → Song catalog with optional availability across all channels. Safe ingestion, categories, rotations, artist/track separation, clocks, timed events, stopsets, traffic planning, Live Assist, and confirmed playback history feed a dedicated non-root automation worker. It does not claim frame-accurate timing, studio microphone/source switching, a cue bus, arbitrary queue surgery, fade-to-time, satellite joins, or accounting.

The live [diagnostic stream](https://freo.world/stream/freo-test) tests the Liquidsoap → Icecast → Nginx engine. The separate [database-managed Freo Demo stream](https://freo.world/stream/freo-demo) proves station provisioning and real library playback. The public homepage and player use real stream and station data. The authenticated `/admin` dashboard provides an Artist → Album → Song music library, batch and folder ingestion, background audio analysis, station Category assignment, enable/disable, verification, and an audit trail. Categories, rotations, clocks, weekly assignments, and station timezone can be edited in authenticated admin pages. [Playlists](docs/playlists.md) provide ordered or random song lists, Music membership bubbles, and calendar scheduling; categories, artists, and albums can be copied into a playlist. Station creation and deletion are available in Admin → Overview and the server CLI, with a configurable default limit of three channels. Fresh installs start with zero stations. See [station lifecycle and shared music](docs/channel-management.md). Broadcast start/stop and automation enable/disable remain CLI operations. See [UI and account setup](docs/ui.md) and [programming controls](docs/programming-ui.md).

The stack is Python 3.12, Flask, Gunicorn, PostgreSQL, Nginx, systemd, Liquidsoap, Icecast, and ffprobe on Ubuntu 24.04. Timed events can execute durable [event blocks and stopsets](docs/event-blocks.md): ordered Track/ImagingAsset snapshots that exclude normal music between items. Authenticated [traffic planning](docs/traffic.md) manages advertisers, campaigns, commercial creatives, stopset inventory, finalized daily logs, as-run reconciliation, and makegood relationships. Accounting and invoicing are not included. See [clocks](docs/clocks.md), [scheduling](docs/scheduling.md), [rotations](docs/rotations.md), [automation](docs/automation.md), [media library](docs/media-library.md), [stations](docs/stations.md), [radio engine](docs/radio-engine.md), [architecture](docs/architecture.md), [installation](docs/installation.md), and the [fresh-VM acceptance test](docs/clean-install-test.md).

The installer deploys the fuller stack but has **not** been tested on a separate fresh Ubuntu VM. Public one-command installation is not yet claimed as supported. Local development needs a Python 3.12 venv, `requirements-dev.txt`, a private `.env`, and `flask --app wsgi:app db upgrade`; run `pytest` for tests. Root, a domain, and radio services are not required for unit tests.

No license has been selected. The owner must choose one before broadly promoting reuse as open-source software.

### Custom station domains

See [custom domain setup](docs/custom-domains.md) for verified station domains,
DNS instructions, and HTTPS deployment with the existing Nginx/Certbot setup.

Audio upload formats, stream quality, processing, and deployment: [Audio imports and station sound](docs/audio-import-and-processing.md).
