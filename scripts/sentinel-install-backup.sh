#!/usr/bin/env bash
# One owner covers base creation, chain check and the selected restore milestone.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
. scripts/sentinel-env.sh
sentinel_load_environment --profile maintenance
. scripts/sentinel-backup-lib.sh
export SENTINEL_BASE_BACKUP_LOCK_ROOT="$(sentinel_backup_root)"
exec "$PYTHON" scripts/sentinel_backup_lock.py hold --wait-seconds 3660 \
  "$PYTHON" scripts/sentinel_install_backup.py "$@"
