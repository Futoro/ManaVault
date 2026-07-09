#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"
HOST="${MANAVAULT_HOST:-0.0.0.0}"
PORT="${MANAVAULT_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_DIR="$(pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"
RUN_GROUP="$(id -gn "$RUN_USER")"

if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte mit sudo starten:"
  echo "  sudo ./install-linux-service.sh"
  exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 wurde nicht gefunden. Installiere zuerst:"
  echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Erstelle lokale Python-Umgebung..."
  sudo -u "$RUN_USER" "$PYTHON_BIN" -m venv .venv
fi

echo "Installiere Abhaengigkeiten..."
sudo -u "$RUN_USER" ".venv/bin/python" -m pip install --upgrade pip
sudo -u "$RUN_USER" ".venv/bin/python" -m pip install -r requirements.txt

echo "Schreibe systemd-Service..."
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=ManaVault local MTG collection manager
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn backend.main:app --host ${HOST} --port ${PORT}
Restart=on-failure
RestartSec=5
User=${RUN_USER}
Group=${RUN_GROUP}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "ManaVault laeuft jetzt als Server-Dienst."
echo "Status:"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo
echo "Logs:"
echo "  journalctl -u ${SERVICE_NAME} -f"
echo
echo "Adresse im Netzwerk:"
echo "  http://<server-ip>:${PORT}"
