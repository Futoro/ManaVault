#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

HOST="${MANAVAULT_HOST:-0.0.0.0}"
PORT="${MANAVAULT_PORT:-8000}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3 wurde nicht gefunden. Installiere z.B. mit:"
  echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Erstelle lokale Python-Umgebung..."
  "$PYTHON_BIN" -m venv .venv
fi

echo "Pruefe Abhaengigkeiten..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

echo
echo "ManaVault startet..."
echo "Auf diesem Geraet:  http://127.0.0.1:${PORT}"
echo "Im Netzwerk:        http://<server-ip>:${PORT}"
echo "Beenden mit Strg+C."
echo

exec ".venv/bin/python" -m uvicorn backend.main:app --host "$HOST" --port "$PORT"
