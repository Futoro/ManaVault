#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_FILE="$ROOT_DIR/data/openai-api-key.txt"
PROVIDER_FILE="$ROOT_DIR/data/ai-provider.txt"
SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"

mkdir -p "$ROOT_DIR/data"
printf "OpenAI-API-Schlüssel (Eingabe bleibt unsichtbar): "
IFS= read -r -s OPENAI_KEY
printf "\n"

if [[ -z "$OPENAI_KEY" ]]; then
  echo "Abgebrochen: Es wurde kein Schlüssel eingegeben."
  exit 1
fi

umask 077
printf "%s" "$OPENAI_KEY" > "$KEY_FILE"
printf "openai" > "$PROVIDER_FILE"
chmod 600 "$KEY_FILE"
unset OPENAI_KEY

echo "Der API-Schlüssel wurde geschützt gespeichert."
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE_NAME"
  echo "ManaVault wurde neu gestartet."
else
  echo "Bitte ManaVault neu starten, damit der Assistent verfügbar wird."
fi
