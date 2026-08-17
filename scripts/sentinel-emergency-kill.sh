#!/usr/bin/env bash
# Minimal risk-reducing automation fence. Deliberately bypasses backup and
# authorized-runtime preflight; it does not contact a broker or mutate one.
set -euo pipefail

cd "$(dirname "$0")/.."

CANONICAL="docker-compose.sentinel.yml"
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
GENERATED=""

cleanup() {
  [ -z "$GENERATED" ] || rm -f "$GENERATED"
}
trap cleanup EXIT

"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}
[ -n "${SENTINEL_POSTGRES_PASSWORD:-}" ] || {
  echo "REFUSED: SENTINEL_POSTGRES_PASSWORD is required to reach the durable automation fence" >&2
  exit 2
}
if [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ] && \
   [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
  echo "REFUSED: CPU-limit force modes are mutually exclusive" >&2
  exit 2
fi

COMPOSE_ARGS=(-f "$CANONICAL")
if [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
  GENERATED="$(mktemp "${TMPDIR:-/tmp}/sentinel-emergency-nocpu.XXXXXX.yml")"
  "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" >&2
  COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED")
elif [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" != "1" ]; then
  CAPS="$("$PYTHON" scripts/sentinel_host_capabilities.py --json 2>/dev/null || echo '{}')"
  USABLE="$(printf '%s' "$CAPS" | "$PYTHON" -c \
    'import json,sys
try: d=json.load(sys.stdin)
except ValueError: d={}
print("1" if d.get("cpu_limits_usable", True) else "0")' \
    2>/dev/null || echo 1)"
  if [ "$USABLE" != "1" ]; then
    GENERATED="$(mktemp "${TMPDIR:-/tmp}/sentinel-emergency-nocpu.XXXXXX.yml")"
    "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" >&2
    COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED")
  fi
fi

# --no-deps is intentional: an emergency fence may use only the already
# running behavioral PostgreSQL service. Starting/recreating deployment or
# backup services would add exactly the dependencies this path removes.
docker compose "${COMPOSE_ARGS[@]}" --profile cli run --rm --no-deps sentinel \
  engage-paper-automation-kill-switch "$@"
