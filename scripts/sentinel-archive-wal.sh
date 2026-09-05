#!/bin/sh
# Publish one completed PostgreSQL WAL object without exposing a partial final
# pathname. Each PostgreSQL cluster gets an immutable system-id namespace so a
# recreated cluster can never collide with an older cluster's WAL filenames.
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

# PostgreSQL writes the 64-bit database-system identifier into the long WAL
# page header at byte offset 24 of every segment's first page. Read the identity
# from the immutable source itself; archive_command therefore cannot be pointed
# at the wrong cluster namespace by configuration or environment drift.
system_id="$(od -An -t u8 -j 24 -N 8 -- "$source_wal" 2>/dev/null | tr -d '[:space:]')" || \
  refuse "could not read PostgreSQL system identifier from $wal_name"
case "$system_id" in
  ""|*[!0-9]*) refuse "invalid PostgreSQL system identifier in $wal_name" ;;
esac
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
temporary=""
cleanup() {
  [ -z "$temporary" ] || rm -f -- "$temporary"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

source_size_before="$(stat -c %s -- "$source_wal")" || \
  refuse "could not stat source: $source_wal"

final_matches_source() {
  candidate="$1"
  [ ! -L "$candidate" ] && [ -f "$candidate" ] || return 1
  candidate_size="$(stat -c %s -- "$candidate")" || return 1
  source_size_now="$(stat -c %s -- "$source_wal")" || return 1
  [ "$source_size_before" = "$source_size_now" ] || return 1
  [ "$candidate_size" = "$source_size_now" ] || return 1
  cmp -s -- "$source_wal" "$candidate"
}

# PostgreSQL retries an archive command after any nonzero result. An existing
# immutable final is idempotent only when it is the exact completed source.
if [ -e "$target" ] || [ -L "$target" ]; then
  final_matches_source "$target" || \
    refuse "existing archive differs from source: $target"
  sync "$target" || refuse "could not fsync existing archive: $target"
  sync "$archive_dir" || refuse "could not fsync archive directory: $archive_dir"
  final_matches_source "$target" || \
    refuse "existing archive changed during durable validation: $target"
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
[ "$temporary_size" = "$source_size_after" ] || \
  refuse "temporary archive size differs from source"
cmp -s -- "$source_wal" "$temporary" || \
  refuse "temporary archive contents differ from source"

sync "$temporary" || refuse "could not fsync temporary archive"
final_matches_source "$temporary" || \
  refuse "temporary archive changed after fsync"

if ! mv -T --no-clobber -- "$temporary" "$target"; then
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
sync "$archive_dir" || refuse "could not fsync archive directory: $archive_dir"
final_matches_source "$target" || \
  refuse "published archive changed during durable validation: $target"
exit 0
