#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

SERVICE_NAME="${MANAVAULT_PUBLIC_SERVICE_NAME:-manavault-public}"
APP_DIR="$(pwd)"
PORT="${MANAVAULT_PUBLIC_PORT:-8001}"
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_GROUP="$(id -gn "$RUN_USER")"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./install-linux-public-service.sh"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Python-Umgebung fehlt. Fuehre zuerst install-linux-service.sh aus."
  exit 1
fi

cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=ManaVault public read-only deck viewer
After=network-online.target manavault.service
Wants=network-online.target
Requires=manavault.service

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn backend.public:app --host 127.0.0.1 --port ${PORT}
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
echo "Oeffentliche Nur-Lese-Ansicht laeuft lokal auf:"
echo "  http://127.0.0.1:${PORT}"
echo
echo "Status:"
echo "  sudo systemctl status ${SERVICE_NAME}"
