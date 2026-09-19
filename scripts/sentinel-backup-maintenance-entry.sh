#!/usr/bin/env bash
# Internal child: all preflight, lock and backup work is process-supervised.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null
. scripts/sentinel-env.sh
sentinel_load_environment --profile maintenance
. scripts/sentinel-backup-lib.sh
export SENTINEL_BASE_BACKUP_LOCK_ROOT="$(sentinel_backup_root)"
exec "$PYTHON" scripts/sentinel_backup_lock.py hold \
  "$PYTHON" scripts/sentinel_backup_maintenance.py --worker
