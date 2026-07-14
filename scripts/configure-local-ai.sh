#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROVIDER_FILE="$ROOT_DIR/data/ai-provider.txt"
MODEL_FILE="$ROOT_DIR/data/ollama-model.txt"
SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"
MODEL="${1:-qwen3:4b}"

if ! command -v curl >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "Installiere den für den Ollama-Download benötigten Netzwerkhelfer ..."
    sudo apt-get update
    sudo apt-get install -y curl
  else
    echo "curl fehlt und konnte auf diesem System nicht automatisch installiert werden."
    exit 1
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama wird jetzt als optionale lokale KI installiert."
  curl -fsSL https://ollama.com/install.sh | sh
fi

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl enable --now ollama
fi

echo "Lade lokales Modell $MODEL. Der Download kann einige Minuten dauern ..."
ollama pull "$MODEL"

mkdir -p "$ROOT_DIR/data"
umask 077
printf "ollama" > "$PROVIDER_FILE"
printf "%s" "$MODEL" > "$MODEL_FILE"

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "$SERVICE_NAME.service" >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE_NAME"
fi

echo
echo "Der lokale ManaVault Assistent ist mit $MODEL eingerichtet."
echo "Das Modell wird bei Nichtbenutzung nach etwa fünf Minuten aus dem Arbeitsspeicher entladen."
