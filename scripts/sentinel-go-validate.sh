#!/usr/bin/env bash
# One-command NAS financial validation with a bounded prevalidation DB upgrade.
#
# The Python producer parses .env literally; this launcher never sources it and
# therefore never evaluates or echoes a credential. The candidate runtime may
# migrate schema and run one bounded Sharadar daily ingest before its read-only
# evidence boundary; no production mode accepts a hand-authored PASS input.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

# Surface operational image drift before the expensive candidate builds/tests.
# A stale prior runtime is diagnostic, not authority: the candidate is promoted
# only after successful production validation below.
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

# The production entrypoint wraps scripts/sentinel_go_validate.py and reuses
# sentinel_feed_gate.py to bind the one prevalidation corpus mutation to clean
# HEAD and the exact candidate image.
set +e
"$PYTHON" scripts/sentinel_go_validate_entry.py "$@"
VALIDATION_RC=$?
set -e

if [ "$VALIDATION_RC" -ne 0 ]; then
  exit "$VALIDATION_RC"
fi

# Successful production validation must leave ordinary Sentinel Compose bound
# to the exact ordinary runtime candidate that was just validated. Development
# input runs are explicitly skipped by the helper and can never promote.
"$PYTHON" scripts/sentinel_runtime_selection.py promote -- "$@" || exit $?
