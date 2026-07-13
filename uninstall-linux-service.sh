#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"
PUBLIC_SERVICE_NAME="${MANAVAULT_PUBLIC_SERVICE_NAME:-manavault-public}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./uninstall-linux-service.sh"
  exit 1
fi

systemctl stop "$PUBLIC_SERVICE_NAME" 2>/dev/null || true
systemctl disable "$PUBLIC_SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${PUBLIC_SERVICE_NAME}.service"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

echo "Services ${SERVICE_NAME} und ${PUBLIC_SERVICE_NAME} wurden entfernt. Projektdateien und Datenbank bleiben erhalten."
