#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
MARKER=".sentinel-independent-durable-target-v1"
EXPECTED="sentinel-independent-durable-target-v1"
work="$(mktemp -d)"

cleanup() {
  docker run --rm --network none \
    -v "$work:/probe" --entrypoint sh "$IMAGE" \
    -ceu 'chmod -R 0777 /probe 2>/dev/null || true' \
    >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

mkdir -p "$work/wal" "$work/base"
pg_uid="$(docker run --rm --network none --entrypoint id "$IMAGE" -u postgres)"
test -n "$pg_uid"

# Reproduce the NAS permission model that exposed the defect: the host account
# can identify the child directories but cannot create files inside either one.
docker run --rm --network none \
  -e "PG_UID=$pg_uid" \
  -v "$work:/probe" --entrypoint sh "$IMAGE" -ceu '
    chown "$PG_UID:$PG_UID" /probe/wal
    chmod 0700 /probe/wal
    chown 0:0 /probe/base
    chmod 0700 /probe/base
  '

if { : > "$work/wal/.host-write-probe"; } 2>/dev/null; then
  echo "REFUSED: test host unexpectedly writes the postgres-owned WAL directory" >&2
  exit 1
fi
if { : > "$work/base/.host-write-probe"; } 2>/dev/null; then
  echo "REFUSED: test host unexpectedly writes the root-owned base directory" >&2
  exit 1
fi

# First-time provisioning must succeed through container authority even though
# the invoking host user cannot write either marker directory.
initialized="$(
  SENTINEL_BACKUP_DIR="$work" \
  SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1 \
  bash -c '. scripts/sentinel-backup-lib.sh; sentinel_backup_root --initialize-markers'
)"
test "$initialized" = "$work"

# A routine restart/check must verify the same markers through the same
# authorities without requiring host-user traversal of marker contents.
verified="$(
  SENTINEL_BACKUP_DIR="$work" \
  SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1 \
  bash -c '. scripts/sentinel-backup-lib.sh; sentinel_backup_root'
)"
test "$verified" = "$work"

# Independently inspect the exact durable bytes with each owning authority.
docker run --rm --network none --user "$pg_uid" \
  -e "EXPECTED=$EXPECTED" -e "MARKER=$MARKER" \
  -v "$work/wal:/probe" --entrypoint sh "$IMAGE" -ceu '
    test -f "/probe/$MARKER"
    test ! -L "/probe/$MARKER"
    test "$(cat "/probe/$MARKER")" = "$EXPECTED"
    test "$(stat -c %a "/probe/$MARKER")" = 444
  '
docker run --rm --network none \
  -e "EXPECTED=$EXPECTED" -e "MARKER=$MARKER" \
  -v "$work/base:/probe" --entrypoint sh "$IMAGE" -ceu '
    test -f "/probe/$MARKER"
    test ! -L "/probe/$MARKER"
    test "$(cat "/probe/$MARKER")" = "$EXPECTED"
    test "$(stat -c %a "/probe/$MARKER")" = 444
  '

# Routine validation must reject a marker whose read-only contract was weakened.
docker run --rm --network none \
  -e "MARKER=$MARKER" \
  -v "$work/base:/probe" --entrypoint sh "$IMAGE" \
  -ceu 'chmod 0644 "/probe/$MARKER"'
set +e
mode_refusal="$(
  SENTINEL_BACKUP_DIR="$work" \
  SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1 \
  bash -c '. scripts/sentinel-backup-lib.sh; sentinel_backup_root' 2>&1
)"
mode_rc=$?
set -e
test "$mode_rc" -ne 0
case "$mode_refusal" in
  *"invalid or could not be verified"*) ;;
  *)
    echo "REFUSED: weakened marker mode did not produce the expected refusal" >&2
    printf '%s\n' "$mode_refusal" >&2
    exit 1
    ;;
esac
docker run --rm --network none \
  -e "MARKER=$MARKER" \
  -v "$work/base:/probe" --entrypoint sh "$IMAGE" \
  -ceu 'chmod 0444 "/probe/$MARKER"'
restored="$(
  SENTINEL_BACKUP_DIR="$work" \
  SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1 \
  bash -c '. scripts/sentinel-backup-lib.sh; sentinel_backup_root'
)"
test "$restored" = "$work"

# Provisioning must not loosen directory ownership or permissions merely to make
# the host initializer succeed.
if { : > "$work/wal/.host-write-probe-2"; } 2>/dev/null; then
  echo "REFUSED: WAL directory permissions were weakened by marker bootstrap" >&2
  exit 1
fi
if { : > "$work/base/.host-write-probe-2"; } 2>/dev/null; then
  echo "REFUSED: base directory permissions were weakened by marker bootstrap" >&2
  exit 1
fi

printf '%s\n' 'BACKUP_MARKER_CONTAINER_AUTHORITY_PASS'
