#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

if [ ! -x ".venv/bin/python" ]; then
  echo "Python-Umgebung fehlt."
  exit 1
fi

".venv/bin/python" -m backend.setup_remote_auth
sudo systemctl restart manavault-remote

echo
echo "Login eingerichtet."
echo "Der geschuetzte Funnel kann danach auf http://127.0.0.1:8002 zeigen."
