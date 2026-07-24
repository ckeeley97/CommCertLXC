#!/usr/bin/env bash
# Runs INSIDE the Debian 12 LXC. Installs the app, its native PDF deps,
# a systemd service and an nginx reverse proxy. Idempotent.
#
#   provision.sh <APP_DIR>
#
# APP_DIR is the app/ folder to serve (e.g. the one inside your cloned repo,
# /opt/ascom-form/src/app). The service runs straight from there, so a later
# `git pull && systemctl restart ascom-form` picks up changes.
set -euo pipefail

ROOT=/opt/ascom-form
APP_DIR="${1:-$ROOT/src/app}"
VENV="$ROOT/venv"
DATA="$ROOT/data"

if [[ ! -f "$APP_DIR/app.py" ]]; then
  echo "!! $APP_DIR/app.py not found — pass the correct app dir." >&2
  exit 1
fi

echo ">> Installing packages…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip \
  nginx \
  libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
  libcairo2 libgdk-pixbuf-2.0-0 libffi-dev \
  fonts-dejavu-core

echo ">> Creating service user and data dir…"
id -u ascom >/dev/null 2>&1 || useradd --system --home "$ROOT" --shell /usr/sbin/nologin ascom
mkdir -p "$DATA"

echo ">> Python virtualenv…"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

chown -R ascom:ascom "$DATA" "$VENV"

echo ">> systemd service (running from $APP_DIR)…"
cat >/etc/systemd/system/ascom-form.service <<UNIT
[Unit]
Description=Ascom Commissioning Certificate form app
After=network.target

[Service]
Type=simple
User=ascom
Group=ascom
WorkingDirectory=$APP_DIR
Environment=ASCOM_DATA_DIR=$DATA
ExecStart=$VENV/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 app:app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now ascom-form
systemctl restart ascom-form

echo ">> nginx reverse proxy…"
cat >/etc/nginx/sites-available/ascom-form <<'NGINX'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 8m;      # allow signature PNG data URLs

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/ascom-form /etc/nginx/sites-enabled/ascom-form
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

echo ">> Done. App is live on port 80."
systemctl --no-pager --full status ascom-form | head -n 5 || true
