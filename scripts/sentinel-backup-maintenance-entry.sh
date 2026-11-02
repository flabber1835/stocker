#!/usr/bin/env bash
# Internal child: all preflight, lock and backup work is process-supervised.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null
. scripts/sentinel-env.sh
sentinel_load_environment --profile maintenance
# Capacity is independent of the USB and must publish before media admission.
# This is one child of the existing bounded maintenance invocation, not a loop.
if ! "$PYTHON" scripts/sentinel_backup_capacity.py; then
  echo 'SENTINEL_BACKUP_CONTINUITY_CAPACITY=UNAVAILABLE' >&2
fi
. scripts/sentinel-backup-lib.sh
export SENTINEL_BASE_BACKUP_LOCK_ROOT="$(sentinel_backup_root)"
exec "$PYTHON" scripts/sentinel_backup_lock.py hold --standby-if-busy \
  "$PYTHON" scripts/sentinel_backup_maintenance.py "$@"
