#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"

mkdir -p "$ROOT_DIR/data"
umask 077
printf "disabled" > "$ROOT_DIR/data/ai-provider.txt"

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE_NAME"
fi

echo "Der ManaVault Assistent ist deaktiviert. Ollama und vorhandene Modelle wurden nicht gelöscht."
