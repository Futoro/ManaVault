#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PUBLIC_URL="${1:-}"
if [[ ! "$PUBLIC_URL" =~ ^https://[A-Za-z0-9.-]+/?$ ]]; then
  echo "Aufruf:"
  echo "  ./configure-public-url.sh https://decks.deinedomain.ch"
  exit 1
fi

PUBLIC_URL="${PUBLIC_URL%/}"
mkdir -p data
printf '%s\n' "$PUBLIC_URL" > data/public-url.txt
chmod 600 data/public-url.txt

sudo systemctl restart manavault
sudo systemctl restart manavault-public

echo
echo "Oeffentliche ManaVault-Adresse gespeichert:"
echo "  $PUBLIC_URL"
echo
echo "Neue QR-Codes verwenden ab jetzt diese Adresse."
