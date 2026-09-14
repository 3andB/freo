# Freo

Freo is an early-stage public internet radio automation and station management project. Freo now has PostgreSQL-backed stations, one isolated Liquidsoap process per managed station, and a station-scoped media library. Root-run CLI ingestion probes and stores MP3 audio safely; approved tracks play through Liquidsoap with a generated fallback tone. It has no scheduling, clocks, carts, live assist, web upload, or production programming yet.

The live [diagnostic stream](https://freo.world/stream/freo-test) tests the Liquidsoap → Icecast → Nginx engine. The separate [database-managed Freo Demo stream](https://freo.world/stream/freo-demo) proves station provisioning and real library playback. Station and media mutations are **CLI-only** until a proper authenticated control boundary exists.

The stack is Python 3.12, Flask, Gunicorn, PostgreSQL, Nginx, systemd, Liquidsoap, Icecast, and ffprobe on Ubuntu 24.04. See [media library](docs/media-library.md), [stations](docs/stations.md), [radio engine](docs/radio-engine.md), [architecture](docs/architecture.md), [installation](docs/installation.md), and the [fresh-VM acceptance test](docs/clean-install-test.md).

The installer deploys the fuller stack but has **not** been tested on a separate fresh Ubuntu VM. Public one-command installation is not yet claimed as supported. Local development needs a Python 3.12 venv, `requirements-dev.txt`, a private `.env`, and `flask --app wsgi:app db upgrade`; run `pytest` for tests. Root, a domain, and radio services are not required for unit tests.

No license has been selected. The owner must choose one before broadly promoting reuse as open-source software.
