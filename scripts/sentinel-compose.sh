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
RUNTIME_POINTER="artifacts/sentinel/deployment/validated-runtime.env"
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
EXPLAIN=0
RUN=0
INITIALIZE_BACKUP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --explain) EXPLAIN=1; shift ;;
    --initialize-backup) INITIALIZE_BACKUP=1; shift ;;
    --run) RUN=1; shift; break ;;
    *) break ;;
  esac
done

note() { [ "$EXPLAIN" -eq 1 ] && printf '%s\n' "$*" >&2 || true; }

"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

# Successful GO validation atomically writes one non-secret immutable runtime
# selector. Prefer it over shell/.env state so an old operator export cannot
# silently resurrect a stale image. This is selection only; feed writers still
# pass sentinel_feed_gate.py against clean HEAD below on every mutation.
if [ -f "$RUNTIME_POINTER" ]; then
  VALIDATED_RUNTIME_REF="$(
    "$PYTHON" - "$RUNTIME_POINTER" <<'PY'
import pathlib,re,sys
path=pathlib.Path(sys.argv[1])
try:
    lines=path.read_text(encoding='ascii').splitlines()
except OSError:
    raise SystemExit(2)
if len(lines) != 1:
    raise SystemExit(2)
prefix='SENTINEL_RUNTIME_IMAGE_REF='
if not lines[0].startswith(prefix):
    raise SystemExit(2)
value=lines[0][len(prefix):]
if re.fullmatch(r'sha256:[0-9a-f]{64}', value) is None:
    raise SystemExit(2)
print(value)
PY
  )" || {
    echo "REFUSED: validated Sentinel runtime pointer is malformed" >&2
    exit 2
  }
  SENTINEL_RUNTIME_IMAGE_REF="$VALIDATED_RUNTIME_REF"
  export SENTINEL_RUNTIME_IMAGE_REF
  note "validated runtime selector active"
fi

[ -n "${SENTINEL_BACKUP_DIR:-}" ] || {
  echo "REFUSED: SENTINEL_BACKUP_DIR is required; every supported Sentinel" >&2
  echo "Compose invocation includes continuous WAL archiving" >&2
  exit 2
}

# One explicit provisioning command installs the durable-target marker only
# while the operator has verified that the intended external filesystem is
# mounted. Ordinary starts and restarts only verify that retained marker.
if [ "$INITIALIZE_BACKUP" -eq 1 ]; then
  [ "$RUN" -eq 0 ] && [ "$#" -eq 0 ] || {
    echo "REFUSED: --initialize-backup may not be combined with a Compose command" >&2
    exit 2
  }
  . scripts/sentinel-backup-lib.sh
  INITIALIZED_ROOT="$(sentinel_backup_root --initialize-markers)"
  printf 'initialized_backup_target:%s\n' "$INITIALIZED_ROOT"
  exit 0
fi

if [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ] && \
   [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
  echo "REFUSED: CPU-limit force modes are mutually exclusive" >&2
  exit 2
elif [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
  note "SENTINEL_FORCE_NO_CPU_LIMITS=1 - CPU observed, not bounded"
  mkdir -p "$(dirname "$GENERATED")"
  "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" \
    >&2 || { echo "could not generate the CPU-free compose file" >&2; exit 1; }
  COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED" -f "$BACKUP")
elif [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ]; then
  note "SENTINEL_FORCE_CPU_LIMITS=1 - canonical CPU limits"
  COMPOSE_ARGS=(-f "$CANONICAL" -f "$BACKUP")
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
  else
    note "CPU quota UNSUPPORTED - generating CPU-free deployment"
    mkdir -p "$(dirname "$GENERATED")"
    "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" \
      >&2 || { echo "could not generate the CPU-free compose file" >&2; exit 1; }
    COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED" -f "$BACKUP")
  fi
fi

if [ "$RUN" -eq 1 ]; then
  . scripts/sentinel-backup-lib.sh
  sentinel_backup_root >/dev/null

  # A digest makes an image immutable; it does not authorize that image to
  # mutate the CURRENT checkout's corpus.  Resolve the image exactly as Compose
  # will, then bind feed writers to clean HEAD before the container or database
  # is touched.  Dedicated feed variables are never inherited accidentally by
  # a non-feed command.
  unset SENTINEL_FEED_AUTHORIZED SENTINEL_FEED_SERVICE_MODE \
    SENTINEL_FEED_GIT_COMMIT \
    SENTINEL_FEED_RUNTIME_IMAGE_DIGEST
  set +e
  "$PYTHON" scripts/sentinel_feed_gate.py classify -- "$@" >/dev/null
  FEED_CLASSIFICATION=$?
  set -e
  if [ "$FEED_CLASSIFICATION" -eq 0 ]; then
    COMPOSE_MODEL="$(
      docker compose "${COMPOSE_ARGS[@]}" --profile cli config --format json
    )" || {
      echo "REFUSED: Compose could not resolve the selected Sentinel image" >&2
      exit 2
    }
    RESOLVED_IMAGE="$(printf '%s' "$COMPOSE_MODEL" | "$PYTHON" -c \
      'import json,sys
model=json.load(sys.stdin)
service=(model.get("services") or {}).get("sentinel") or {}
image=service.get("image")
if not isinstance(image,str) or not image.strip():
    raise SystemExit("REFUSED: Compose model has no exact sentinel image")
print(image.strip())')" || exit 2
    mapfile -t FEED_BINDING < <(
      "$PYTHON" scripts/sentinel_feed_gate.py bind \
        --repo "$(pwd -P)" --image "$RESOLVED_IMAGE"
    )
    [ "${#FEED_BINDING[@]}" -eq 2 ] || {
      echo "REFUSED: feed image/source binding was not established" >&2
      exit 2
    }
    SENTINEL_GIT_COMMIT="${FEED_BINDING[0]}"
    SENTINEL_RUNTIME_IMAGE_DIGEST="${FEED_BINDING[1]}"
    SENTINEL_FEED_AUTHORIZED="CLEAN_HEAD_IMAGE_V1"
    SENTINEL_FEED_GIT_COMMIT="$SENTINEL_GIT_COMMIT"
    SENTINEL_FEED_RUNTIME_IMAGE_DIGEST="$SENTINEL_RUNTIME_IMAGE_DIGEST"
    export SENTINEL_GIT_COMMIT SENTINEL_RUNTIME_IMAGE_DIGEST
    export SENTINEL_FEED_AUTHORIZED SENTINEL_FEED_GIT_COMMIT
    export SENTINEL_FEED_RUNTIME_IMAGE_DIGEST
    # Keep the ordinary Compose service free of standing artifact authority.
    # These five values cross the membrane only on this already-classified,
    # host-authorized `compose run` invocation.
    RUN_ARGS=(
      run
      --env SENTINEL_GIT_COMMIT
      --env SENTINEL_RUNTIME_IMAGE_DIGEST
      --env SENTINEL_FEED_AUTHORIZED
      --env SENTINEL_FEED_GIT_COMMIT
      --env SENTINEL_FEED_RUNTIME_IMAGE_DIGEST
      "${@:2}"
    )
    exec docker compose "${COMPOSE_ARGS[@]}" "${RUN_ARGS[@]}"
  elif [ "$FEED_CLASSIFICATION" -ne 1 ]; then
    exit "$FEED_CLASSIFICATION"
  fi
  exec docker compose "${COMPOSE_ARGS[@]}" "$@"
fi

# Compatibility/inspection output only. Production callers use --run so a
# refusal cannot degrade into an empty argument list and default Compose graph.
printf '%q ' "${COMPOSE_ARGS[@]}"
