#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

SERVICE_NAME="${MANAVAULT_REMOTE_SERVICE_NAME:-manavault-remote}"
PORT="${MANAVAULT_REMOTE_PORT:-8002}"
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_GROUP="$(id -gn "$RUN_USER")"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./scripts/install-remote-service.sh"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Python-Umgebung fehlt. Fuehre zuerst sudo ./scripts/install.sh aus."
  exit 1
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=ManaVault authenticated remote access
After=network-online.target manavault.service
Wants=network-online.target
Requires=manavault.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn backend.remote:app --host 127.0.0.1 --port ${PORT}
Restart=on-failure
RestartSec=5
User=${RUN_USER}
Group=${RUN_GROUP}
Environment=PYTHONUNBUFFERED=1
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "Geschuetzter externer Zugang laeuft lokal auf:"
echo "  http://127.0.0.1:${PORT}"
