#!/usr/bin/env bash
# Read-only backup health checkpoint. No cleanup and no retention mutation.
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"
MAX_AGE_HOURS="${SENTINEL_BACKUP_MAX_AGE_HOURS:-30}"
case "$MAX_AGE_HOURS" in *[!0-9]*|'')
  echo "REFUSED: SENTINEL_BACKUP_MAX_AGE_HOURS must be an integer" >&2; exit 2 ;;
esac

EXPECTED=""
if [ "$#" -gt 0 ]; then
  [ "$#" -eq 2 ] && [ "$1" = "--backup" ] || {
    echo "REFUSED: usage: sentinel-backup-status.sh [--backup PATH]" >&2
    exit 2
  }
  EXPECTED="$2"
fi

COMPOSE=(docker compose -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml)
ARCHIVER="$(${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel -Atc \
  "SELECT current_setting('archive_mode'), coalesce(last_archived_wal,''),
          coalesce(extract(epoch from last_archived_time)::bigint,0),
          coalesce(extract(epoch from last_failed_time)::bigint,0),
          failed_count FROM pg_stat_archiver")"
IFS='|' read -r MODE LAST_WAL LAST_OK LAST_FAIL FAILED_COUNT <<EOF
$ARCHIVER
EOF
[ "$MODE" = "on" ] || { echo "REFUSED: archive_mode=$MODE" >&2; exit 4; }
[ -n "$LAST_WAL" ] && [ "${LAST_OK:-0}" -gt 0 ] || {
  echo "REFUSED: no successful WAL archive is recorded" >&2; exit 4; }
[ "${LAST_FAIL:-0}" -le "${LAST_OK:-0}" ] || {
  echo "REFUSED: an unresolved archive failure is newer than the last success" >&2
  exit 4
}
NOW="$(date +%s)"
WAL_AGE_HOURS="$(( (NOW - LAST_OK) / 3600 ))"
[ "$WAL_AGE_HOURS" -le "$MAX_AGE_HOURS" ] || {
  echo "REFUSED: last WAL archive is ${WAL_AGE_HOURS}h old" >&2; exit 4; }

if [ -n "$EXPECTED" ]; then
  NAME="${EXPECTED##*/}"
  case "$NAME" in base-*) ;; *)
    echo "REFUSED: requested backup has an invalid name" >&2; exit 4 ;;
  esac
  [ "$EXPECTED" = "$BACKUP_ROOT/base/$NAME" ] || {
    echo "REFUSED: requested backup is outside the Sentinel base-backup root" >&2; exit 4; }
else
  NAME="$(${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
    find /sentinel-backup/base -mindepth 1 -maxdepth 1 -type d \
      -name "base-*" -printf "%f\n" | sort | tail -1
  ')"
fi
[ -n "$NAME" ] || { echo "REFUSED: no base backup exists" >&2; exit 4; }
LATEST="$BACKUP_ROOT/base/$NAME"
${COMPOSE[@]} exec -T sentinel-postgres test -d "/sentinel-backup/base/$NAME" || {
  echo "REFUSED: requested base backup does not exist: $LATEST" >&2; exit 4; }
${COMPOSE[@]} exec -T sentinel-postgres test -f "/sentinel-backup/base/$NAME/backup_manifest" || {
  echo "REFUSED: latest backup has no manifest: $LATEST" >&2; exit 4; }
MTIME="$(${COMPOSE[@]} exec -T sentinel-postgres \
  stat -c %Y "/sentinel-backup/base/$NAME/backup_manifest")"
AGE_HOURS="$(( (NOW - MTIME) / 3600 ))"
[ "$AGE_HOURS" -le "$MAX_AGE_HOURS" ] || {
  echo "REFUSED: latest base backup is ${AGE_HOURS}h old (max ${MAX_AGE_HOURS}h)" >&2
  exit 4
}
${COMPOSE[@]} exec -T sentinel-postgres \
  test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker" || {
  echo "REFUSED: latest backup lacks a post-base recovery marker" >&2; exit 4; }
echo "backup_ready:true base=$LATEST age_hours=$AGE_HOURS wal_age_hours=$WAL_AGE_HOURS"
