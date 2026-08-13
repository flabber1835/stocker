#!/usr/bin/env bash
# Resolve and, preferably, execute the one supported Sentinel Compose graph.
# Every graph includes the required WAL-archive overlay.  `--run` preserves a
# validation failure as the command's exit status; callers must not hide it in
# command substitution.
set -euo pipefail

cd "$(dirname "$0")/.."

CANONICAL="docker-compose.sentinel.yml"
BACKUP="docker-compose.sentinel-backup.yml"
GENERATED="artifacts/compose/docker-compose.sentinel.nocpu.yml"
EXPLAIN=0
RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --explain) EXPLAIN=1; shift ;;
    --run) RUN=1; shift; break ;;
    *) break ;;
  esac
done

note() { [ "$EXPLAIN" -eq 1 ] && printf '%s\n' "$*" >&2 || true; }

[ -n "${SENTINEL_BACKUP_DIR:-}" ] || {
  echo "REFUSED: SENTINEL_BACKUP_DIR is required; every supported Sentinel" >&2
  echo "Compose invocation includes continuous WAL archiving" >&2
  exit 2
}

if [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ]; then
  note "SENTINEL_FORCE_CPU_LIMITS=1 - canonical CPU limits"
  COMPOSE_ARGS=(-f "$CANONICAL" -f "$BACKUP")
else
  CAPS="$(python3 scripts/sentinel_host_capabilities.py --json 2>/dev/null || echo '{}')"
  USABLE="$(printf '%s' "$CAPS" | python3 -c \
    'import json,sys
try: d=json.load(sys.stdin)
except ValueError: d={}
print("1" if d.get("cpu_limits_usable", True) else "0")' \
    2>/dev/null || echo 1)"
  if [ "$USABLE" = "1" ]; then
    note "CPU quota ENFORCED - canonical deployment"
    COMPOSE_ARGS=(-f "$CANONICAL" -f "$BACKUP")
  else
    note "CPU quota UNSUPPORTED - generating CPU-free deployment"
    mkdir -p "$(dirname "$GENERATED")"
    python3 scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" \
      >&2 || { echo "could not generate the CPU-free compose file" >&2; exit 1; }
    COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED" -f "$BACKUP")
  fi
fi

if [ "$RUN" -eq 1 ]; then
  . scripts/sentinel-backup-lib.sh
  sentinel_backup_root >/dev/null
  exec docker compose "${COMPOSE_ARGS[@]}" "$@"
fi

# Compatibility/inspection output only. Production callers use --run so a
# refusal cannot degrade into an empty argument list and default Compose graph.
printf '%q ' "${COMPOSE_ARGS[@]}"
