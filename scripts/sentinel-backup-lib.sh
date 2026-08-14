#!/usr/bin/env bash
# Shared validation for backup scripts. Sourced, not invoked.

sentinel_backup_root() {
  local root raw_root repo parent docker_root root_dev docker_dev uid
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
  # it has another name.  Prove both the path boundary and the backing device,
  # or require an explicit operator attestation for a remote/durable filesystem
  # whose Linux device number is intentionally shared by the mount layer.
  docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
  if [ -n "$docker_root" ] && [ -d "$docker_root" ]; then
    docker_root="$(cd "$docker_root" && pwd -P)"
    case "$root" in
      "$docker_root"|"$docker_root"/*)
        echo "REFUSED: backup root is inside Docker's data root: $docker_root" >&2
        return 2 ;;
    esac
    root_dev="$(stat -c %d "$root")"
    docker_dev="$(stat -c %d "$docker_root")"
    if [ "$root_dev" = "$docker_dev" ] && \
       [ "${SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED:-0}" != "1" ]; then
      echo "REFUSED: backup root and Docker data use the same device; set" >&2
      echo "SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1 only after verifying" >&2
      echo "that this path is an independently durable mounted target" >&2
      return 2
    fi
  elif [ "${SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED:-0}" != "1" ]; then
    echo "REFUSED: Docker data root could not be verified; explicitly attest" >&2
    echo "the independently durable backup target" >&2
    return 2
  fi

  # The archive process runs as the postgres image's uid (999).  Check actual
  # write authority through a disposable container; host-root writability is
  # not evidence that archive_command can create a WAL file.
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
  printf '%s\n' "$root"
}

sentinel_backup_compose() {
  printf '%s\n' docker compose -f docker-compose.sentinel.yml \
    -f docker-compose.sentinel-backup.yml
}
