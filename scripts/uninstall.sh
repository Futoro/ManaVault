#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"
PUBLIC_SERVICE_NAME="${MANAVAULT_PUBLIC_SERVICE_NAME:-manavault-public}"
REMOTE_SERVICE_NAME="${MANAVAULT_REMOTE_SERVICE_NAME:-manavault-remote}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./scripts/uninstall.sh"
  exit 1
fi

systemctl stop "$REMOTE_SERVICE_NAME" 2>/dev/null || true
systemctl disable "$REMOTE_SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${REMOTE_SERVICE_NAME}.service"
systemctl stop "$PUBLIC_SERVICE_NAME" 2>/dev/null || true
systemctl disable "$PUBLIC_SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${PUBLIC_SERVICE_NAME}.service"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload

echo "ManaVault-Services wurden entfernt. Projektdateien und Datenbank bleiben erhalten."
