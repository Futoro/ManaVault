#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PUBLIC_URL="${1:-}"
if [[ ! "$PUBLIC_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?/?$ ]]; then
  echo "Aufruf:"
  echo "  ./scripts/configure-public-url.sh https://decks.deinedomain.ch"
  echo "  ./scripts/configure-public-url.sh https://geraet.tailnet.ts.net:8443"
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
