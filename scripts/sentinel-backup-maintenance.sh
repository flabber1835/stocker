#!/usr/bin/env bash
# DSM/host scheduler entry point. No broker credentials or broker calls.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null
. scripts/sentinel-env.sh
sentinel_load_environment --profile maintenance
. scripts/sentinel-backup-lib.sh
export SENTINEL_BASE_BACKUP_LOCK_ROOT="$(sentinel_backup_root)"
if [ "${1:-}" = --loop ] && [ "$#" -eq 1 ]; then
  exec "$PYTHON" scripts/sentinel_backup_maintenance.py --loop
fi
exec "$PYTHON" scripts/sentinel_backup_lock.py hold \
  "$PYTHON" scripts/sentinel_backup_maintenance.py "$@"
