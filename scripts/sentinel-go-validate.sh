#!/usr/bin/env bash
# One-command NAS financial validation with a certified, bounded preparation.
#
# The Python producer parses .env literally; this launcher never sources it and
# therefore never evaluates or echoes a credential. Production corpus mutation
# happens only after the exact candidate artifacts pass the stable certification
# boundary installed by sentinel_go_phase_entry.py.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

# Serialize the entire lifecycle, not just the mutable database phase. Two GO
# processes building the same commit-scoped tags or racing cache/promotion files
# would invalidate single-process identity reasoning even if PostgreSQL itself
# serialized market-data writes.
if [ "${SENTINEL_GO_LOCK_HELD:-0}" != "1" ]; then
  exec "$PYTHON" scripts/sentinel_go_lock.py \
    bash scripts/sentinel-go-validate.sh "$@"
fi

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

# Promotion re-fetches origin/main and requires the ordinary tag to resolve to
# the exact immutable image id recorded when the certification suite passed.
# A same-revision retag/substitution therefore cannot cross this boundary.
"$PYTHON" scripts/sentinel_go_promote.py "$@" || exit $?

if [ "$PRODUCTION_RUN" -eq 1 ]; then
  # Recreate the read-only panel on the promoted runtime and write the exact
  # authorized/test image-id handoff required by the signed activation wrapper.
  "$PYTHON" scripts/sentinel_go_post_validate.py || exit $?
fi
