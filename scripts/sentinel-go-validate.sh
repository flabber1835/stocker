#!/usr/bin/env bash
# One-command NAS financial validation with a certified, bounded preparation.
#
# The Python producer parses .env literally; this launcher never sources it and
# therefore never evaluates or echoes a credential. Production corpus mutation
# happens only after the exact candidate artifacts pass the stable certification
# boundary inside sentinel_go_phase_controller.py.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

# Surface ordinary-runtime drift cheaply. A stale prior runtime is diagnostic,
# never authority: promotion occurs only after the requested GO target passes.
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

set +e
"$PYTHON" scripts/sentinel_go_phase_controller.py "$@"
VALIDATION_RC=$?
set -e

if [ "$VALIDATION_RC" -ne 0 ]; then
  exit "$VALIDATION_RC"
fi

# Successful production validation leaves ordinary Sentinel Compose bound to
# the exact validated candidate. Development input is skipped by the helper.
"$PYTHON" scripts/sentinel_runtime_selection.py promote -- "$@" || exit $?
