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

# The production entrypoint reuses sentinel_feed_gate.py to bind the one
# prevalidation corpus mutation to clean HEAD and the exact candidate image.
exec "$PYTHON" scripts/sentinel_go_validate_entry.py "$@"
