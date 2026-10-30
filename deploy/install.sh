#!/usr/bin/env sh
# One-time setup on the server, as root from the checkout (e.g. /opt/xtip): service user, venv, key file, systemd unit.
set -eu
APP_DIR=$(cd "$(dirname "$0")/.." && pwd)

id xtip >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin xtip
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
mkdir -p "$APP_DIR/data"
chown -R xtip:xtip "$APP_DIR/data"

if [ ! -f /etc/xtip.env ]; then
  printf 'PINNWIRE_API_KEY=\n' > /etc/xtip.env
  chmod 600 /etc/xtip.env
  echo "Upiši PinnWire ključ u /etc/xtip.env, pa: systemctl restart xtip"
fi

sed "s#/opt/xtip#$APP_DIR#g" "$APP_DIR/deploy/xtip.service" > /etc/systemd/system/xtip.service
systemctl daemon-reload
systemctl enable --now xtip
systemctl --no-pager status xtip | head -5
