#!/usr/bin/env bash
# Fast, non-authoritative Sentinel bring-up loop.
#
# This path exists only to shorten bootstrap/debug iteration. It may perform the
# same bounded market-data preparation as certified GO when --recover is given,
# but it can never certify, promote, emit a GO bundle, or authorize broker work.
# Final deployment still requires scripts/sentinel-go-validate.sh.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"

phase() { printf '\n=== BRINGUP: %s ===\n' "$1"; }

phase "HOST PYTHON"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null

# Share the exact GO lifecycle lock. Bring-up data repair and certified GO must
# never race each other on image tags, backup state, or the financial database.
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

# Use the previously validated ordinary runtime only as a negative liveness
# filter. It has no network and can never authorize recovery. If it says the
# newest closed session has not reached the reviewed Sharadar source-final
# boundary, stop before building a new exact-current image. READY merely allows
# the current-commit authoritative checks below to proceed.
phase "SOURCE-FINAL HINT - NO NETWORK"
"$PYTHON" scripts/sentinel_bringup_source_hint.py

phase "DATA + RECOVERY BRING-UP"
exec "$PYTHON" scripts/sentinel_bringup.py "$@"
