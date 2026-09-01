#!/bin/sh
# Publish one completed PostgreSQL WAL object without exposing a partial final
# pathname. Invoked only by archive_command inside sentinel-postgres.
set -eu

refuse() {
  echo "sentinel WAL archive REFUSED: $*" >&2
  exit 1
}

[ "$#" -eq 3 ] || refuse "expected SOURCE WAL_NAME ARCHIVE_DIRECTORY"
source_wal="$1"
wal_name="$2"
archive_dir="$3"
marker="$archive_dir/.sentinel-independent-durable-target-v1"
marker_content="sentinel-independent-durable-target-v1"

case "$wal_name" in
  ""|.|..|*/*) refuse "invalid WAL filename: $wal_name" ;;
esac
[ -f "$source_wal" ] && [ -r "$source_wal" ] || \
  refuse "source is not a readable regular file: $source_wal"
[ -d "$archive_dir" ] && [ ! -L "$archive_dir" ] || \
  refuse "archive directory is missing or is a symlink: $archive_dir"
[ -f "$marker" ] && [ ! -L "$marker" ] || \
  refuse "independent durable-target marker is missing: $marker"
[ "$(cat "$marker")" = "$marker_content" ] || \
  refuse "independent durable-target marker is invalid: $marker"

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

# The temporary is created in the destination directory so publication is a
# same-filesystem atomic rename. No copy operation ever writes the final name.
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

# GNU coreutils sync with a pathname calls fsync(2) on that object. The pinned
# PostgreSQL image supplies it. Refuse publication if durable file sync fails.
sync "$temporary" || refuse "could not fsync temporary archive"
final_matches_source "$temporary" || \
  refuse "temporary archive changed after fsync"

# --no-clobber makes a concurrent publication a validation path, never an
# overwrite. Successful publication is one atomic same-directory rename.
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

# Persist the directory entry before archive_command reports success. If this
# fails, PostgreSQL retries; the exact-match branch above repeats both fsyncs.
sync "$archive_dir" || refuse "could not fsync archive directory: $archive_dir"
final_matches_source "$target" || \
  refuse "published archive changed during durable validation: $target"
exit 0
