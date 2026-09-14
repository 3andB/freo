# Installation and deployment

## Production target

Ubuntu 24.04 LTS only. Clone the public repository and run `sudo ./scripts/install.sh` from its root. The installer copies named release files to `/opt/freo`, creates a `freo` system account, installs Python and radio packages, provisions a local PostgreSQL role/database on a fresh install, installs version-controlled units and an HTTP Nginx site, and validates the result. The installer requires internet access for apt and pip. Do not rely on this path as verified for others until `clean-install-test.md` has been executed on a separate VM.

For an IP-only install, leave `FREO_DOMAIN` unset. For an HTTP domain install, set `FREO_DOMAIN=radio.example.com` when running the installer, after DNS points at the server. For HTTPS, also set `FREO_ENABLE_HTTPS=1` and `FREO_CERTBOT_EMAIL=operator@example.com`; Certbot will obtain a certificate and update the Nginx site. DNS, inbound 80/443, and a reachable public IP are prerequisites for that step. Certbot is optional. The checked-in Nginx template is HTTP only; it contains no certificate path. An existing Nginx site is retained rather than overwritten.

The installer supports reruns: it does not recreate the database, reset role passwords, or overwrite `.env`. It backs up a changed systemd unit before replacement. It updates named application files and Python dependencies, then restarts Freo and the test engine. Existing OS packages are not upgraded automatically. Back up the database and site configuration before upgrades. The installer is not an uninstaller; rollback uses the prior application release, the backed-up unit, and the operator's database backup. Do not remove a database automatically.

`/opt/freo` stays root-owned and readable by `freo`. `/opt/freo/.env` is `root:freo` mode `0640`; it contains generated secrets on a fresh install. `/var/lib/freo` is owned by `freo` with traversal-only access for the separate playout account; its child directories remain restricted. systemd sends stdout/stderr to journald. No broad sudo privilege is granted. PostgreSQL keeps Ubuntu's local exposure defaults; the installer does not rewrite `pg_hba.conf` or `listen_addresses`. Confirm actual listeners and firewall policy on the target host.

On an existing deployment with an `.env` but no `SECRET_KEY`, add a cryptographically random value privately before restarting the new service. The installer refuses to overwrite such a file. Existing Certbot-managed Nginx sites should be retained and validated with `nginx -t` and HTTP/HTTPS requests.

## Development

Use Python 3.12 and a local PostgreSQL database, or SQLite for route-only tests. Run `python3 -m venv .venv`, `.venv/bin/pip install -r requirements-dev.txt`, copy `.env.example` to `.env`, and replace every active placeholder. Set `FLASK_ENV=development`; run `.venv/bin/flask --app wsgi:app db upgrade`, `.venv/bin/flask --app wsgi:app run`, and `.venv/bin/pytest`. Do not use a production database in tests. SQLite test success does not validate PostgreSQL behavior.

The migration directory is initialized but has no revision or schema yet. `flask db heads` and `flask db current` are empty until the first model migration. Creating the first revision must be reviewed before applying it to production data.

## Phase 2 radio packages

The installer now installs Ubuntu's `liquidsoap` and `icecast2` packages, records installed versions, creates the non-login `freo-playout` account, renders restricted radio configs, installs native Icecast/playout units, and adds an exact test-mount Nginx snippet. It does not reset existing radio credentials on rerun. Runtime config changes are backed up before replacement. An existing customized Nginx site is retained; its operator must include `/etc/nginx/snippets/freo-stream.conf` in the appropriate public server block. The existing Freo production site uses that include in its Certbot HTTPS server. The generated default HTTP site includes it automatically.

For radio validation, run `sudo ./scripts/validate-install.sh`. Confirm the direct Icecast backend listens on `127.0.0.1:8001`, not a public address. Check the public URL with a media player or bounded byte read, and consult [radio-engine.md](radio-engine.md). The fuller clean-server installation remains unverified until the separate VM acceptance test is executed.
