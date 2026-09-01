#!/usr/bin/env bash
# Shared validation for backup scripts. Sourced, not invoked.

SENTINEL_BACKUP_TARGET_MARKER=".sentinel-independent-durable-target-v1"
SENTINEL_BACKUP_TARGET_MARKER_CONTENT="sentinel-independent-durable-target-v1"

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

  local root raw_root repo parent docker_root docker_canonical root_dev docker_dev uid marker content
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
    postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
    -u postgres 2>/dev/null || true)"
  [ -n "$uid" ] || {
    echo "REFUSED: could not resolve the postgres container uid" >&2
    return 2
  }
  docker run --rm --network none --user "$uid" \
    -v "$root/wal:/probe" --entrypoint sh \
    postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
    -ceu 'p=/probe/.sentinel-write-probe-$$; : > "$p"; rm -f "$p"' \
    >/dev/null || {
      echo "REFUSED: postgres uid $uid cannot write the WAL target" >&2
      return 2
    }

  # Physical base backups are intentionally created by container root so the
  # operator-owned base/ parent does not need to be writable by uid 999. Prove
  # that exact authority too, before starting a multi-gigabyte backup.
  docker run --rm --network none \
    -v "$root/base:/probe" --entrypoint sh \
    postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
    -ceu 'p=/probe/.sentinel-write-probe-$$; : > "$p"; rm -f "$p"' \
    >/dev/null || {
      echo "REFUSED: container root cannot write the base-backup target" >&2
      return 2
    }

  # Marker creation is a one-time explicit provisioning act. Routine validation
  # never recreates a missing marker. If an external filesystem is absent after
  # a reboot, the empty underlying mountpoint therefore remains fenced even when
  # the operator previously supplied a durable-target attestation.
  for parent in "$root/wal" "$root/base"; do
    marker="$parent/$SENTINEL_BACKUP_TARGET_MARKER"
    if [ -e "$marker" ] || [ -L "$marker" ]; then
      [ -f "$marker" ] && [ ! -L "$marker" ] || {
        echo "REFUSED: backup durable-target marker is not a regular file: $marker" >&2
        return 2
      }
      content="$(cat "$marker")" || {
        echo "REFUSED: backup durable-target marker is unreadable: $marker" >&2
        return 2
      }
      [ "$content" = "$SENTINEL_BACKUP_TARGET_MARKER_CONTENT" ] || {
        echo "REFUSED: backup durable-target marker content is invalid: $marker" >&2
        return 2
      }
    elif [ "$initialize_markers" -eq 1 ]; then
      printf '%s\n' "$SENTINEL_BACKUP_TARGET_MARKER_CONTENT" > "$marker" || {
        echo "REFUSED: could not create backup durable-target marker: $marker" >&2
        return 2
      }
      sync "$marker" || {
        echo "REFUSED: could not fsync backup durable-target marker: $marker" >&2
        return 2
      }
      sync "$parent" || {
        echo "REFUSED: could not fsync backup durable-target directory: $parent" >&2
        return 2
      }
    else
      echo "REFUSED: backup durable-target marker is missing: $marker" >&2
      echo "run scripts/sentinel-backup-initialize.sh only while the verified external target is mounted" >&2
      return 2
    fi
  done

  printf '%s\n' "$root"
}

sentinel_backup_compose() {
  printf '%s\n' docker compose -f docker-compose.sentinel.yml \
    -f docker-compose.sentinel-backup.yml
}
