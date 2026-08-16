#!/usr/bin/env bash
# Resolve and, preferably, execute the one supported Sentinel Compose graph.
# Every graph includes the required WAL-archive overlay. `--automation-overlay`
# adds the signed-authority/automation services through the SAME host-capability
# decision, so ordinary, authorized-CLI and unattended paths cannot disagree on
# whether CPU CFS limits are usable.
set -euo pipefail

cd "$(dirname "$0")/.."

CANONICAL="docker-compose.sentinel.yml"
BACKUP="docker-compose.sentinel-backup.yml"
AUTOMATION="docker-compose.sentinel-automation.yml"
GENERATED="artifacts/compose/docker-compose.sentinel.nocpu.yml"
GENERATED_AUTOMATION="artifacts/compose/docker-compose.sentinel-automation.nocpu.yml"
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
EXPLAIN=0
RUN=0
INCLUDE_AUTOMATION=0

while [ $# -gt 0 ]; do
  case "$1" in
    --explain) EXPLAIN=1; shift ;;
    --automation-overlay) INCLUDE_AUTOMATION=1; shift ;;
    --run) RUN=1; shift; break ;;
    *) break ;;
  esac
done

note() { [ "$EXPLAIN" -eq 1 ] && printf '%s\n' "$*" >&2 || true; }

"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

[ -n "${SENTINEL_BACKUP_DIR:-}" ] || {
  echo "REFUSED: SENTINEL_BACKUP_DIR is required; every supported Sentinel" >&2
  echo "Compose invocation includes continuous WAL archiving" >&2
  exit 2
}

append_automation_overlay() {
  if [ "$INCLUDE_AUTOMATION" -eq 1 ]; then
    COMPOSE_ARGS+=(-f "$1")
  fi
}

generate_cpu_free_graph() {
  mkdir -p "$(dirname "$GENERATED")"
  "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" \
    >&2 || { echo "could not generate the CPU-free compose file" >&2; exit 1; }
  if [ "$INCLUDE_AUTOMATION" -eq 1 ]; then
    "$PYTHON" scripts/sentinel_strip_cpu_limits.py \
      "$AUTOMATION" "$GENERATED_AUTOMATION" >&2 || {
        echo "could not generate the CPU-free automation overlay" >&2
        exit 1
      }
  fi
}

if [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ] && \
   [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
  echo "REFUSED: CPU-limit force modes are mutually exclusive" >&2
  exit 2
elif [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
  note "SENTINEL_FORCE_NO_CPU_LIMITS=1 - CPU observed, not bounded"
  generate_cpu_free_graph
  COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED" -f "$BACKUP")
  append_automation_overlay "$GENERATED_AUTOMATION"
elif [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ]; then
  note "SENTINEL_FORCE_CPU_LIMITS=1 - canonical CPU limits"
  COMPOSE_ARGS=(-f "$CANONICAL" -f "$BACKUP")
  append_automation_overlay "$AUTOMATION"
else
  CAPS="$("$PYTHON" scripts/sentinel_host_capabilities.py --json 2>/dev/null || echo '{}')"
  USABLE="$(printf '%s' "$CAPS" | "$PYTHON" -c \
    'import json,sys
try: d=json.load(sys.stdin)
except ValueError: d={}
print("1" if d.get("cpu_limits_usable", True) else "0")' \
    2>/dev/null || echo 1)"
  if [ "$USABLE" = "1" ]; then
    note "CPU quota ENFORCED - canonical deployment"
    COMPOSE_ARGS=(-f "$CANONICAL" -f "$BACKUP")
    append_automation_overlay "$AUTOMATION"
  else
    note "CPU quota UNSUPPORTED - generating CPU-free deployment"
    generate_cpu_free_graph
    COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED" -f "$BACKUP")
    append_automation_overlay "$GENERATED_AUTOMATION"
  fi
fi

if [ "$RUN" -eq 1 ]; then
  . scripts/sentinel-backup-lib.sh
  sentinel_backup_root >/dev/null

  # `docker compose run` does not inherit arbitrary host variables into the
  # service. The candidate builder deliberately obtains deployment artifacts
  # from process environment, so pass the three measured identities whenever
  # the operator has set them. Signed-authority services already bind the same
  # variables in their explicit overlay; this path fixes ordinary run-only
  # candidate creation without weakening their required-value checks.
  if [ "${1:-}" = "run" ]; then
    shift
    RUN_ENV=()
    [ -z "${SENTINEL_GIT_COMMIT:-}" ] || RUN_ENV+=(-e SENTINEL_GIT_COMMIT)
    [ -z "${SENTINEL_RUNTIME_IMAGE_DIGEST:-}" ] || \
      RUN_ENV+=(-e SENTINEL_RUNTIME_IMAGE_DIGEST)
    [ -z "${SENTINEL_TEST_IMAGE_DIGEST:-}" ] || \
      RUN_ENV+=(-e SENTINEL_TEST_IMAGE_DIGEST)
    exec docker compose "${COMPOSE_ARGS[@]}" run "${RUN_ENV[@]}" "$@"
  fi

  exec docker compose "${COMPOSE_ARGS[@]}" "$@"
fi

# Compatibility/inspection output only. Production callers use --run so a
# refusal cannot degrade into an empty argument list and default Compose graph.
printf '%q ' "${COMPOSE_ARGS[@]}"
