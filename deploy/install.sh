#!/bin/bash
# Installs Pi Eyes style control. Run from a checkout of this repo on the Pi,
# after Adafruit's pi-eyes.py installer has finished:
#   sudo bash deploy/install.sh
# Safe to re-run.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP=/opt/pi-eyes-control
STATE=/var/lib/pi-eyes
CONFIG=/etc/pi-eyes/control.toml

if [[ $EUID -ne 0 ]]; then
    echo "Run this with sudo." >&2
    exit 1
fi
if [[ ! -f /opt/Pi_Eyes/eyes.py || ! -f /etc/pi-eyes/env ]]; then
    echo "Adafruit's software isn't installed. Run pi-eyes.py first." >&2
    exit 1
fi
if ! systemctl cat pi-eyes.service >/dev/null 2>&1; then
    echo "pi-eyes.service not found. Check that pi-eyes.py finished." >&2
    exit 1
fi

id -u pi-eyes >/dev/null 2>&1 ||
    useradd --system --no-create-home --shell /usr/sbin/nologin pi-eyes

echo "Copying files to $APP"
install -d "$APP"
rm -rf "$APP/control" "$APP/supervisor" "$APP/tools"
cp -r "$REPO/control" "$REPO/supervisor" "$REPO/tools" "$APP/"
find "$APP" -name __pycache__ -prune -exec rm -rf {} +

echo "Installing Python dependencies"
[[ -x "$APP/venv/bin/python" ]] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --quiet -r "$REPO/requirements.txt"

echo "Building built-in styles"
install -d -o pi-eyes -g pi-eyes -m 2775 "$STATE" "$STATE/styles"
"$APP/venv/bin/python" "$APP/tools/make_starter_styles.py" \
    --source /opt/Pi_Eyes/graphics --dest "$STATE/styles"
[[ -e "$STATE/current-style" ]] || echo default > "$STATE/current-style"
chown -R pi-eyes:pi-eyes "$STATE"

# The supervisor writes active-style. If Adafruit's service isn't root, its user
# needs write access to the state folder.
SERVICE_USER="$(systemctl show -p User --value pi-eyes.service)"
if [[ -n "$SERVICE_USER" && "$SERVICE_USER" != root ]]; then
    usermod -aG pi-eyes "$SERVICE_USER"
fi

if [[ ! -e "$CONFIG" ]]; then
    install -o pi-eyes -g pi-eyes -m 600 "$REPO/config.example.toml" "$CONFIG"
    echo "Created $CONFIG. Add your MQTT broker there for Home Assistant."
fi

echo "Installing services"
install -m 644 "$REPO/systemd/pi-eyes-control.service" /etc/systemd/system/
install -d /etc/systemd/system/pi-eyes.service.d
install -m 644 "$REPO/systemd/pi-eyes.service.d/override.conf" \
    /etc/systemd/system/pi-eyes.service.d/
systemctl daemon-reload
systemctl enable pi-eyes-control.service
systemctl restart pi-eyes-control.service
systemctl restart pi-eyes.service

echo "Done. Open http://$(hostname).local:$(grep -m1 '^port' "$CONFIG" | tr -dc 0-9)"
