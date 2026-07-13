#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PYTHON_BIN="${PYTHON_BIN:-python3}"
BACKUP_DIR="${MANAVAULT_BACKUP_DIR:-data/backups}"
KEEP_LOCAL_BACKUPS="${MANAVAULT_KEEP_LOCAL_BACKUPS:-14}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"

mkdir -p "$BACKUP_DIR"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="$PYTHON_BIN"
fi

BACKUP_PATH="$("$PYTHON" -c '
from datetime import datetime
from pathlib import Path
import sqlite3

db_path = Path("data/manavault.sqlite3")
backup_dir = Path("'"$BACKUP_DIR"'")
backup_dir.mkdir(parents=True, exist_ok=True)
backup_path = backup_dir / f"manavault-auto-{datetime.now():%Y%m%d-%H%M%S}.sqlite3"
if not db_path.exists():
    raise SystemExit("data/manavault.sqlite3 wurde nicht gefunden.")
with sqlite3.connect(db_path, timeout=30) as source:
    with sqlite3.connect(backup_path) as target:
        source.backup(target)
print(backup_path)
')"

echo "Backup erstellt: $BACKUP_PATH"

find "$BACKUP_DIR" -maxdepth 1 -name "manavault-auto-*.sqlite3" -type f -printf "%T@ %p\n" \
  | sort -nr \
  | tail -n "+$((KEEP_LOCAL_BACKUPS + 1))" \
  | cut -d " " -f 2- \
  | while IFS= read -r old_backup; do
      rm -f "$old_backup"
    done

if [ -n "$RCLONE_REMOTE" ]; then
  if ! command -v rclone >/dev/null 2>&1; then
    echo "rclone wurde nicht gefunden. Installiere es mit: sudo apt install rclone"
    exit 1
  fi
  rclone copy "$BACKUP_PATH" "$RCLONE_REMOTE"
  echo "Backup zu $RCLONE_REMOTE kopiert."
fi
