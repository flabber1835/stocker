#!/bin/sh
# Sourced inside a root Docker worker; fd 9 remains owned by the actual worker.
sentinel_media_lock() {
  root="$1" mode="$2"
  test -d "$root" && test ! -L "$root" || return 4
  lock="$root/.sentinel-maintenance.lock"
  # noclobber gives create-if-absent; never replace/unlink an existing lock inode.
  (umask 077; set -C; : > "$lock") 2>/dev/null || true
  test -f "$lock" && test ! -L "$lock" || return 4
  test "$(stat -c '%h:%a' "$lock")" = '1:600' || return 4
  before="$(stat -c '%d:%i' "$lock")"
  exec 9<>"$lock"
  case "$mode" in
    shared) flock -s -n 9 || return 4 ;;
    exclusive) flock -x -n 9 || return 4 ;;
    *) return 4 ;;
  esac
  test "$(stat -Lc '%d:%i' /proc/self/fd/9)" = "$before" || return 4
  test "$(stat -c '%d:%i' "$lock")" = "$before" || return 4
}
