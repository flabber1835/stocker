#!/usr/bin/env bash
# One-command NAS financial validation with a certified, bounded preparation.
#
# The Python producer parses .env literally; this launcher never sources it and
# therefore never evaluates or echoes a credential. Production corpus mutation
# happens only after the exact candidate artifacts pass the stable certification
# boundary installed by the phased GO entry.
#
# The lower-level scripts/sentinel_go_validate.py producer is deliberately not
# invoked directly. Production enters only through sentinel_go_verified_entry.py.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  GO_CYAN='\033[1;36m'
  GO_GREEN='\033[1;32m'
  GO_YELLOW='\033[1;33m'
  GO_RED='\033[1;31m'
  GO_RESET='\033[0m'
else
  GO_CYAN=''
  GO_GREEN=''
  GO_YELLOW=''
  GO_RED=''
  GO_RESET=''
fi

go_phase() {
  printf '\n%b=== %s ===%b\n' "$GO_CYAN" "$1" "$GO_RESET"
}

go_info() {
  printf '%b[GO]%b %s\n' "$GO_GREEN" "$GO_RESET" "$1"
}

go_warn() {
  printf '%b[WARN]%b %s\n' "$GO_YELLOW" "$GO_RESET" "$1" >&2
}

go_error() {
  printf '%b[ERROR]%b %s\n' "$GO_RED" "$GO_RESET" "$1" >&2
}

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
go_phase "HOST COMPATIBILITY"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  go_error "host Python is incompatible; minimum Python is 3.8.15"
  exit 1
}
go_info "host Python compatibility passed"

# Serialize the entire lifecycle, not just the mutable database phase. Two GO
# processes building the same commit-scoped tags or racing cache/promotion files
# would invalidate single-process identity reasoning even if PostgreSQL itself
# serialized market-data writes.
if [ "${SENTINEL_GO_LOCK_HELD:-0}" != "1" ]; then
  go_phase "ACQUIRE SINGLE GO LIFECYCLE LOCK"
  exec "$PYTHON" scripts/sentinel_go_lock.py \
    bash scripts/sentinel-go-validate.sh "$@"
fi

go_info "GO lifecycle lock held"

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
  go_phase "HOST GO IDENTITY PREFLIGHT"
  "$PYTHON" scripts/sentinel_go_host_preflight.py
fi

# Surface ordinary-runtime drift cheaply. A stale prior runtime is diagnostic,
# never authority: promotion occurs only after the requested GO target passes.
go_phase "RUNTIME SELECTION PREFLIGHT"
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

# A broker-capable target needs a usable PAPER account. Prove that cheap,
# GET-only volatile prerequisite before starting image/test work. It is
# re-observed again at the final verdict boundary; this early pass is only a
# liveness filter and never retained as final account authority. SHADOW skips.
if [ "$PRODUCTION_RUN" -eq 1 ]; then
  go_phase "PAPER ACCOUNT PREFLIGHT - GET ONLY"
  "$PYTHON" scripts/sentinel_go_account_preflight.py "$@"
fi

# Before the multi-image/full-suite certification, build only the exact ordinary
# runtime and use it for a READ-ONLY diagnostic of the current SEP CDC interval.
# This catches deterministic cursor/source authority refusals early without
# allowing uncertified code to create schema, advance cursors, renormalize bars,
# or publish a corpus generation. The certified preparation still repeats the
# source observation later at the real write boundary.
if [ "$PRODUCTION_RUN" -eq 1 ]; then
  go_phase "READ-ONLY SHARADAR PREFLIGHT"
  "$PYTHON" scripts/sentinel_go_readonly_data_preflight.py
fi

go_phase "CERTIFICATION + FINANCIAL READINESS"
set +e
"$PYTHON" scripts/sentinel_go_verified_entry.py "$@"
VALIDATION_RC=$?
set -e

if [ "$VALIDATION_RC" -ne 0 ]; then
  go_warn "GO validation returned NO_GO/REFUSED (exit $VALIDATION_RC)"
  exit "$VALIDATION_RC"
fi

# Promotion re-fetches origin/main and requires the ordinary tag to resolve to
# the exact immutable image id recorded when the certification suite passed.
# A same-revision retag/substitution therefore cannot cross this boundary.
go_phase "PROMOTE EXACT CERTIFIED RUNTIME"
"$PYTHON" scripts/sentinel_go_promote.py "$@" || {
  go_error "certified runtime promotion failed"
  exit $?
}

if [ "$PRODUCTION_RUN" -eq 1 ]; then
  # Recreate the read-only panel on the promoted runtime and record the local
  # certified image IDs that autonomous deployment must promote unchanged to
  # registry RepoDigests before any broker-authorized service can use them.
  go_phase "POST-VALIDATION HANDOFF"
  "$PYTHON" scripts/sentinel_go_post_validate.py || {
    go_error "post-validation handoff failed"
    exit $?
  }
fi

go_info "GO lifecycle completed successfully"
