#!/usr/bin/env bash
set -euo pipefail

source_dir=${1:?source directory required}
install_dir=${FREO_INSTALL_DIR:-/opt/freo}
if [[ $install_dir != /opt/freo ]]; then
  echo 'Phase 1 supports FREO_INSTALL_DIR=/opt/freo only.' >&2
  exit 1
fi
. /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 ]]; then
  echo 'Freo Phase 1 installer supports Ubuntu 24.04 only.' >&2
  exit 1
fi
if [[ ! -d "$source_dir/app" ]]; then
  echo 'Missing application files.' >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
printf 'Installing required Freo system packages without upgrading existing packages...\n'
apt-get update
apt-get install --no-upgrade -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib openssl certbot python3-certbot-nginx liquidsoap icecast2 ffmpeg
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
install -d -o freo-playout -g freo-playout -m 0750 /var/lib/freo/playout
install -d -o root -g freo-playout -m 0750 /var/lib/freo/media /var/lib/freo/playlists
install -d -o freo -g freo -m 0750 /var/lib/freo/state
install -d -o icecast2 -g icecast -m 0750 /var/log/icecast2
# Only named release files are deployed; .env, media, .git and runtime files stay untouched.
if [[ $source_dir != "$install_dir" ]]; then
  cp -R "$source_dir/app" "$install_dir/"
fi
chown -R root:root "$install_dir/app"
if [[ $source_dir != "$install_dir" ]]; then
  install -m 0644 "$source_dir/wsgi.py" "$install_dir/wsgi.py"
  install -m 0644 "$source_dir/requirements.txt" "$install_dir/requirements.txt"
fi
if [[ ! -x "$install_dir/venv/bin/python" ]]; then
  python3 -m venv "$install_dir/venv"
fi
"$install_dir/venv/bin/pip" install -r "$install_dir/requirements.txt"
if [[ ! -f "$install_dir/.env" ]]; then
  if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='freo'" | grep -qx 1; then
    echo 'Existing PostgreSQL role freo found but no .env; refusing to reset its password.' >&2
    exit 1
  fi
  db_password=$(openssl rand -hex 32)
  app_secret=$(openssl rand -hex 32)
  runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE freo LOGIN PASSWORD '$db_password'" >/dev/null
  if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='freo'" | grep -qx 1; then
    runuser -u postgres -- createdb -O freo freo
  fi
  domain=${FREO_DOMAIN:-}
  if [[ -n $domain && ! $domain =~ ^[A-Za-z0-9.-]+$ ]]; then
    echo 'FREO_DOMAIN contains invalid characters.' >&2
    exit 1
  fi
  public_base=http://${domain:-localhost}
  if [[ -z $domain ]]; then
    public_base=http://$(hostname -I | awk '{print $1}')
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
ENV
  unset db_password app_secret
fi
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
  chown -R root:root "$install_dir/migrations"
fi
install -d -o root -g root -m 0755 "$install_dir/deploy/icecast" "$install_dir/deploy/liquidsoap" "$install_dir/deploy/nginx" "$install_dir/deploy/systemd" "$install_dir/scripts"
if [[ $source_dir != "$install_dir" ]]; then
  install -m 0644 "$source_dir/deploy/icecast/icecast.xml.template" "$install_dir/deploy/icecast/icecast.xml.template"
  install -m 0644 "$source_dir/deploy/liquidsoap/freo-test.liq.template" "$install_dir/deploy/liquidsoap/freo-test.liq.template"
  install -m 0644 "$source_dir/deploy/liquidsoap/station.liq.template" "$install_dir/deploy/liquidsoap/station.liq.template"
  install -m 0644 "$source_dir/deploy/nginx/station-location.conf.template" "$install_dir/deploy/nginx/station-location.conf.template"
  install -m 0755 "$source_dir/scripts/render-radio-config.py" "$install_dir/scripts/render-radio-config.py"
  install -m 0755 "$source_dir/scripts/validate-station-instance.py" "$install_dir/scripts/validate-station-instance.py"
fi
python3 "$install_dir/scripts/render-radio-config.py"
if [[ -f "$install_dir/migrations/env.py" ]]; then
  (cd "$install_dir" && runuser -u freo -- env FREO_ENV_FILE="$install_dir/.env" "$install_dir/venv/bin/flask" --app wsgi:app db upgrade)
fi
unit_src=$source_dir/deploy/systemd/freo.service
unit_dst=/etc/systemd/system/freo.service
if [[ -f $unit_dst ]] && ! cmp -s "$unit_src" "$unit_dst"; then
  cp -a "$unit_dst" "$unit_dst.backup.$(date +%Y%m%d%H%M%S)"
fi
install -m 0644 "$unit_src" "$unit_dst"
systemctl daemon-reload
systemctl enable --now freo.service
systemctl restart freo.service
for service in icecast2 freo-playout freo-playout@; do
  unit_src="$source_dir/deploy/systemd/$service.service"
  unit_dst="/etc/systemd/system/$service.service"
  if [[ -f $unit_dst ]] && ! cmp -s "$unit_src" "$unit_dst"; then
    cp -a "$unit_dst" "$unit_dst.backup.$(date +%Y%m%d%H%M%S)"
  fi
  install -m 0644 "$unit_src" "$unit_dst"
done
systemctl daemon-reload
systemctl enable --now icecast2.service freo-playout.service
systemctl reload icecast2.service
install -m 0644 "$source_dir/deploy/nginx/stream-location.conf" /etc/nginx/snippets/freo-stream.conf
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
nginx -t
systemctl reload nginx
if [[ ${FREO_ENABLE_HTTPS:-0} == 1 ]]; then
  if [[ -z ${FREO_DOMAIN:-} || -z ${FREO_CERTBOT_EMAIL:-} ]]; then
    echo 'HTTPS requires FREO_DOMAIN and FREO_CERTBOT_EMAIL.' >&2
    exit 1
  fi
  certbot --nginx --non-interactive --agree-tos --redirect -m "$FREO_CERTBOT_EMAIL" -d "$FREO_DOMAIN"
fi
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
"$source_dir/scripts/validate-install.sh"
