# Freo

Freo is an early-stage public internet radio automation and station management project. Phase 3 adds PostgreSQL-backed stations, one isolated Liquidsoap process per managed station, a root-run administration CLI, and read-only station APIs. The system still plays generated test audio. It has no music library, scheduling, clocks, carts, live assist, or production programming yet.

The live [diagnostic stream](https://freo.world/stream/freo-test) tests the Liquidsoap → Icecast → Nginx engine. The separate [database-managed Freo Demo stream](https://freo.world/stream/freo-demo) proves station provisioning and per-station runtime. Station mutations and service controls are **CLI-only** until a proper authenticated control boundary exists.

The stack is Python 3.12, Flask, Gunicorn, PostgreSQL, Nginx, systemd, Liquidsoap, and Icecast on Ubuntu 24.04. See [stations](docs/stations.md), [radio engine](docs/radio-engine.md), [architecture](docs/architecture.md), [installation](docs/installation.md), and the [fresh-VM acceptance test](docs/clean-install-test.md).

The installer deploys the fuller stack but has **not** been tested on a separate fresh Ubuntu VM. Public one-command installation is not yet claimed as supported. Local development needs a Python 3.12 venv, `requirements-dev.txt`, a private `.env`, and `flask --app wsgi:app db upgrade`; run `pytest` for tests. Root, a domain, and radio services are not required for unit tests.

No license has been selected. The owner must choose one before broadly promoting reuse as open-source software.
