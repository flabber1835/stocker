#!/usr/bin/env bash
# Create and verify one physical PostgreSQL base backup. No broker access.
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="base-$STAMP"
MARKER="sentinel-backup-$STAMP-$$"
METADATA="$BACKUP_ROOT/base/$NAME/sentinel-recovery-marker"

COMPOSE=(docker compose -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml)

# Do not silently restart PostgreSQL to turn archiving on. The operator starts
# the documented overlay; this command verifies that exact durable mode first.
MODE="$(${COMPOSE[@]} exec -T sentinel-postgres \
  psql -U sentinel -d sentinel -Atc "SHOW archive_mode")"
[ "$MODE" = "on" ] || {
  echo "REFUSED: archive_mode=$MODE; start the documented backup overlay" >&2
  exit 3
}

${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
  test ! -e "/sentinel-backup/base/'"$NAME"'"
  test ! -e "/sentinel-backup/base/'"$NAME"'.part"
  export PGPASSWORD="$POSTGRES_PASSWORD"
  pg_basebackup -h 127.0.0.1 -U sentinel -D \
    "/sentinel-backup/base/'"$NAME"'.part" -Fp -Xs -P -c fast
  pg_verifybackup "/sentinel-backup/base/'"$NAME"'.part"
  mv "/sentinel-backup/base/'"$NAME"'.part" \
     "/sentinel-backup/base/'"$NAME"'"
  psql -h 127.0.0.1 -U sentinel -d sentinel -Atc "SELECT pg_switch_wal()" >/dev/null
'

# Prove recovery beyond the base-backup boundary.  The marker is created only
# after pg_basebackup completed, then its transaction WAL is forced to archive.
# Metadata is published only after pg_stat_archiver names that segment.
${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel \
  -v ON_ERROR_STOP=1 -Atc "
    CREATE TABLE IF NOT EXISTS sentinel_backup_recovery_markers (
      marker TEXT PRIMARY KEY, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
    INSERT INTO sentinel_backup_recovery_markers(marker) VALUES ('$MARKER');" \
  >/dev/null
MARKER_ROW="$(${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel \
  -v ON_ERROR_STOP=1 -Atc "
    SELECT '$MARKER|' || pg_current_wal_lsn()::text || '|' ||
           pg_walfile_name(pg_current_wal_lsn());")"
IFS='|' read -r MARKER_VALUE MARKER_LSN MARKER_WAL <<EOF
$MARKER_ROW
EOF
[ "$MARKER_VALUE" = "$MARKER" ] && [ -n "$MARKER_LSN" ] && [ -n "$MARKER_WAL" ] || {
  echo "REFUSED: recovery marker identity was malformed" >&2; exit 4; }
${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel -Atc \
  "SELECT pg_switch_wal()" >/dev/null
for _ in $(seq 1 60); do
  ARCHIVED="$(${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel -Atc \
    "SELECT coalesce(last_archived_wal,'') FROM pg_stat_archiver")"
  [ -f "$BACKUP_ROOT/wal/$MARKER_WAL" ] || {
    sleep 1; continue; }
  printf 'marker=%s\nlsn=%s\nwal=%s\n' \
    "$MARKER" "$MARKER_LSN" "$MARKER_WAL" > "$METADATA"
  break
done
[ -f "$METADATA" ] || {
  echo "REFUSED: marker WAL $MARKER_WAL was not archived" >&2; exit 4; }

echo "verified_base_backup:$BACKUP_ROOT/base/$NAME"
