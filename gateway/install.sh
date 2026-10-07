#!/bin/sh
# Run from a checked-out Beacon Cooked repository on the remote Linux host.
set -eu
test "$(id -u)" = 0 || { echo 'Run this installer as root'; exit 1; }
source_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
apt-get update
apt-get install -y bluez python3 python3-paho-mqtt
install -d -m 755 /opt/tuya-beacon
install -d -m 700 /etc/tuya-beacon /var/lib/tuya-beacon
cp -R "$source_root/custom_components/tuya_beacon/beacon" /opt/tuya-beacon/
install -m 644 "$source_root/gateway/server.py" "$source_root/gateway/mqtt_bridge.py" /opt/tuya-beacon/
install -m 644 "$source_root/gateway/tuya-beacon.service" /etc/systemd/system/
if test ! -f /etc/tuya-beacon/config.json; then
    python3 - <<'PY'
import json,secrets,uuid
from pathlib import Path
path=Path('/etc/tuya-beacon/config.json')
path.write_text(json.dumps({'gateway_id':'beacon-'+uuid.uuid4().hex,'adapter':'hci0',
    'bind':'0.0.0.0','port':8787,'token':secrets.token_urlsafe(32),'lights':[]},indent=2))
path.chmod(0o600)
PY
fi
systemctl enable --now bluetooth
systemctl daemon-reload
systemctl enable tuya-beacon
systemctl restart tuya-beacon
echo 'Beacon Cooked is ready. Add the host LAN address and the token from /etc/tuya-beacon/config.json in the HA wizard.'
