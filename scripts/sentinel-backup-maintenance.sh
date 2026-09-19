#!/usr/bin/env bash
# Invoke every five minutes and at NAS startup; no broker operations.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
exec "$PYTHON" scripts/sentinel_backup_maintenance.py "$@"
