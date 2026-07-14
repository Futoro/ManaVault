#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SOURCE_DIR"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ManaVault benötigt für die Installation Administratorrechte."
  exec sudo bash "$SOURCE_DIR/INSTALLIEREN.sh" "$@"
fi

SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"
RUN_USER="${SUDO_USER:-$(stat -c '%U' "$SOURCE_DIR")}"
RUN_GROUP="$(id -gn "$RUN_USER")"
TARGET_DIR="$SOURCE_DIR"
IS_UPDATE=0

EXISTING_DIR="$(systemctl show "$SERVICE_NAME" -p WorkingDirectory --value 2>/dev/null || true)"
if [[ -n "$EXISTING_DIR" && -d "$EXISTING_DIR" && -f "$EXISTING_DIR/backend/main.py" ]]; then
  TARGET_DIR="$(cd "$EXISTING_DIR" && pwd)"
  IS_UPDATE=1
  echo "Bestehende ManaVault-Installation gefunden: $TARGET_DIR"
  echo "Sammlung, Decks, Login, Assistent-Konfiguration und alle Dateien unter data/ bleiben erhalten."
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "Diese automatische Installation unterstützt Debian, Ubuntu und darauf basierende Systeme."
  exit 1
fi

echo "Installiere die benötigten Systempakete …"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  git \
  python3 \
  python3-pip \
  python3-venv \
  tesseract-ocr \
  tesseract-ocr-deu \
  tesseract-ocr-eng \
  libgl1 \
  libglib2.0-0

if [[ "$IS_UPDATE" -eq 1 && -f "$TARGET_DIR/data/manavault.sqlite3" ]]; then
  echo "Erstelle vor dem Update eine vollständige Datenbanksicherung …"
  (
    cd "$TARGET_DIR"
    sudo -u "$RUN_USER" bash ./scripts/backup.sh
  )
fi

if [[ "$IS_UPDATE" -eq 1 ]]; then
  systemctl stop "$SERVICE_NAME" manavault-public manavault-remote 2>/dev/null || true
fi

restart_after_error() {
  if [[ "$IS_UPDATE" -eq 1 ]]; then
    echo "Das Update wurde abgebrochen. Die vorhandenen Daten wurden nicht verändert."
    systemctl start "$SERVICE_NAME" manavault-public manavault-remote 2>/dev/null || true
  fi
}
trap restart_after_error ERR

if [[ "$TARGET_DIR" != "$SOURCE_DIR" ]]; then
  echo "Aktualisiere ausschließlich die Programmdateien …"
  for directory in backend frontend scripts deploy docs; do
    install -d -o "$RUN_USER" -g "$RUN_GROUP" "$TARGET_DIR/$directory"
    cp -a "$SOURCE_DIR/$directory/." "$TARGET_DIR/$directory/"
    chown -R "$RUN_USER:$RUN_GROUP" "$TARGET_DIR/$directory"
  done
  for file in INSTALLIEREN.sh README.md CHANGELOG.md CONTRIBUTING.md LICENSE SECURITY.md VERSION requirements.txt .gitignore .gitattributes; do
    if [[ -f "$SOURCE_DIR/$file" ]]; then
      cp -a "$SOURCE_DIR/$file" "$TARGET_DIR/$file"
      chown "$RUN_USER:$RUN_GROUP" "$TARGET_DIR/$file"
    fi
  done
fi

cd "$TARGET_DIR"
chmod +x INSTALLIEREN.sh scripts/*.sh
SUDO_USER="$RUN_USER" ./scripts/install.sh
trap - ERR

echo
if [[ "$IS_UPDATE" -eq 1 ]]; then
  echo "Update abgeschlossen. Alle vorhandenen Daten und Zugangsdaten wurden beibehalten."
else
  echo "Installation abgeschlossen."
  echo "Kartendaten erstmals laden:"
  echo "  ./scripts/import-scryfall.sh"
fi
echo
echo "Optional den ManaVault Assistenten lokal aktivieren:"
echo "  ./scripts/configure-local-ai.sh"
echo "Alternativ mit eigener OpenAI-API-Abrechnung:"
echo "  ./scripts/configure-openai.sh"
