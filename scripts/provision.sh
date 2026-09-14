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
printf 'Installing Phase 1 system packages...\n'
apt-get update
apt-get install -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib openssl certbot python3-certbot-nginx
systemctl enable --now postgresql nginx
if ! id freo >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/freo --shell /usr/sbin/nologin freo
fi
install -d -o root -g root -m 0755 "$install_dir"
install -d -o freo -g freo -m 0750 /var/lib/freo
# Only named release files are deployed; .env, media, .git and runtime files stay untouched.
if [[ $source_dir != "$install_dir" ]]; then
  cp -R "$source_dir/app" "$install_dir/"
fi
chown -R root:root "$install_dir/app"
install -m 0644 "$source_dir/wsgi.py" "$install_dir/wsgi.py"
install -m 0644 "$source_dir/requirements.txt" "$install_dir/requirements.txt"
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
"$source_dir/scripts/validate-install.sh"
