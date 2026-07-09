#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

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
echo "Scryfall Bulk Data wird geladen und importiert."
echo "Das kann beim ersten Mal mehrere Minuten dauern."
echo

exec ".venv/bin/python" -m backend.import_scryfall "$@"
