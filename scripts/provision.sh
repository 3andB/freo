#!/usr/bin/env bash
set -euo pipefail
umask 022

source_dir=${1:?source directory required}
install_dir=${FREO_INSTALL_DIR:-/opt/freo}
if [[ $install_dir != /opt/freo ]]; then
  echo 'Freo currently supports FREO_INSTALL_DIR=/opt/freo only.' >&2
  exit 1
fi
# Installation and upgrade are separate operations. Refuse before apt, file
# replacement, role creation or any service changes on an existing installation.
if [[ -e "$install_dir/.env" || -L "$install_dir/.env" || -e "$install_dir/current" || -L "$install_dir/current" || -e /etc/freo/freo.env || -L /etc/freo/freo.env || -d /var/lib/freo/media ]]; then
  echo 'Existing Freo state detected. Installer will not overwrite this installation.' >&2
  echo 'Use the verified upgrade/recovery workflow in docs/recovery-and-upgrades.md.' >&2
  exit 1
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 ]]; then
  echo 'Freo installer supports Ubuntu 24.04 only.' >&2
  exit 1
fi
if [[ $(uname -m) != x86_64 ]]; then
  echo 'Freo installer supports x86_64 servers only.' >&2
  exit 1
fi
if [[ ! -d "$source_dir/app" ]]; then
  echo 'Missing application files.' >&2
  exit 1
fi
# Validate HTTPS inputs before installing packages or creating any durable state.
domain=${FREO_DOMAIN:-}
if [[ -n $domain && ! $domain =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo 'FREO_DOMAIN contains invalid characters.' >&2
  exit 1
fi
if [[ ${FREO_ENABLE_HTTPS:-0} != 0 && ${FREO_ENABLE_HTTPS:-0} != 1 ]]; then
  echo 'FREO_ENABLE_HTTPS must be 0 or 1.' >&2
  exit 1
fi
public_scheme=http
if [[ ${FREO_ENABLE_HTTPS:-0} == 1 ]]; then
  if [[ -z $domain || -z ${FREO_CERTBOT_EMAIL:-} ]]; then
    echo 'HTTPS requires FREO_DOMAIN and FREO_CERTBOT_EMAIL.' >&2
    exit 1
  fi
  public_scheme=https
fi
public_base=$public_scheme://${domain:-localhost}
if [[ -z $domain ]]; then
  public_base=http://$(hostname -I | awk '{print $1}')
fi
printf '%s\n' 'Freo automatically reports installation identity, version, machine facts, channel metadata and hourly aggregate totals to api.freo.live.' 'No owner account is required. Listener identities/IPs and music metadata are not sent; public directory listing is opt-in.'
export DEBIAN_FRONTEND=noninteractive
printf 'Installing Freo dependencies; Icecast will use the supported 2.5 series...\n'
apt-get update
apt-get install --no-upgrade -y python3 ca-certificates gnupg
bash "$source_dir/scripts/configure-icecast-repository.sh"
apt-get update
apt-get install --no-upgrade -y python3 python3-venv python3-pip tzdata curl git nginx postgresql postgresql-contrib openssl certbot python3-certbot-nginx liquidsoap ffmpeg acl
# The trusted-proxy configuration requires Icecast 2.5 even on existing installs.
# Keep dpkg from removing the old package's empty directory during upgrade;
# Xiph's post-install script still expects it but no longer ships the directory.
install -d -m 0750 /var/log/icecast2
touch /var/log/icecast2/.freo-keep
mapfile -t active_playout_units < <(systemctl list-units --state=active --no-legend --plain 'freo-playout*.service' | awk '{print $1}')
apt-get install --no-remove -y 'icecast2=2.5.*'
# A package-triggered Icecast restart can stop Requires= playout dependents.
if (( ${#active_playout_units[@]} )); then
  systemctl start "${active_playout_units[@]}"
fi
dpkg-query -W -f='Installed ${Package} ${Version}\n' liquidsoap icecast2 ffmpeg
systemctl enable --now postgresql nginx
if ! id freo >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/freo --shell /usr/sbin/nologin freo
fi
install -d -o root -g root -m 0755 "$install_dir"
install -d -o freo -g freo -m 0750 /var/lib/freo
chmod 0711 /var/lib/freo
if ! id freo-playout >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/freo/playout --shell /usr/sbin/nologin freo-playout
fi
if ! id freo-automation >/dev/null 2>&1; then
  useradd --system --user-group --groups freo,freo-playout --home-dir /var/lib/freo --shell /usr/sbin/nologin freo-automation
else
  usermod -a -G freo,freo-playout freo-automation
fi
if ! id freo-ingest >/dev/null 2>&1; then
  useradd --system --user-group --groups freo --home-dir /var/lib/freo --shell /usr/sbin/nologin freo-ingest
else
  usermod -G freo freo-ingest
fi
install -d -o freo-playout -g freo-playout -m 0750 /var/lib/freo/playout
install -d -o root -g freo-playout -m 0750 /var/lib/freo/media /var/lib/freo/playlists
chmod 0751 /var/lib/freo/media
install -d -o freo -g freo-ingest -m 2770 /var/lib/freo/uploads
for station_dir in /var/lib/freo/media/*; do
  [[ -d $station_dir && ! -L $station_dir ]] || continue
  if [[ -L $station_dir/originals || -L $station_dir/staging || -L $station_dir/imaging ]]; then
    echo 'Refusing symlinked media directory during ingest provisioning.' >&2
    exit 1
  fi
  install -d -o freo-ingest -g freo-playout -m 2750 "$station_dir" "$station_dir/originals" "$station_dir/imaging"
  install -d -o freo-ingest -g freo-playout -m 2700 "$station_dir/staging"
  find "$station_dir/originals" -maxdepth 1 -type f -name '*.mp3' -exec chown freo-ingest:freo-playout {} +
  find "$station_dir/imaging" -maxdepth 1 -type f -name '*.mp3' -exec chown freo-ingest:freo-playout {} +
done
bash "$source_dir/scripts/media-web-access.sh" /var/lib/freo/media
install -d -o freo -g freo -m 0750 /var/lib/freo/state
install -d -o icecast2 -g icecast -m 0750 /var/log/icecast2
# Only named release files are deployed; .env, media, .git and runtime files stay untouched.
if [[ $source_dir != "$install_dir" ]]; then
  for directory in app freo_ops migrations deploy scripts docs; do
    cp -R "$source_dir/$directory" "$install_dir/"
  done
  install -m 0644 "$source_dir/LICENSE" "$install_dir/LICENSE"
  if [[ -f "$source_dir/release.json" ]]; then
    install -m 0644 "$source_dir/release.json" "$install_dir/release.json"
  fi
fi
chown -R root:root "$install_dir/app"
chown -R root:root "$install_dir/freo_ops"
if [[ $source_dir != "$install_dir" ]]; then
  install -m 0644 "$source_dir/wsgi.py" "$install_dir/wsgi.py"
  install -m 0644 "$source_dir/requirements.txt" "$install_dir/requirements.txt"
fi
if [[ ! -x "$install_dir/venv/bin/python" ]]; then
  python3 -m venv "$install_dir/venv"
fi
if [[ -f "$source_dir/requirements.lock" && -d "$source_dir/wheels" ]]; then
  "$install_dir/venv/bin/pip" install --no-index --require-hashes --find-links "$source_dir/wheels" -r "$source_dir/requirements.lock"
else
  "$install_dir/venv/bin/pip" install -r "$install_dir/requirements.txt"
fi
if [[ ! -f "$install_dir/.env" ]]; then
  if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='freo'" | grep -qx 1; then
    echo 'Existing PostgreSQL role freo found but no .env; refusing to reset its password.' >&2
    exit 1
  fi
  db_password=$(openssl rand -hex 32)
  app_secret=$(openssl rand -hex 32)
  if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='freo'" | grep -qx 1; then
    echo 'Existing Freo database found; refusing fresh installation. Use recovery/adoption.' >&2
    exit 1
  fi
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 >/dev/null <<SQL
CREATE ROLE freo LOGIN PASSWORD '$db_password';
SQL
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='freo'" | grep -qx 1; then
    runuser -u postgres -- createdb -O freo freo
  fi
  umask 077
  cat > "$install_dir/.env" <<ENV
FLASK_ENV=production
SECRET_KEY=$app_secret
DATABASE_URL=postgresql://freo:$db_password@127.0.0.1/freo
PUBLIC_BASE_URL=$public_base
FREO_DOMAIN=$domain
LOG_LEVEL=INFO
FREO_MEDIA_ROOT=/var/lib/freo/media
FREO_MAX_STATIONS=${FREO_MAX_STATIONS:-3}
ENV
  unset db_password app_secret
fi
umask 022
chown root:freo "$install_dir/.env"
chmod 0640 "$install_dir/.env"
if ! grep -q '^SECRET_KEY=' "$install_dir/.env"; then
  echo 'Existing .env lacks SECRET_KEY. Add it privately; installer will not overwrite .env.' >&2
  exit 1
fi
if [[ $source_dir != "$install_dir" && -d "$source_dir/migrations" && -f "$source_dir/migrations/env.py" ]]; then
  cp -R "$source_dir/migrations" "$install_dir/"
fi
if [[ -d "$install_dir/migrations" ]]; then
  # Phase 6 clock/schedule upgrades are additive; demo programming is never seeded.
  chown -R root:root "$install_dir/migrations"
fi
install -d -o root -g root -m 0755 "$install_dir/deploy/icecast" "$install_dir/deploy/liquidsoap" "$install_dir/deploy/nginx" "$install_dir/deploy/systemd" "$install_dir/scripts"
if [[ $source_dir != "$install_dir" ]]; then
  install -m 0644 "$source_dir/deploy/icecast/icecast.xml.template" "$install_dir/deploy/icecast/icecast.xml.template"
  install -m 0644 "$source_dir/deploy/liquidsoap/freo-test.liq.template" "$install_dir/deploy/liquidsoap/freo-test.liq.template"
  install -m 0644 "$source_dir/deploy/liquidsoap/station.liq.template" "$install_dir/deploy/liquidsoap/station.liq.template"
  install -m 0644 "$source_dir/deploy/nginx/station-location.conf.template" "$install_dir/deploy/nginx/station-location.conf.template"
  install -m 0755 "$source_dir/scripts/render-radio-config.py" "$install_dir/scripts/render-radio-config.py"
  install -m 0755 "$source_dir/scripts/configure-icecast-repository.sh" "$install_dir/scripts/configure-icecast-repository.sh"
  install -m 0755 "$source_dir/scripts/validate-station-instance.py" "$install_dir/scripts/validate-station-instance.py"
fi
python3 "$install_dir/scripts/render-radio-config.py"
if [[ -f "$install_dir/migrations/env.py" ]]; then
  (cd "$install_dir" && runuser -u freo -- env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/flask" --app wsgi:app db upgrade)
  (cd "$install_dir" && runuser -u freo -- env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/flask" --app wsgi:app settings import-environment)
fi
(cd "$install_dir" && env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/flask" --app wsgi:app admin bootstrap)
unit_src=$source_dir/deploy/systemd/freo.service
unit_dst=/etc/systemd/system/freo.service
if [[ -f $unit_dst ]] && ! cmp -s "$unit_src" "$unit_dst"; then
  cp -a "$unit_dst" "$unit_dst.backup.$(date +%Y%m%d%H%M%S)"
fi
install -m 0644 "$unit_src" "$unit_dst"
systemctl daemon-reload
systemctl enable --now freo.service
systemctl restart freo.service
for service in icecast2 freo-playout freo-playout@ freo-automation freo-ingest freo-provision freo-public-schedules freo-central-api freo-updater; do
  unit_src="$source_dir/deploy/systemd/$service.service"
  unit_dst="/etc/systemd/system/$service.service"
  if [[ -f $unit_dst ]] && ! cmp -s "$unit_src" "$unit_dst"; then
    cp -a "$unit_dst" "$unit_dst.backup.$(date +%Y%m%d%H%M%S)"
  fi
  install -m 0644 "$unit_src" "$unit_dst"
done
systemctl daemon-reload
systemctl enable --now icecast2.service
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 ]]; then
  systemctl enable --now freo-playout.service
fi
systemctl enable --now freo-automation.service
systemctl enable --now freo-ingest.service
install -d -o root -g root -m 0755 /etc/freo
install -d -o root -g root -m 0755 /etc/freo/radio /etc/freo/radio/stations
freo_release=$(git -C "$source_dir" rev-parse --short HEAD 2>/dev/null || printf '%s' "${FREO_VERSION:-development}")
printf '%s\n' "$freo_release" > /etc/freo/release
chmod 0644 /etc/freo/release
systemctl enable freo-central-api.service
systemctl restart freo-central-api.service
install -m 0644 "$source_dir/deploy/systemd/freo-public-schedules.timer" /etc/systemd/system/freo-public-schedules.timer
systemctl daemon-reload
systemctl enable --now freo-public-schedules.timer
install -m 0644 "$source_dir/deploy/systemd/freo-updater.timer" /etc/systemd/system/freo-updater.timer
systemctl daemon-reload
systemctl enable --now freo-updater.timer
systemctl reload icecast2.service
install -m 0644 "$source_dir/deploy/nginx/stream-location.conf" /etc/nginx/snippets/freo-stream.conf
install -m 0644 "$source_dir/deploy/nginx/admin-upload.conf" /etc/nginx/snippets/freo-admin-upload.conf
install -m 0644 "$source_dir/deploy/nginx/static-assets.conf" /etc/nginx/snippets/freo-static-assets.conf
install -d -o root -g root -m 0755 /etc/nginx/snippets/freo-stations
site=/etc/nginx/sites-available/freo
if [[ ! -e $site ]]; then
  host=${FREO_DOMAIN:-$(hostname -I | awk '{print $1}')}
  if [[ ! $host =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo 'Invalid server name for Nginx.' >&2
    exit 1
  fi
  sed "s/FREO_SERVER_NAME/$host/g" "$source_dir/deploy/nginx/freo.conf.template" > "$site"
  ln -s "$site" /etc/nginx/sites-enabled/freo
else
  echo 'Existing Nginx site retained; review it manually if changing domains.'
fi
if ! grep -q 'freo-admin-upload.conf' "$site"; then
  python3 - "$site" <<'PY'
from pathlib import Path
import sys
site = Path(sys.argv[1])
body = site.read_text()
needle = 'include /etc/nginx/snippets/freo-stations/*.conf;'
if body.count(needle) != 1:
    raise SystemExit('Existing Nginx site lacks one unambiguous station include; add the admin upload include manually')
backup = site.with_name(site.name + '.pre-media-upload')
if not backup.exists():
    backup.write_text(body)
site.write_text(body.replace(needle, needle + '\n    include /etc/nginx/snippets/freo-admin-upload.conf;', 1))
PY
fi
if ! grep -q 'freo-static-assets.conf' "$site"; then
  python3 - "$site" <<'PY'
from pathlib import Path
import sys
site = Path(sys.argv[1])
body = site.read_text()
needle = 'include /etc/nginx/snippets/freo-admin-upload.conf;'
if body.count(needle) != 1:
    raise SystemExit('Existing Nginx site lacks one unambiguous upload include; add the static assets include manually')
backup = site.with_name(site.name + '.pre-static-assets')
if not backup.exists():
    backup.write_text(body)
site.write_text(body.replace(needle, needle + '\n    include /etc/nginx/snippets/freo-static-assets.conf;', 1))
PY
fi
nginx -t
systemctl reload nginx
install -m 0644 "$source_dir/deploy/systemd/freo-provision.timer" /etc/systemd/system/freo-provision.timer
systemctl daemon-reload
systemctl enable --now freo-provision.timer
if [[ ${FREO_ENABLE_HTTPS:-0} == 1 ]]; then
  certbot --nginx --non-interactive --agree-tos --redirect -m "$FREO_CERTBOT_EMAIL" -d "$FREO_DOMAIN"
  systemctl enable --now certbot.timer
fi
if [[ ${FREO_ENABLE_DIAGNOSTIC:-0} == 1 ]]; then
for attempt in {1..30}; do
  if [[ -S /run/freo/liquidsoap/control.sock ]] && curl --fail --silent --max-time 2 http://127.0.0.1:8000/health/stream >/dev/null; then
    break
  fi
  if (( attempt == 30 )); then
    echo 'Radio engine did not become ready within 60 seconds.' >&2
    exit 1
  fi
  sleep 2
done
fi
bash "$source_dir/scripts/install-statistics.sh" "$source_dir"
(cd "$install_dir" && bash "$source_dir/scripts/validate-install.sh")

printf 'Open %s/admin/login and sign in with username admin and password IAmOnTheAir.\n' "$public_base"
printf 'Complete first-time setup immediately: choose your own password before accessing administration.\n'
printf 'The first administrator manages installation upgrades and licenses. Registration is optional.\n'
