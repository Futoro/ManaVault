#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./uninstall-linux-service.sh"
  exit 1
fi

systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

echo "Service ${SERVICE_NAME} wurde entfernt. Projektdateien und Datenbank bleiben erhalten."
