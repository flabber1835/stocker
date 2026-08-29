#!/usr/bin/env bash
# Restore one physical backup into an isolated disposable volume, replay its
# marker, promote it, and validate it with the exact Sentinel runtime image.
# The primary database is read-only to this script.
set -euo pipefail

cd "$(dirname "$0")/.."
. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"
COMPOSE=(docker compose -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml)
COMPLETED_NAME_RE='^base-[0-9]{8}T[0-9]{6}Z$'

EXPECTED=""
PHYSICAL_ONLY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --backup)
      [ "$#" -ge 2 ] && [ -z "$EXPECTED" ] || {
        echo "REFUSED: --backup requires one unique path" >&2; exit 2; }
      EXPECTED="$2"
      shift 2
      ;;
    --physical-only)
      [ "$PHYSICAL_ONLY" -eq 0 ] || {
        echo "REFUSED: --physical-only was repeated" >&2; exit 2; }
      PHYSICAL_ONLY=1
      shift
      ;;
    *)
      echo "REFUSED: usage: sentinel-restore-drill.sh [--backup PATH] [--physical-only]" >&2
      exit 2
      ;;
  esac
done
if [ -n "$EXPECTED" ]; then
  NAME="${EXPECTED##*/}"
  [[ "$NAME" =~ $COMPLETED_NAME_RE ]] || {
    echo "REFUSED: requested backup has an invalid name" >&2; exit 4; }
  [ "$EXPECTED" = "$BACKUP_ROOT/base/$NAME" ] || {
    echo "REFUSED: requested backup is outside the Sentinel base-backup root" >&2; exit 4; }
else
  CANDIDATES="$(${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
    find /sentinel-backup/base -mindepth 1 -maxdepth 1 -type d -printf "%f\n"
  ')"
  NAME="$(printf '%s\n' "$CANDIDATES" \
    | grep -E "$COMPLETED_NAME_RE" | sort | tail -1 || true)"
fi
[ -n "$NAME" ] || { echo "REFUSED: no base backup exists" >&2; exit 4; }
LATEST="$BACKUP_ROOT/base/$NAME"
${COMPOSE[@]} exec -T sentinel-postgres test -d "/sentinel-backup/base/$NAME" || {
  echo "REFUSED: requested base backup does not exist: $LATEST" >&2; exit 4; }
${COMPOSE[@]} exec -T sentinel-postgres test -f "/sentinel-backup/base/$NAME/backup_manifest" || {
  echo "REFUSED: backup manifest missing: $LATEST" >&2; exit 4; }
${COMPOSE[@]} exec -T sentinel-postgres \
  test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker" || {
  echo "REFUSED: post-base recovery marker metadata missing: $LATEST" >&2
  exit 4
}
MARKER_ROW="$(${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
  file="/sentinel-backup/base/$1/sentinel-recovery-marker"
  marker="$(sed -n "s/^marker=//p" "$file")"
  lsn="$(sed -n "s/^lsn=//p" "$file")"
  printf "%s|%s\n" "$marker" "$lsn"
' sh "$NAME")"
IFS='|' read -r MARKER TARGET_LSN <<EOF
$MARKER_ROW
EOF
[ -n "$MARKER" ] && [ -n "$TARGET_LSN" ] || {
  echo "REFUSED: recovery marker metadata is malformed" >&2; exit 4; }
[[ "$MARKER" =~ ^sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || {
  echo "REFUSED: recovery marker identity is malformed" >&2; exit 4; }
[[ "$TARGET_LSN" =~ ^[0-9A-F]+/[0-9A-F]+$ ]] || {
  echo "REFUSED: recovery marker LSN is malformed" >&2; exit 4; }

TOKEN="$(date -u +%Y%m%dT%H%M%SZ)-$$"
VOLUME="sentinel-restore-drill-$TOKEN"
CONTAINER="sentinel-restore-drill-$TOKEN"
NETWORK="sentinel-restore-drill-$TOKEN"
cleanup() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker volume create "$VOLUME" >/dev/null
docker network create --internal "$NETWORK" >/dev/null
docker run --rm --network none \
  -v "$LATEST:/source:ro" -v "$VOLUME:/target" \
  --entrypoint sh postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
  -ceu 'cp -a /source/. /target/; chown -R postgres:postgres /target; chmod 700 /target; touch /target/recovery.signal; chown postgres:postgres /target/recovery.signal'

docker run -d --name "$CONTAINER" --network "$NETWORK" \
  --network-alias restored-postgres \
  -v "$VOLUME:/var/lib/postgresql/data" -v "$BACKUP_ROOT/wal:/archive:ro" \
  postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
  postgres -c "restore_command=cp /archive/%f %p" -c "listen_addresses=*" >/dev/null

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
echo "physical_wal_replay_ready:true backup=$LATEST"

if [ "$PHYSICAL_ONLY" -eq 1 ]; then
  exit 0
fi

RUNTIME_IMAGE="${SENTINEL_RUNTIME_IMAGE_REF:-}"
if [ -z "$RUNTIME_IMAGE" ] && \
   [ -n "${SENTINEL_RUNTIME_IMAGE_REPOSITORY:-}" ] && \
   [ -n "${SENTINEL_RUNTIME_IMAGE_DIGEST:-}" ]; then
  RUNTIME_IMAGE="${SENTINEL_RUNTIME_IMAGE_REPOSITORY}@${SENTINEL_RUNTIME_IMAGE_DIGEST}"
fi
if ! [[ "$RUNTIME_IMAGE" =~ ^sha256:[0-9a-f]{64}$|^[A-Za-z0-9][A-Za-z0-9._/:@-]*@sha256:[0-9a-f]{64}$ ]]; then
  echo "REFUSED: configured Sentinel runtime must name an immutable image digest" >&2
  exit 4
fi
[ -n "${SENTINEL_POSTGRES_PASSWORD:-}" ] || {
  echo "REFUSED: SENTINEL_POSTGRES_PASSWORD is required for semantic validation" >&2
  exit 4
}

PROMOTED="$(docker exec "$CONTAINER" psql -U sentinel -d sentinel -Atc \
  'SELECT pg_promote(true,60)')"
[ "$PROMOTED" = "t" ] || {
  echo "REFUSED: disposable restored database did not promote" >&2
  exit 4
}
IN_RECOVERY="$(docker exec "$CONTAINER" psql -U sentinel -d sentinel -Atc \
  'SELECT pg_is_in_recovery()')"
[ "$IN_RECOVERY" = "f" ] || {
  echo "REFUSED: disposable restored database remains in recovery" >&2
  exit 4
}

docker run --rm --network "$NETWORK" --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  -e SENTINEL_RESTORE_DATABASE_HOST=restored-postgres \
  -e SENTINEL_RESTORE_DATABASE_PASSWORD="$SENTINEL_POSTGRES_PASSWORD" \
  --entrypoint python "$RUNTIME_IMAGE" -m sentinel.restore_validation
echo "restore_semantics_ready:true backup=$LATEST image=$RUNTIME_IMAGE"
