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

case "${SENTINEL_GO_TARGET:-DUAL_RUN_OBSERVATION}" in
  SHADOW|DUAL_RUN_OBSERVATION|HISTORICAL_PAPER_EXECUTION) ;;
  *)
    echo "REFUSED: SENTINEL_GO_TARGET must be SHADOW, DUAL_RUN_OBSERVATION, or HISTORICAL_PAPER_EXECUTION" >&2
    exit 2
    ;;
esac

# Surface ordinary-runtime drift cheaply. A stale prior runtime is diagnostic,
# never authority: promotion occurs only after the requested GO target passes.
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

PRODUCTION_RUN=1
for ARG in "$@"; do
  case "$ARG" in
    --input|--input=*|--dev-input) PRODUCTION_RUN=0 ;;
  esac
done

set +e
"$PYTHON" scripts/sentinel_go_phase_entry.py "$@"
VALIDATION_RC=$?
set -e

if [ "$VALIDATION_RC" -ne 0 ]; then
  exit "$VALIDATION_RC"
fi

# Successful production validation leaves ordinary Sentinel Compose bound to
# the exact validated candidate. The promotion helper refreshes origin/main at
# this final boundary so a long validation cannot promote a commit superseded
# upstream while the suite was running.
"$PYTHON" scripts/sentinel_runtime_selection.py promote -- "$@" || exit $?

if [ "$PRODUCTION_RUN" -eq 1 ]; then
  # Recreate the read-only panel on the promoted runtime, write an explicit
  # exact authorized/test image-id handoff record, and garbage-collect only old
  # GO scratch tags that Docker confirms are not in use.
  "$PYTHON" scripts/sentinel_go_post_validate.py || exit $?
fi
