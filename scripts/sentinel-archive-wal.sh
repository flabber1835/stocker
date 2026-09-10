#!/bin/sh
# Publish one completed PostgreSQL archive object without exposing a partial
# final pathname. Each PostgreSQL cluster gets an immutable system-id namespace
# so a recreated cluster can never collide with an older cluster's WAL/history.
set -eu

refuse() {
  echo "sentinel WAL archive REFUSED: $*" >&2
  exit 1
}

[ "$#" -eq 3 ] || refuse "expected SOURCE WAL_NAME ARCHIVE_DIRECTORY"
source_wal="$1"
wal_name="$2"
archive_root="$3"
marker="$archive_root/.sentinel-independent-durable-target-v1"
marker_content="sentinel-independent-durable-target-v1"

case "$wal_name" in
  ""|.|..|*/*) refuse "invalid WAL filename: $wal_name" ;;
esac
[ -f "$source_wal" ] && [ -r "$source_wal" ] || \
  refuse "source is not a readable regular file: $source_wal"
[ -d "$archive_root" ] && [ ! -L "$archive_root" ] || \
  refuse "archive directory is missing or is a symlink: $archive_root"
[ -f "$marker" ] && [ ! -L "$marker" ] || \
  refuse "independent durable-target marker is missing: $marker"
[ "$(cat "$marker")" = "$marker_content" ] || \
  refuse "independent durable-target marker is invalid: $marker"

is_segment=0
is_history=0
is_backup_history=0
if printf '%s\n' "$wal_name" | grep -Eq '^[0-9A-F]{24}$'; then
  is_segment=1
elif printf '%s\n' "$wal_name" | grep -Eq '^[0-9A-F]{8}\.history$'; then
  is_history=1
elif printf '%s\n' "$wal_name" | grep -Eq '^[0-9A-F]{24}\.[0-9A-F]{8}\.backup$'; then
  is_backup_history=1
else
  refuse "unsupported PostgreSQL archive object name: $wal_name"
fi

# WAL segments carry the 64-bit database-system identifier in their long page
# header. Timeline/backup-history files are text metadata and do not. PostgreSQL
# defines archive_command %p relative to the server working directory, which is
# the cluster data directory. Derive pg_control from that exact path first; use
# PGDATA only for explicit non-%p invocations such as standalone harness calls.
case "$source_wal" in
  */pg_wal/*) control_dir="${source_wal%/pg_wal/*}" ;;
  pg_wal/*) control_dir="." ;;
  *) control_dir="${PGDATA:-.}" ;;
esac
control_system_id=""
if [ -d "$control_dir" ] && command -v pg_controldata >/dev/null 2>&1; then
  control_system_id="$(pg_controldata "$control_dir" 2>/dev/null \
    | awk -F: '/Database system identifier/ {gsub(/[[:space:]]/,"",$2); print $2; exit}')" || true
fi
case "$control_system_id" in
  "") ;;
  *[!0-9]*) refuse "invalid PostgreSQL system identifier from pg_control" ;;
esac

source_system_id=""
if [ "$is_segment" -eq 1 ]; then
  source_system_id="$(od -An -t u8 -j 24 -N 8 -- "$source_wal" 2>/dev/null | tr -d '[:space:]')" || \
    refuse "could not read PostgreSQL system identifier from $wal_name"
  case "$source_system_id" in
    ""|*[!0-9]*) refuse "invalid PostgreSQL system identifier in $wal_name" ;;
  esac
  if [ -n "$control_system_id" ] && [ "$control_system_id" != "$source_system_id" ]; then
    refuse "WAL source system identifier differs from running PostgreSQL cluster"
  fi
  system_id="$source_system_id"
else
  [ -n "$control_system_id" ] || \
    refuse "could not establish PostgreSQL system identifier for history object $wal_name"
  system_id="$control_system_id"
fi

namespace_name="cluster-$system_id"
archive_dir="$archive_root/$namespace_name"
if [ -e "$archive_dir" ] || [ -L "$archive_dir" ]; then
  [ -d "$archive_dir" ] && [ ! -L "$archive_dir" ] || \
    refuse "cluster WAL namespace is not a regular directory: $archive_dir"
else
  mkdir "$archive_dir" || refuse "could not create cluster WAL namespace: $archive_dir"
  chmod 0700 "$archive_dir" || refuse "could not protect cluster WAL namespace: $archive_dir"
  sync "$archive_root" || refuse "could not fsync WAL namespace root"
fi

target="$archive_dir/$wal_name"
checksum_target="$target.sha256"
temporary=""
checksum_temporary=""
cleanup() {
  [ -z "$temporary" ] || rm -f -- "$temporary"
  [ -z "$checksum_temporary" ] || rm -f -- "$checksum_temporary"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

source_size_before="$(stat -c %s -- "$source_wal")" || \
  refuse "could not stat source: $source_wal"
[ "$source_size_before" -gt 0 ] || refuse "archive source is empty: $wal_name"
source_sha256="$(sha256sum -- "$source_wal" | awk '{print $1}')" || \
  refuse "could not hash source WAL $wal_name"
case "$source_sha256" in
  ""|*[!0-9a-f]* ) refuse "source WAL SHA-256 is malformed: $wal_name" ;;
esac
[ "${#source_sha256}" -eq 64 ] || refuse "source WAL SHA-256 length is invalid: $wal_name"

hash_matches_source() {
  candidate="$1"
  [ ! -L "$candidate" ] && [ -f "$candidate" ] && [ -r "$candidate" ] || return 1
  observed_sha256="$(sha256sum -- "$candidate" | awk '{print $1}')" || return 1
  [ "$observed_sha256" = "$source_sha256" ]
}

source_hash_unchanged() {
  hash_matches_source "$source_wal"
}

final_matches_source() {
  candidate="$1"
  [ ! -L "$candidate" ] && [ -f "$candidate" ] || return 1
  candidate_size="$(stat -c %s -- "$candidate")" || return 1
  source_size_now="$(stat -c %s -- "$source_wal")" || return 1
  [ "$source_size_before" = "$source_size_now" ] || return 1
  [ "$candidate_size" = "$source_size_now" ] || return 1
  cmp -s -- "$source_wal" "$candidate" && hash_matches_source "$candidate"
}

checksum_matches_source() {
  candidate="$1"
  [ ! -L "$candidate" ] && [ -f "$candidate" ] && [ -r "$candidate" ] || return 1
  [ "$(cat "$candidate")" = "sha256=$source_sha256" ]
}

publish_checksum() {
  source_hash_unchanged || refuse "source WAL changed after initial hash: $wal_name"
  if [ -e "$checksum_target" ] || [ -L "$checksum_target" ]; then
    checksum_matches_source "$checksum_target" || \
      refuse "existing WAL checksum differs from source: $checksum_target"
    sync "$checksum_target" || refuse "could not fsync existing WAL checksum: $checksum_target"
    sync "$archive_dir" || refuse "could not fsync archive directory: $archive_dir"
    checksum_matches_source "$checksum_target" || \
      refuse "existing WAL checksum changed during durable validation: $checksum_target"
    return 0
  fi

  checksum_temporary="$(mktemp "$archive_dir/.${wal_name}.sha256.part.XXXXXX")" || \
    refuse "could not create same-directory WAL checksum temporary file"
  printf 'sha256=%s\n' "$source_sha256" > "$checksum_temporary" || \
    refuse "could not write WAL checksum temporary file"
  chmod 0600 "$checksum_temporary" || refuse "could not protect WAL checksum temporary file"
  sync "$checksum_temporary" || refuse "could not fsync WAL checksum temporary file"
  [ "$(cat "$checksum_temporary")" = "sha256=$source_sha256" ] || \
    refuse "WAL checksum temporary file changed after fsync"

  if ! mv -T --no-clobber -- "$checksum_temporary" "$checksum_target"; then
    [ -f "$checksum_temporary" ] && checksum_matches_source "$checksum_target" || \
      refuse "atomic WAL checksum publication failed for $wal_name"
  fi
  if [ -e "$checksum_temporary" ]; then
    checksum_matches_source "$checksum_target" || \
      refuse "concurrent WAL checksum publication differs from source: $checksum_target"
    rm -f -- "$checksum_temporary"
  else
    checksum_temporary=""
  fi
  checksum_matches_source "$checksum_target" || \
    refuse "published WAL checksum differs from source: $checksum_target"
  sync "$checksum_target" || refuse "could not fsync published WAL checksum: $checksum_target"
  sync "$archive_dir" || refuse "could not fsync archive directory: $archive_dir"
  checksum_matches_source "$checksum_target" || \
    refuse "published WAL checksum changed during durable validation: $checksum_target"
  source_hash_unchanged || refuse "source WAL changed while publishing checksum: $wal_name"
}

# PostgreSQL retries an archive command after any nonzero result. An existing
# immutable final is idempotent only when it is the exact completed source.
if [ -e "$target" ] || [ -L "$target" ]; then
  final_matches_source "$target" || \
    refuse "existing archive differs from source: $target"
  sync "$target" || refuse "could not fsync existing archive: $target"
  publish_checksum
  final_matches_source "$target" || \
    refuse "existing archive changed during durable validation: $target"
  checksum_matches_source "$checksum_target" || \
    refuse "existing WAL checksum changed during durable validation: $checksum_target"
  exit 0
fi

temporary="$(mktemp "$archive_dir/.${wal_name}.part.XXXXXX")" || \
  refuse "could not create same-directory temporary file"
if ! cp -- "$source_wal" "$temporary"; then
  refuse "copy failed for $wal_name"
fi

temporary_size="$(stat -c %s -- "$temporary")" || \
  refuse "could not stat temporary archive"
source_size_after="$(stat -c %s -- "$source_wal")" || \
  refuse "could not restat source"
[ "$source_size_before" = "$source_size_after" ] || \
  refuse "source size changed during copy"
source_hash_unchanged || refuse "source WAL contents changed during copy: $wal_name"
[ "$temporary_size" = "$source_size_after" ] || \
  refuse "temporary archive size differs from source"
cmp -s -- "$source_wal" "$temporary" || \
  refuse "temporary archive contents differ from source"
hash_matches_source "$temporary" || \
  refuse "temporary archive hash differs from initial source hash"

sync "$temporary" || refuse "could not fsync temporary archive"
final_matches_source "$temporary" || \
  refuse "temporary archive changed after fsync"

if ! mv -T --no-clobber -- "$temporary" "$target"; then
  # Coreutils versions differ on the exit status of a no-clobber name race.
  # Only an intact temporary plus an exact competing final proves that case.
  [ -f "$temporary" ] && final_matches_source "$target" || \
    refuse "atomic publication failed for $wal_name"
fi
if [ -e "$temporary" ]; then
  final_matches_source "$target" || \
    refuse "concurrent archive publication differs from source: $target"
  rm -f -- "$temporary"
else
  temporary=""
fi

final_matches_source "$target" || \
  refuse "published archive differs from source: $target"
sync "$target" || refuse "could not fsync published archive: $target"
publish_checksum
final_matches_source "$target" || \
  refuse "published archive changed during durable validation: $target"
checksum_matches_source "$checksum_target" || \
  refuse "published WAL checksum changed during final validation: $checksum_target"
source_hash_unchanged || refuse "source WAL changed before archive success: $wal_name"
exit 0