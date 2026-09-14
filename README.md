# Freo

Freo is an early-stage public internet radio automation and station management project. Phase 2 now runs a **generated test stream** through Liquidsoap, Icecast, and Nginx at [https://freo.world/stream/freo-test](https://freo.world/stream/freo-test). It does not yet provide scheduling, library management, station administration, or production programming.

The stack is Python 3.12, Flask, Gunicorn, PostgreSQL, Nginx, systemd, Liquidsoap, and Icecast on Ubuntu 24.04. Freo Web/API runs as `freo`; test playout runs as `freo-playout`; Icecast runs as its package-managed account. Only Nginx is public by default. See [radio engine](docs/radio-engine.md), [architecture](docs/architecture.md), [installation](docs/installation.md), and the [fresh-VM acceptance test](docs/clean-install-test.md).

The installer has been updated for the fuller stack, but it has **not** been verified on a separate fresh Ubuntu VM. Public one-command installation is therefore not yet claimed as supported. The production server validates the service configuration and stream only.

For development, create a Python 3.12 venv, install `requirements-dev.txt`, copy `.env.example` to `.env` and replace placeholders, then run `flask --app wsgi:app run`, `flask --app wsgi:app db upgrade`, and `pytest`. Root, a domain, and the radio services are not required for unit tests.

Roadmap: fresh-VM acceptance and licensing; station and mount management; a separate scheduling/control worker; library and automation features. No license has been selected. The owner must choose one before broadly promoting reuse as open-source software.
