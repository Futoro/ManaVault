#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

SERVICE_NAME="${MANAVAULT_BACKUP_SERVICE_NAME:-manavault-backup}"
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_GROUP="$(id -gn "$RUN_USER")"
ENV_FILE="/etc/default/${SERVICE_NAME}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./scripts/install-backup-timer.sh"
  exit 1
fi

chmod +x "${SCRIPT_DIR}/backup.sh"

if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<EOF
# Optionales Cloud-Ziel fuer rclone, z.B.:
# RCLONE_REMOTE=pcloud:ManaVault
RCLONE_REMOTE=
MANAVAULT_KEEP_LOCAL_BACKUPS=14
EOF
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=ManaVault daily database backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${APP_DIR}
ExecStart=${SCRIPT_DIR}/backup.sh
User=${RUN_USER}
Group=${RUN_GROUP}
EnvironmentFile=-${ENV_FILE}
EOF

cat > "/etc/systemd/system/${SERVICE_NAME}.timer" <<EOF
[Unit]
Description=Run ManaVault backup daily

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.timer"

echo
echo "ManaVault Autobackup ist aktiv."
echo "Cloud-Ziel eintragen:"
echo "  sudo nano ${ENV_FILE}"
echo
echo "Timer pruefen:"
echo "  systemctl list-timers ${SERVICE_NAME}.timer"
echo
echo "Testlauf:"
echo "  sudo systemctl start ${SERVICE_NAME}.service"
