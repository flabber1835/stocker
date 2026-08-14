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

LATEST="$(find "$BACKUP_ROOT/base" -mindepth 1 -maxdepth 1 -type d \
  -name 'base-*' -print | sort | tail -1)"
[ -n "$LATEST" ] || { echo "REFUSED: no base backup exists" >&2; exit 4; }
[ -f "$LATEST/backup_manifest" ] || {
  echo "REFUSED: latest backup has no manifest: $LATEST" >&2; exit 4
}
MTIME="$(stat -c %Y "$LATEST/backup_manifest")"
AGE_HOURS="$(( (NOW - MTIME) / 3600 ))"
[ "$AGE_HOURS" -le "$MAX_AGE_HOURS" ] || {
  echo "REFUSED: latest base backup is ${AGE_HOURS}h old (max ${MAX_AGE_HOURS}h)" >&2
  exit 4
}
[ -f "$LATEST/sentinel-recovery-marker" ] || {
  echo "REFUSED: latest backup lacks a post-base recovery marker" >&2; exit 4; }
echo "backup_ready:true base=$LATEST age_hours=$AGE_HOURS wal_age_hours=$WAL_AGE_HOURS"
