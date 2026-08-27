#!/usr/bin/env bash
# One-command NAS financial validation with a certified, bounded preparation.
#
# The Python producer parses .env literally; this launcher never sources it and
# therefore never evaluates or echoes a credential. Production corpus mutation
# happens only after the exact candidate artifacts pass the stable certification
# boundary installed by the phased GO entry.
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

PRODUCTION_RUN=1
for ARG in "$@"; do
  case "$ARG" in
    --input|--input=*|--dev-input) PRODUCTION_RUN=0 ;;
  esac
done

# Retained certification/retry evidence and exact post-validation handoff are
# bound to the current Linux boot. This is a deterministic prerequisite, so
# prove it before any long image build/test work. Development input is neither
# retained nor promoted and does not need the production host binding.
if [ "$PRODUCTION_RUN" -eq 1 ]; then
  "$PYTHON" scripts/sentinel_go_host_preflight.py
fi

# Surface ordinary-runtime drift cheaply. A stale prior runtime is diagnostic,
# never authority: promotion occurs only after the requested GO target passes.
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

# A broker-capable target needs a usable PAPER account. Prove that cheap,
# GET-only volatile prerequisite before starting the multi-image/full-suite work.
# It is re-observed again at the final verdict boundary; this early pass is only
# a liveness filter and never retained as final account authority. SHADOW skips.
if [ "$PRODUCTION_RUN" -eq 1 ]; then
  "$PYTHON" scripts/sentinel_go_account_preflight.py "$@"
fi

set +e
"$PYTHON" scripts/sentinel_go_verified_entry.py "$@"
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
  # Recreate the read-only panel on the promoted runtime and record the local
  # certified image IDs that autonomous deployment must promote unchanged to
  # registry RepoDigests before any broker-authorized service can use them.
  "$PYTHON" scripts/sentinel_go_post_validate.py || exit $?
fi
