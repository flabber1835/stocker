#!/usr/bin/env bash
# Fast, non-authoritative Sentinel bring-up diagnostics.
#
# This path exists only to shorten bootstrap/debug iteration. It performs cheap
# host/runtime/database/backup and source-liveness checks, but it never mutates
# financial data, certifies, promotes, emits a GO bundle, or authorizes broker
# work. Full source validation, recovery, and certification belong to GO.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"

phase() { printf '\n=== BRINGUP: %s ===\n' "$1"; }

phase "HOST PYTHON"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null

# Share the exact GO lifecycle lock so diagnostic image/backup observations do
# not race a concurrent certified lifecycle.
if [ "${SENTINEL_GO_LOCK_HELD:-0}" != "1" ]; then
  phase "ACQUIRE GO LIFECYCLE LOCK"
  exec "$PYTHON" scripts/sentinel_go_lock.py \
    bash scripts/sentinel-bringup.sh "$@"
fi

phase "CHEAP HOST AUTHORITY"
"$PYTHON" scripts/sentinel_deployment_bootstrap.py
"$PYTHON" scripts/sentinel_go_host_preflight.py
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

phase "PAPER ACCOUNT - GET ONLY"
"$PYTHON" scripts/sentinel_go_account_preflight.py \
  --target DUAL_RUN_OBSERVATION

phase "LOCAL + SOURCE LIVENESS"
exec "$PYTHON" scripts/sentinel_bringup_install_anytime.py "$@"
