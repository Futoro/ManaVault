#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export TARGET_VERSION="0.1.83"
exec bash "$SCRIPT_DIR/update-linux-0.1.71-to-0.1.76.sh" "$@"
