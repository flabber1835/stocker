#!/usr/bin/env bash
# Restore one physical backup into an isolated disposable volume and verify
# canonical tables. The primary database is read-only to this script.
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"

EXPECTED=""
if [ "$#" -gt 0 ]; then
  [ "$#" -eq 2 ] && [ "$1" = "--backup" ] || {
    echo "REFUSED: usage: sentinel-restore-drill.sh [--backup PATH]" >&2
    exit 2
  }
  EXPECTED="$2"
fi
if [ -n "$EXPECTED" ]; then
  case "$EXPECTED" in
    "$BACKUP_ROOT"/base/base-*) LATEST="$EXPECTED" ;;
    *) echo "REFUSED: requested backup is outside the Sentinel base-backup root" >&2; exit 4 ;;
  esac
  [ -d "$LATEST" ] || { echo "REFUSED: requested base backup does not exist: $LATEST" >&2; exit 4; }
else
  LATEST="$(find "$BACKUP_ROOT/base" -mindepth 1 -maxdepth 1 -type d \
    -name 'base-*' -print | sort | tail -1)"
fi
[ -n "$LATEST" ] || { echo "REFUSED: no base backup exists" >&2; exit 4; }
[ -f "$LATEST/backup_manifest" ] || {
  echo "REFUSED: backup manifest missing: $LATEST" >&2; exit 4
}
MARKER_FILE="$LATEST/sentinel-recovery-marker"
[ -f "$MARKER_FILE" ] || {
  echo "REFUSED: post-base recovery marker metadata missing: $LATEST" >&2
  exit 4
}
MARKER="$(sed -n 's/^marker=//p' "$MARKER_FILE")"
TARGET_LSN="$(sed -n 's/^lsn=//p' "$MARKER_FILE")"
[ -n "$MARKER" ] && [ -n "$TARGET_LSN" ] || {
  echo "REFUSED: recovery marker metadata is malformed" >&2; exit 4; }

TOKEN="$(date -u +%Y%m%dT%H%M%SZ)-$$"
VOLUME="sentinel-restore-drill-$TOKEN"
CONTAINER="sentinel-restore-drill-$TOKEN"
cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker volume create "$VOLUME" >/dev/null
docker run --rm --network none \
  -v "$LATEST:/source:ro" -v "$VOLUME:/target" \
  --entrypoint sh postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
  -ceu 'cp -a /source/. /target/; chown -R postgres:postgres /target; chmod 700 /target; touch /target/recovery.signal; chown postgres:postgres /target/recovery.signal'

docker run -d --name "$CONTAINER" --network none \
  -v "$VOLUME:/var/lib/postgresql/data" -v "$BACKUP_ROOT/wal:/archive:ro" \
  postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
  postgres -c "restore_command=cp /archive/%f %p" -c "listen_addresses=" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$CONTAINER" pg_isready -U sentinel -d sentinel >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$CONTAINER" pg_isready -U sentinel -d sentinel >/dev/null
for _ in $(seq 1 60); do
  REPLAYED="$(docker exec "$CONTAINER" psql -U sentinel -d sentinel -Atc \
    "SELECT CASE WHEN pg_last_wal_replay_lsn() >= '$TARGET_LSN'::pg_lsn
       AND EXISTS (SELECT 1 FROM sentinel_backup_recovery_markers
                    WHERE marker = '$MARKER') THEN 'yes' ELSE 'no' END" \
    2>/dev/null || true)"
  [ "$REPLAYED" = "yes" ] && break
  sleep 1
done
[ "${REPLAYED:-}" = "yes" ] || {
  echo "REFUSED: archived WAL did not replay through marker $MARKER" >&2
  exit 4
}
docker exec "$CONTAINER" psql -U sentinel -d sentinel -v ON_ERROR_STOP=1 -Atc \
  'DO $$
   BEGIN
      IF to_regclass('"'"'public.sentinel_account_binding'"'"') IS NULL OR
         to_regclass('"'"'public.sentinel_behavioral_schema_migrations'"'"') IS NULL OR
         to_regclass('"'"'public.sentinel_rollout_state'"'"') IS NULL OR
         to_regclass('"'"'public.sentinel_processed_sessions'"'"') IS NULL OR
         to_regclass('"'"'public.sentinel_execution_plans'"'"') IS NULL THEN
       RAISE EXCEPTION '"'"'canonical Sentinel tables are missing'"'"';
     END IF;
     IF NOT pg_is_in_recovery() THEN
       RAISE EXCEPTION '"'"'restore drill did not enter recovery'"'"';
     END IF;
   END $$;'
echo "restore_drill_ready:true backup=$LATEST"
