> Freo automatically contacts api.freo.live to identify this installation and send
> its version, machine facts, channel metadata, and hourly listener/library totals.
> No email or Freo Live account is required for Community. Listener identities,
> listener IP addresses and music metadata are not sent. Public directory listing
> requires a separate opt-in. See [reporting and recovery](central-api-integration-plan.md).

# Installation and deployment

For the staged signed 0.3.0 installer, begin with [stable installation](stable-installation.md).
Publication is separate from package preparation. Historical candidate instructions
remain in [candidate installation](install-candidate.md).
For existing installations, use [recovery and upgrades](recovery-and-upgrades.md) for existing
installations. The installer now refuses existing state before making changes;
the historical rerun-based upgrade instructions below are superseded by the
dedicated verified updater.

## Production target

Ubuntu 24.04 LTS x86_64 only. Prefer the verified signed archive; source developers may clone the canonical 3andB/freo repository and run `sudo ./scripts/install.sh` from its root. The installer copies named release files to `/opt/freo`, creates a `freo` system account, installs Python and radio packages, provisions a local PostgreSQL role/database on a fresh install, installs version-controlled units and an HTTP Nginx site, and validates the result. The installer requires internet access for apt and pip. Do not rely on this path as verified for others until `clean-install-test.md` has been executed on a separate VM.

For an IP-only install, leave `FREO_DOMAIN` unset. For an HTTP domain install, set `FREO_DOMAIN=radio.example.com` when running the installer, after DNS points at the server. For HTTPS, also set `FREO_ENABLE_HTTPS=1` and `FREO_CERTBOT_EMAIL=operator@example.com`; Certbot will obtain a certificate and update the Nginx site. DNS, inbound 80/443, and a reachable public IP are prerequisites for that step. Certbot is optional. The checked-in Nginx template is HTTP only; it contains no certificate path. An existing Nginx site is retained rather than overwritten.

The installer is for fresh installations. It refuses an existing environment,
release pointer or media directory before changing packages, files, services or
the database. Existing installations use the separate signed-release updater,
which preserves their database/media and requires a verified backup/restore
before migration. Do not rerun the installer as an upgrade mechanism.

`/opt/freo` stays root-owned and readable by `freo`. `/opt/freo/.env` is `root:freo` mode `0640`; it contains generated secrets on a fresh install. `/var/lib/freo` is owned by `freo` with traversal-only access for the separate playout account; its child directories remain restricted. systemd sends stdout/stderr to journald. No broad sudo privilege is granted. PostgreSQL keeps Ubuntu's local exposure defaults; the installer does not rewrite `pg_hba.conf` or `listen_addresses`. Confirm actual listeners and firewall policy on the target host.

On an existing deployment with an `.env` but no `SECRET_KEY`, add a cryptographically random value privately before restarting the new service. The installer refuses to overwrite such a file. Existing Certbot-managed Nginx sites should be retained and validated with `nginx -t` and HTTP/HTTPS requests.

## Development

Use Python 3.12 and a local PostgreSQL database, or SQLite for route-only tests. Run `python3 -m venv .venv`, `.venv/bin/pip install -r requirements-dev.txt`, copy `.env.example` to `.env`, and replace every active placeholder. Set `FLASK_ENV=development`; run `.venv/bin/flask --app wsgi:app db upgrade`, `.venv/bin/flask --app wsgi:app run`, and `.venv/bin/pytest`. Do not use a production database in tests. SQLite test success does not validate PostgreSQL behavior.

The migration directory includes station and media revisions. Check `flask db current` against `flask db heads` after setup.

After the initial development migration, also run
`.venv/bin/flask --app wsgi:app settings import-environment`. Production fresh
installation invokes this automatically before starting the web application.

## Phase 2 radio packages

The installer installs Ubuntu's `liquidsoap` and Xiph's official Ubuntu 24.04 `icecast2` 2.5 packages, records installed versions, creates the non-login `freo-playout` account, renders restricted radio configs, installs native Icecast/playout units, and adds an exact test-mount Nginx snippet. Xiph's repository uses a dedicated signing key, with package preferences limited to Icecast 2.5 and its libigloo dependency. Existing Icecast installations are explicitly upgraded to 2.5 because the trusted-proxy configuration requires it; this can interrupt streams. See [Icecast upgrade and rollback](icecast-upgrade.md). It does not reset existing radio credentials on rerun. Runtime config changes are backed up before replacement. An existing customized Nginx site is retained; its operator must include `/etc/nginx/snippets/freo-stream.conf` in the appropriate public server block. The existing Freo production site uses that include in its Certbot HTTPS server. The generated default HTTP site includes it automatically.

For radio validation, run `sudo ./scripts/validate-install.sh`. Confirm the direct Icecast backend listens on `127.0.0.1:8001`, not a public address. Check the public URL with a media player or bounded byte read, and consult [radio-engine.md](radio-engine.md). The fuller clean-server installation remains unverified until the separate VM acceptance test is executed.

## Phase 3 station runtime

Provisioning deploys the station/stream migration, `freo-playout@.service`, its instance validator, a controlled Liquidsoap template, and an Nginx exact-route include directory. It does **not** create demo stations on a normal public install. After installation, an administrator may use the root-run [station CLI](stations.md) to create and start a station. Only started instances are enabled for boot; stopped stations remain in PostgreSQL without a running playout process. Existing customized Nginx sites need `include /etc/nginx/snippets/freo-stations/*.conf;` inside the intended public server block. The default generated site includes it.

## Phase 4 media

Provisioning installs Ubuntu `ffmpeg` (including `/usr/bin/ffprobe`) and creates root-owned, `freo-playout`-readable `/var/lib/freo/media` and `/var/lib/freo/playlists` (mode 0750). It applies the additive Track migration. It does not install demo audio or create library rows. The administrator ingests files through the [media CLI](media-library.md). The complete backup set now includes PostgreSQL, `/etc/freo`, and `/var/lib/freo/media`; playlists can be regenerated from accepted DB records.

## Phase 5 automation

Provisioning creates the non-login `freo-automation` account, grants it only the `freo` environment-read and `freo-playout` socket/media-read groups, deploys `freo-automation.service`, and applies additive category/rotation/history migrations. The web `freo` user is not in the playout group. No demo categories, rotation, or automated mode are created on a normal install. After defining and activating a rotation through the root-run CLI, enable automation explicitly. Check `sudo ./scripts/validate-install.sh`, `/health/automation`, and the [automation guide](automation.md). Existing station configs must be rerendered to switch to `request.queue`; this is a station-only maintenance event and should be validated before restarting its instance.
# Phase 6 database and programming

Provisioning applies additive clock/schedule migrations with `flask db upgrade`. Python 3.12's `zoneinfo` and Ubuntu's `tzdata` package supply IANA zones; no new Python package or system service is required. A fresh installation has no demo clocks or schedule. Set each station timezone, create clocks, and assign weekly times through the root-run CLI after creating categories and rotations. Existing stations migrate to explicit `UTC` until an operator changes them. Public clean-VM support remains unverified.

## Read-only web overview

The installer applies additive admin, ingest-job, and audit migrations. It creates a private web upload staging directory and a non-root `freo-ingest.service`; fresh rc.4 installations create the one-time `admin` / `IAmOnTheAir` login and require browser setup before administration. No initial CLI account creation is needed. For later root-run account recovery, create or rotate an account privately with `sudo /opt/freo/venv/bin/flask --app wsgi:app admin set-password --email operator@example.com` from `/opt/freo`. The command prompts twice without echoing the password. Do not put passwords in shell arguments, `.env.example`, or Git. `/admin` requires this login. Media and programming management are available there; station lifecycle and automation enable/disable remain CLI-only. Back up PostgreSQL, `/etc/freo`, and `/var/lib/freo/media`. See [UI guide](ui.md).

Phase 9's additive migration creates imaging assets and groups and extends clock targets and confirmed decision rows. Provisioning creates each station's private `imaging` directory owned by `freo-ingest:freo-playout` (mode 2750). No demo imaging is seeded. After upgrading, restart the Freo web and automation/ingest workers once to load the new code; subsequent imaging and clock edits do not require a playout or worker restart. See [Imaging and carts](imaging.md).

## Local statistics

Provisioning applies the additive statistics migration and installs `freo-stats.service`, hourly storage inventory and monthly local geographic database updates. The statistics worker has separate Icecast credentials and no Liquidsoap control-group access. Open Admin → Statistics for overall or per-channel views. See [statistics operations and measurement definitions](statistics.md).

### Public asset delivery

The project Nginx site includes `deploy/nginx/static-assets.conf`: public `/static/` CSS, JavaScript, JSON and SVG responses use gzip and a one-hour cache lifetime. WebP screenshots are already compressed. Audio streaming and authenticated HTML are outside this location. Existing sites receive the include through the provisioner, which retains a backup before editing. When updating an existing host manually, install it as `/etc/nginx/snippets/freo-static-assets.conf`, include it once in the Freo server block, run `nginx -t`, and reload Nginx.
