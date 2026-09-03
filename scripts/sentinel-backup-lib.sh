#!/usr/bin/env bash
# Shared validation for backup scripts. Sourced, not invoked.

SENTINEL_BACKUP_TARGET_MARKER=".sentinel-independent-durable-target-v1"
SENTINEL_BACKUP_TARGET_MARKER_CONTENT="sentinel-independent-durable-target-v1"
SENTINEL_BACKUP_POSTGRES_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"

_sentinel_backup_marker_container() {
  local parent="$1"
  local uid="$2"
  local mode="$3"
  local user_args=()
  [ -z "$uid" ] || user_args=(--user "$uid")

  docker run --rm --network none \
    "${user_args[@]}" \
    -e "EXPECTED=$SENTINEL_BACKUP_TARGET_MARKER_CONTENT" \
    -e "MODE=$mode" \
    -v "$parent:/probe" \
    --entrypoint sh \
    "$SENTINEL_BACKUP_POSTGRES_IMAGE" \
    -ceu '
marker=/probe/.sentinel-independent-durable-target-v1

status() {
  if [ -L "$marker" ]; then
    echo INVALID_SYMLINK
    return 3
  fi
  if [ ! -e "$marker" ]; then
    echo MISSING
    return 4
  fi
  if [ ! -f "$marker" ] || [ ! -r "$marker" ]; then
    echo INVALID_TYPE
    return 3
  fi
  content="$(cat "$marker")" || {
    echo INVALID_UNREADABLE
    return 3
  }
  if [ "$content" != "$EXPECTED" ]; then
    echo INVALID_CONTENT
    return 3
  fi
  echo VALID
  return 0
}

if [ "$MODE" = verify ]; then
  status
  exit $?
fi
[ "$MODE" = initialize ] || exit 2

if status >/dev/null 2>&1; then
  echo VALID
  exit 0
else
  rc=$?
fi
[ "$rc" -eq 4 ] || exit "$rc"

tmp="$(mktemp "${marker}.tmp.XXXXXX")"
# The temporary file is unique on every container invocation and lives beside
# the marker so the final hard link remains on one filesystem. Retain one EXIT
# cleanup until publication succeeds.
trap "rm -f \"$tmp\"" 0
umask 022
printf "%s\n" "$EXPECTED" > "$tmp"
chmod 0444 "$tmp"
sync "$tmp"

# link(2) is the atomic create-if-absent boundary. If another initializer won
# the race, verify the winner instead of overwriting it.
if ! ln "$tmp" "$marker" 2>/dev/null; then
  rm -f "$tmp"
  trap - 0
  status
  exit $?
fi
rm -f "$tmp"
trap - 0
sync /probe
status
'
}

sentinel_backup_root() {
  local initialize_markers=0
  if [ "${1:-}" = "--initialize-markers" ]; then
    initialize_markers=1
    shift
  fi
  [ "$#" -eq 0 ] || {
    echo "REFUSED: sentinel_backup_root received unexpected arguments" >&2
    return 2
  }

  local root raw_root repo parent docker_root docker_canonical root_dev docker_dev uid
  local marker_uid marker_status marker_rc marker_mode marker_action
  raw_root="${SENTINEL_BACKUP_DIR:-}"
  root="$raw_root"
  [ -n "$root" ] || {
    echo "REFUSED: set SENTINEL_BACKUP_DIR to a second durable target" >&2
    return 2
  }
  case "$root" in /*) ;; *)
    echo "REFUSED: SENTINEL_BACKUP_DIR must be absolute" >&2; return 2 ;;
  esac
  [ -d "$root" ] || {
    echo "REFUSED: backup root does not exist: $root" >&2; return 2
  }
  [ ! -L "$raw_root" ] || {
    echo "REFUSED: backup root may not be a symlink: $raw_root" >&2; return 2
  }
  root="$(cd "$root" && pwd -P)"
  repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
  case "$root" in
    /|"${HOME:-__unset__}"|"$repo"|"$repo"/*)
      echo "REFUSED: backup root is a protected local path: $root" >&2
      return 2 ;;
  esac
  for parent in "$root/wal" "$root/base"; do
    [ -d "$parent" ] || {
      echo "REFUSED: create the operator-owned directory first: $parent" >&2
      return 2
    }
    [ ! -L "$parent" ] || {
      echo "REFUSED: backup child may not be a symlink: $parent" >&2
      return 2
    }
  done

  # A directory beside Docker's data root is not a second target merely because
  # it has another name. Prove both the path boundary and the backing device,
  # or require an explicit operator attestation for a remote/durable filesystem
  # whose Linux device number is intentionally shared by the mount layer.
  docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
  if [ -n "$docker_root" ]; then
    case "$docker_root" in /*) ;; *)
      echo "REFUSED: Docker data root is not absolute" >&2; return 2 ;;
    esac
    docker_root="${docker_root%/}"
    case "$root" in
      "$docker_root"|"$docker_root"/*)
        echo "REFUSED: backup root is inside Docker's data root: $docker_root" >&2
        return 2 ;;
    esac
    if docker_canonical="$(cd "$docker_root" 2>/dev/null && pwd -P)"; then
      case "$root" in
        "$docker_canonical"|"$docker_canonical"/*)
          echo "REFUSED: backup root is inside Docker's data root: $docker_canonical" >&2
          return 2 ;;
      esac
      root_dev="$(stat -c %d "$root")"
      docker_dev="$(stat -c %d "$docker_canonical")"
      if [ "$root_dev" = "$docker_dev" ] && \
         [ "${SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED:-0}" != "1" ]; then
        echo "REFUSED: backup root and Docker data use the same device; set" >&2
        echo "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1 only after verifying" >&2
        echo "that this path is an independently durable mounted target" >&2
        return 2
      fi
    elif [ "${SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED:-0}" != "1" ]; then
      echo "REFUSED: Docker data root could not be traversed; explicitly attest" >&2
      echo "the independently durable backup target" >&2
      return 2
    fi
  elif [ "${SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED:-0}" != "1" ]; then
    echo "REFUSED: Docker data root could not be verified; explicitly attest" >&2
    echo "the independently durable backup target" >&2
    return 2
  fi

  # The WAL archive is written by PostgreSQL's uid; prove that exact authority.
  uid="$(docker run --rm --network none --entrypoint id \
    "$SENTINEL_BACKUP_POSTGRES_IMAGE" -u postgres 2>/dev/null || true)"
  [ -n "$uid" ] || {
    echo "REFUSED: could not resolve the postgres container uid" >&2
    return 2
  }
  docker run --rm --network none --user "$uid" \
    -v "$root/wal:/probe" --entrypoint sh \
    "$SENTINEL_BACKUP_POSTGRES_IMAGE" \
    -ceu 'p=/probe/.sentinel-write-probe-$$; : > "$p"; rm -f "$p"' \
    >/dev/null || {
      echo "REFUSED: postgres uid $uid cannot write the WAL target" >&2
      return 2
    }

  # Physical base backups are intentionally created by container root so the
  # operator-owned base/ parent does not need to be writable by the postgres uid.
  docker run --rm --network none \
    -v "$root/base:/probe" --entrypoint sh \
    "$SENTINEL_BACKUP_POSTGRES_IMAGE" \
    -ceu 'p=/probe/.sentinel-write-probe-$$; : > "$p"; rm -f "$p"' \
    >/dev/null || {
      echo "REFUSED: container root cannot write the base-backup target" >&2
      return 2
    }

  # Marker reads and writes use the same authorities as the data they protect.
  # The NAS host user is not required to write—or even traverse—the marker
  # contents. Routine validation verifies existing markers only and never
  # recreates a missing marker, preserving the cold-boot mount fence.
  for parent in "$root/wal" "$root/base"; do
    if [ "$parent" = "$root/wal" ]; then
      marker_uid="$uid"
    else
      marker_uid=""
    fi
    marker_mode=verify
    marker_action=verified
    if [ "$initialize_markers" -eq 1 ]; then
      marker_mode=initialize
      marker_action=initialized
    fi

    if marker_status="$(_sentinel_backup_marker_container \
        "$parent" "$marker_uid" "$marker_mode")"; then
      [ "$marker_status" = VALID ] || {
        echo "REFUSED: backup durable-target marker returned unexpected status: $marker_status" >&2
        return 2
      }
      continue
    else
      marker_rc=$?
    fi

    if [ "$marker_rc" -eq 4 ] && [ "$initialize_markers" -eq 0 ]; then
      echo "REFUSED: backup durable-target marker is missing: $parent/$SENTINEL_BACKUP_TARGET_MARKER" >&2
      echo "run scripts/sentinel-compose.sh --initialize-backup only while the verified external target is mounted" >&2
      return 2
    fi
    echo "REFUSED: backup durable-target marker is invalid or could not be $marker_action: $parent/$SENTINEL_BACKUP_TARGET_MARKER" >&2
    return 2
  done

  printf '%s\n' "$root"
}

sentinel_backup_compose() {
  printf '%s\n' docker compose -f docker-compose.sentinel.yml \
    -f docker-compose.sentinel-backup.yml
}
