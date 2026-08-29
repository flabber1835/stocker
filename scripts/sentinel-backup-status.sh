#!/usr/bin/env bash
# Read-only backup health checkpoint. No cleanup and no retention mutation.
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"
MAX_AGE_HOURS="${SENTINEL_BACKUP_MAX_AGE_HOURS:-30}"
STATUS_REASON_PREFIX="SENTINEL_BACKUP_STATUS_REASON="
COMPLETED_NAME_RE='^base-[0-9]{8}T[0-9]{6}Z$'

refuse() {
  local code="$1" rc="$2" message="$3"
  printf '%s%s\n' "$STATUS_REASON_PREFIX" "$code" >&2
  printf 'REFUSED: %s\n' "$message" >&2
  exit "$rc"
}

case "$MAX_AGE_HOURS" in *[!0-9]*|'')
  refuse "CONFIGURATION_INVALID" 2 \
    "SENTINEL_BACKUP_MAX_AGE_HOURS must be an integer" ;;
esac

EXPECTED=""
if [ "$#" -gt 0 ]; then
  [ "$#" -eq 2 ] && [ "$1" = "--backup" ] ||
    refuse "USAGE_INVALID" 2 \
      "usage: sentinel-backup-status.sh [--backup PATH]"
  EXPECTED="$2"
fi

COMPOSE=(docker compose -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml)
if ! ARCHIVER="$(${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel -Atc \
  "SELECT current_setting('archive_mode'), coalesce(last_archived_wal,''),
          coalesce(extract(epoch from last_archived_time)::bigint,0),
          coalesce(extract(epoch from last_failed_time)::bigint,0),
          failed_count FROM pg_stat_archiver")"; then
  refuse "ARCHIVER_STATUS_UNAVAILABLE" 4 \
    "PostgreSQL archive status could not be read"
fi
IFS='|' read -r MODE LAST_WAL LAST_OK LAST_FAIL FAILED_COUNT <<EOF
$ARCHIVER
EOF
[ "$MODE" = "on" ] ||
  refuse "ARCHIVE_MODE_DISABLED" 4 "archive_mode=$MODE"
[ -n "$LAST_WAL" ] && [ "${LAST_OK:-0}" -gt 0 ] ||
  refuse "WAL_ARCHIVE_UNINITIALIZED" 4 \
    "no successful WAL archive is recorded"
[ "${LAST_FAIL:-0}" -le "${LAST_OK:-0}" ] ||
  refuse "WAL_ARCHIVE_UNRESOLVED_FAILURE" 4 \
    "an unresolved archive failure is newer than the last success"
NOW="$(date +%s)"
WAL_AGE_HOURS="$(( (NOW - LAST_OK) / 3600 ))"
[ "$WAL_AGE_HOURS" -le "$MAX_AGE_HOURS" ] ||
  refuse "WAL_ARCHIVE_STALE" 4 \
    "last WAL archive is ${WAL_AGE_HOURS}h old"

if [ -n "$EXPECTED" ]; then
  NAME="${EXPECTED##*/}"
  [[ "$NAME" =~ $COMPLETED_NAME_RE ]] ||
    refuse "BASE_BACKUP_INVALID_NAME" 4 \
      "requested backup has an invalid name"
  [ "$EXPECTED" = "$BACKUP_ROOT/base/$NAME" ] ||
    refuse "BASE_BACKUP_OUTSIDE_ROOT" 4 \
      "requested backup is outside the Sentinel base-backup root"
else
  if ! CANDIDATES="$(${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
    find /sentinel-backup/base -mindepth 1 -maxdepth 1 -type d \
      -printf "%f\n"
  ')"; then
    refuse "BASE_BACKUP_ENUMERATION_FAILED" 4 \
      "base-backup directory could not be enumerated"
  fi
  NAME="$(printf '%s\n' "$CANDIDATES" \
    | grep -E "$COMPLETED_NAME_RE" | sort | tail -1 || true)"
fi
[ -n "$NAME" ] ||
  refuse "BASE_BACKUP_MISSING" 4 "no base backup exists"
LATEST="$BACKUP_ROOT/base/$NAME"
${COMPOSE[@]} exec -T sentinel-postgres test -d "/sentinel-backup/base/$NAME" ||
  refuse "BASE_BACKUP_NOT_FOUND" 4 \
    "requested base backup does not exist: $LATEST"
${COMPOSE[@]} exec -T sentinel-postgres test -f "/sentinel-backup/base/$NAME/backup_manifest" ||
  refuse "BASE_BACKUP_MANIFEST_MISSING" 4 \
    "latest backup has no manifest: $LATEST"
MTIME="$(${COMPOSE[@]} exec -T sentinel-postgres \
  stat -c %Y "/sentinel-backup/base/$NAME/backup_manifest")"
AGE_HOURS="$(( (NOW - MTIME) / 3600 ))"
[ "$AGE_HOURS" -le "$MAX_AGE_HOURS" ] ||
  refuse "BASE_BACKUP_STALE" 4 \
    "latest base backup is ${AGE_HOURS}h old (max ${MAX_AGE_HOURS}h)"
${COMPOSE[@]} exec -T sentinel-postgres \
  test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker" ||
  refuse "BASE_BACKUP_RECOVERY_MARKER_MISSING" 4 \
    "latest backup lacks a post-base recovery marker"
echo "backup_ready:true base=$LATEST age_hours=$AGE_HOURS wal_age_hours=$WAL_AGE_HOURS"
