# Freo

Freo is an early-stage public open-source internet radio automation and station management project. Phase 1 provides a Flask/PostgreSQL web foundation, health checks, and a native Ubuntu deployment framework. It does **not** yet automate playout, nor install or integrate Liquidsoap or Icecast.

The supported installation target is Ubuntu 24.04 LTS with Python 3.12, Gunicorn, PostgreSQL, Nginx, and systemd. See [installation](docs/installation.md), [architecture](docs/architecture.md), and the mandatory [clean-install acceptance test](docs/clean-install-test.md). The separate fresh-VM acceptance test has not yet been performed, so third-party installation is not yet claimed as verified.

For local development, create a venv, install `requirements-dev.txt`, copy `.env.example` to `.env`, supply your own secret and database URL, and run `flask --app wsgi:app run`. Run `flask --app wsgi:app db upgrade` for migrations and `pytest` for tests. A domain and root access are not required for local development. See the installation guide for details.

Production uses Nginx on 80/443, private Gunicorn on 127.0.0.1:8000, and PostgreSQL locally. The web service runs as the restricted `freo` account. Credentials stay in an untracked, restricted `.env`. Future radio services will use separate identities and private control interfaces.

Roadmap: finish fresh-VM verification and release licensing; add station/media models and authentication; add a separate scheduler/control worker; then integrate Liquidsoap and Icecast. No license has been selected yet. An explicit license decision is required before broadly promoting Freo as reusable open-source software.
