#!/usr/bin/env bash
# One-command NAS financial validation with a certified, bounded preparation.
#
# The Python producer parses .env literally; this launcher never sources it and
# therefore never evaluates or echoes a credential. Production corpus mutation
# happens only after the exact candidate artifacts pass the stable certification
# boundary installed by the phased GO entry.
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

if [ "$PRODUCTION_RUN" -eq 1 ]; then
  go_phase "HOST GO IDENTITY PREFLIGHT"
  "$PYTHON" scripts/sentinel_go_host_preflight.py
fi

go_phase "RUNTIME SELECTION PREFLIGHT"
"$PYTHON" scripts/sentinel_runtime_selection.py preflight

if [ "$PRODUCTION_RUN" -eq 1 ]; then
  go_phase "PAPER ACCOUNT PREFLIGHT - GET ONLY"
  "$PYTHON" scripts/sentinel_go_account_preflight.py "$@"
fi

# Diagnostic only. A just-closed session that has not reached the reviewed
# Sharadar source-final boundary is a legitimate waiting state. The 24x7 entry
# certifies the newest causally final frontier and leaves the newer session for
# the deployment/runtime catch-up boundary.
if [ "$PRODUCTION_RUN" -eq 1 ]; then
  go_phase "READ-ONLY SHARADAR PREFLIGHT"
  "$PYTHON" scripts/sentinel_go_readonly_data_preflight.py
fi

go_phase "CERTIFICATION + FINANCIAL READINESS"
set +e
"$PYTHON" scripts/sentinel_go_24x7_entry.py "$@"
VALIDATION_RC=$?
set -e

if [ "$VALIDATION_RC" -ne 0 ]; then
  go_warn "GO validation returned NO_GO/REFUSED (exit $VALIDATION_RC)"
  exit "$VALIDATION_RC"
fi

go_phase "PROMOTE EXACT CERTIFIED RUNTIME"
set +e
"$PYTHON" scripts/sentinel_go_promote.py "$@"
PROMOTE_RC=$?
set -e
if [ "$PROMOTE_RC" -ne 0 ]; then
  go_error "certified runtime promotion failed (exit $PROMOTE_RC)"
  exit "$PROMOTE_RC"
fi

if [ "$PRODUCTION_RUN" -eq 1 ]; then
  go_phase "POST-VALIDATION HANDOFF"
  set +e
  "$PYTHON" scripts/sentinel_go_post_validate.py
  POST_RC=$?
  set -e
  if [ "$POST_RC" -ne 0 ]; then
    go_error "post-validation handoff failed (exit $POST_RC)"
    exit "$POST_RC"
  fi
fi

go_info "GO lifecycle completed successfully"
