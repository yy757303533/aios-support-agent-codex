#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
venv=/opt/aios-support-stream/venv
credentials=/etc/aios-support/dingtalk-stream-credentials.json
service=aios-support-stream.service
old_service=dws-aios-support.service
unified_app_id=c66d1ebb-cdf3-4223-ba60-2c7548b8a607

if [[ $EUID -ne 0 ]]; then
  echo "install-stream-service.sh must run as root" >&2
  exit 2
fi

python_bin=/usr/bin/python3.9
"$python_bin" -c 'import sqlite3' || {
  echo "Python runtime lacks sqlite3" >&2
  exit 2
}
if [[ ! -x "$venv/bin/python" ]] || ! "$venv/bin/python" -c 'import sqlite3' >/dev/null 2>&1; then
  mkdir -p /opt/aios-support-stream
  "$python_bin" -m venv "$venv.new"
  "$venv.new/bin/pip" install --disable-pip-version-check -r "$repo_root/deploy/requirements-stream.txt"
  mv "$venv.new" "$venv"
else
  "$venv/bin/pip" install --disable-pip-version-check -r "$repo_root/deploy/requirements-stream.txt"
fi

PYTHON_BIN="$python_bin" bash "$repo_root/scripts/test-plugin.sh"

mkdir -p /etc/aios-support /var/lib/aios-support-stream
chmod 0700 /var/lib/aios-support-stream
credential_tmp=$(mktemp /etc/aios-support/dingtalk-stream-credentials.json.XXXXXX)
trap 'test ! -e "$credential_tmp" || shred -u "$credential_tmp"' EXIT
chmod 0600 "$credential_tmp"
dws devapp +credentials-get --unified-app-id "$unified_app_id" --format json |
  "$venv/bin/python" -c '
import json, os, sys
source=json.load(sys.stdin).get("result", {})
client_id, client_value=source.get("appKey"), source.get("appSecret")
if not isinstance(client_id, str) or not client_id or not isinstance(client_value, str) or not client_value:
    raise SystemExit(2)
json.dump({"appKey": client_id, "appSecret": client_value}, sys.stdout, separators=(",", ":"))
' >"$credential_tmp"
chown root:root "$credential_tmp"
chmod 0600 "$credential_tmp"
mv -f "$credential_tmp" "$credentials"
trap - EXIT

install -o root -g root -m 0644 "$repo_root/deploy/$service" "/etc/systemd/system/$service"
systemctl daemon-reload
systemctl enable "$service"
systemctl restart "$service"

connected=false
for _ in $(seq 1 30); do
  if systemctl is-active --quiet "$service" &&
     journalctl -u "$service" --since '-2 minutes' --no-pager | grep -Eq 'endpoint is|Stream connected'; then
    connected=true
    break
  fi
  sleep 1
done
if [[ "$connected" != true ]]; then
  echo "new Stream service did not connect; old gateway was not stopped" >&2
  systemctl status "$service" --no-pager -l >&2 || true
  exit 2
fi

if systemctl is-active --quiet "$old_service"; then
  systemctl disable --now "$old_service"
fi
echo "AIOS Stream service is active and connected."
