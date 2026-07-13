#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_VERSION="${TARGET_VERSION:-0.1.76}"
SERVICE_NAME="${MANAVAULT_SERVICE_NAME:-manavault}"
APP_DIR="${MANAVAULT_DIR:-$HOME/MagicVault}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE="${1:-$SCRIPT_DIR/ManaVault-linux-server-${TARGET_VERSION}.zip}"
SERVICE_STOPPED=0
PUBLIC_SERVICE_NAME="${MANAVAULT_PUBLIC_SERVICE_NAME:-manavault-public}"

on_error() {
  local exit_code=$?
  echo
  echo "Update fehlgeschlagen (Fehlercode ${exit_code})."
  echo "Deine Sicherung liegt in: ${APP_DIR}/data/backups"
  if [ "$SERVICE_STOPPED" -eq 1 ]; then
    echo "ManaVault wird wieder gestartet ..."
    sudo systemctl start "$SERVICE_NAME" || true
    sudo systemctl start "$PUBLIC_SERVICE_NAME" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap on_error ERR

if [ "$(id -u)" -eq 0 ]; then
  echo "Bitte dieses Skript als normaler Benutzer starten, nicht mit sudo."
  echo "Das Skript fragt sudo nur fuer systemctl ab."
  exit 1
fi

if [ ! -d "$APP_DIR" ]; then
  echo "ManaVault-Verzeichnis nicht gefunden: $APP_DIR"
  exit 1
fi

if [ ! -f "$ARCHIVE" ]; then
  echo "Update-ZIP nicht gefunden: $ARCHIVE"
  echo
  echo "Lege diese beiden Dateien in denselben Ordner:"
  echo "  $(basename "$0")"
  echo "  ManaVault-linux-server-${TARGET_VERSION}.zip"
  exit 1
fi

for command in unzip python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Benoetigter Befehl fehlt: $command"
    echo "Installation: sudo apt update && sudo apt install -y unzip python3 python3-venv python3-pip"
    exit 1
  fi
done

archive_version="$(unzip -p "$ARCHIVE" VERSION 2>/dev/null | tr -d '\r\n')"
if [ "$archive_version" != "$TARGET_VERSION" ]; then
  echo "Falsches Update-ZIP: erwartet ${TARGET_VERSION}, gefunden ${archive_version:-unbekannt}."
  exit 1
fi

echo "ManaVault Update auf Version ${TARGET_VERSION}"
echo "Installation: $APP_DIR"
echo

cd "$APP_DIR"

echo "[1/8] Datenbank sichern ..."
chmod +x backup-linux.sh
./backup-linux.sh

echo "[2/8] ManaVault-Dienste stoppen ..."
sudo systemctl stop "$PUBLIC_SERVICE_NAME" 2>/dev/null || true
sudo systemctl stop "$SERVICE_NAME"
SERVICE_STOPPED=1

echo "[3/8] Programmdateien aktualisieren ..."
unzip -o "$ARCHIVE" -d "$APP_DIR"
chmod +x ./*.sh

echo "[4/8] Python-Umgebung und Abhaengigkeiten aktualisieren ..."
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

echo "[5/8] Datenbankstruktur aktualisieren ..."
".venv/bin/python" -c "from backend.main import init_db; init_db(); print('Datenbank ist aktuell.')"

echo "[6/8] Tokens, Embleme und Karten-Token-Beziehungen aktualisieren ..."
".venv/bin/python" -m backend.import_scryfall --tokens-only

echo "[7/8] ManaVault starten und pruefen ..."
sudo systemctl start "$SERVICE_NAME"
SERVICE_STOPPED=0

if ! sudo systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "Der Dienst konnte nicht gestartet werden."
  sudo systemctl status "$SERVICE_NAME" --no-pager -l || true
  exit 1
fi

echo "[8/8] Sichere oeffentliche Deckansicht installieren ..."
sudo ./install-linux-public-service.sh
if ! sudo systemctl is-active --quiet "$PUBLIC_SERVICE_NAME"; then
  echo "Die oeffentliche Deckansicht konnte nicht gestartet werden."
  sudo systemctl status "$PUBLIC_SERVICE_NAME" --no-pager -l || true
  exit 1
fi

installed_version="$(tr -d '\r\n' < VERSION)"
if [ "$installed_version" != "$TARGET_VERSION" ]; then
  echo "Unerwartete installierte Version: $installed_version"
  exit 1
fi

trap - ERR
echo
echo "Update erfolgreich: ManaVault ${installed_version} laeuft."
echo "Status:"
sudo systemctl status "$SERVICE_NAME" --no-pager -l
echo
echo "Danach ManaVault im Browser einmal vollstaendig neu laden."
