#!/usr/bin/env bash
# Restore one physical backup into an isolated disposable volume, replay its
# marker, promote it, and validate it with the exact Sentinel runtime image.
# The primary database is read-only except for one append-only operator proof
# written only after the disposable restore passes full semantic validation.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null
. scripts/sentinel-env.sh
sentinel_load_environment --profile maintenance

. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"
export SENTINEL_BASE_BACKUP_LOCK_ROOT="$BACKUP_ROOT"
if ! "$PYTHON" scripts/sentinel_backup_lock.py verify >/dev/null 2>&1; then
  exec "$PYTHON" scripts/sentinel_backup_lock.py hold \
    bash scripts/sentinel-restore-drill.sh "$@"
fi
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
  NAME=""
  while IFS= read -r CANDIDATE; do
    [ -n "$CANDIDATE" ] || continue
    if ${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
      name="$1"
      test -f "/sentinel-backup/base/$name/backup_manifest"
      test -f "/sentinel-backup/base/$name/sentinel-recovery-marker"
    ' sh "$CANDIDATE" >/dev/null 2>&1; then
      NAME="$CANDIDATE"
      break
    fi
  done < <(printf '%s\n' "$CANDIDATES" \
    | grep -E "$COMPLETED_NAME_RE" | sort -r || true)
fi
[ -n "$NAME" ] || { echo "REFUSED: no complete base backup exists" >&2; exit 4; }
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
  system_id="$(sed -n "s/^system_identifier=//p" "$file")"
  printf "%s|%s|%s\n" "$marker" "$lsn" "$system_id"
' sh "$NAME")"
IFS='|' read -r MARKER TARGET_LSN SYSTEM_ID <<EOF
$MARKER_ROW
EOF
[ -n "$MARKER" ] && [ -n "$TARGET_LSN" ] || {
  echo "REFUSED: recovery marker metadata is malformed" >&2; exit 4; }
[[ "$MARKER" =~ ^sentinel-backup-[0-9]{8}T[0-9]{6}Z-[0-9]+$ ]] || {
  echo "REFUSED: recovery marker identity is malformed" >&2; exit 4; }
[[ "$TARGET_LSN" =~ ^[0-9A-F]+/[0-9A-F]+$ ]] || {
  echo "REFUSED: recovery marker LSN is malformed" >&2; exit 4; }

# New backups are bound to a PostgreSQL system-id WAL namespace. Legacy backups
# created before this contract intentionally retain the old flat restore path so
# historical recovery evidence remains usable and untouched.
if [ -n "$SYSTEM_ID" ]; then
  [[ "$SYSTEM_ID" =~ ^[0-9]+$ ]] || {
    echo "REFUSED: backup PostgreSQL system identifier is malformed" >&2; exit 4; }
  WAL_SOURCE="$BACKUP_ROOT/wal/cluster-$SYSTEM_ID"
  ${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
    system_id="$1"
    path="/sentinel-backup/wal/cluster-$system_id"
    test -d "$path"
    test ! -L "$path"
  ' sh "$SYSTEM_ID" >/dev/null || {
    echo "REFUSED: cluster-specific WAL namespace is unavailable for backup" >&2
    exit 4
  }
else
  WAL_SOURCE="$BACKUP_ROOT/wal"
fi

metadata_digest() {
  ${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
    cd "/sentinel-backup/base/$1"
    for field in backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity; do
      test -f "$field" && test ! -L "$field" && test "$(stat -c %h "$field")" = 1
    done
    sha256sum backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity | sha256sum
  ' sh "$NAME" | cut -d ' ' -f 1
}
METADATA_SHA256=""
if [ -n "$SYSTEM_ID" ]; then
  METADATA_SHA256="$(metadata_digest)"
  [[ "$METADATA_SHA256" =~ ^[0-9a-f]{64}$ ]] || {
    echo 'REFUSED: restore metadata digest unavailable' >&2; exit 4; }
fi

TOKEN="$(date -u +%Y%m%dT%H%M%SZ)-$$-$("$PYTHON" -c 'import secrets; print(secrets.token_hex(16))')"
VOLUME="sentinel-restore-drill-$TOKEN"
CONTAINER="sentinel-restore-drill-$TOKEN"
NETWORK="sentinel-restore-drill-$TOKEN"
VOLUME_CREATED=0
NETWORK_CREATED=0
CONTAINER_STARTED=0
SEMANTIC_STARTED=0
cleanup() {
  if [ "$SEMANTIC_STARTED" -eq 1 ]; then docker rm -f "$CONTAINER-semantic" >/dev/null 2>&1 || true; fi
  if [ "$CONTAINER_STARTED" -eq 1 ]; then docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; fi
  if [ "$VOLUME_CREATED" -eq 1 ]; then docker volume rm "$VOLUME" >/dev/null 2>&1 || true; fi
  if [ "$NETWORK_CREATED" -eq 1 ]; then docker network rm "$NETWORK" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo 'REFUSED: restore volume identity already exists' >&2; exit 4
fi
for object in "$CONTAINER" "$CONTAINER-semantic"; do
  if docker container inspect "$object" >/dev/null 2>&1; then
    echo 'REFUSED: restore container identity already exists' >&2; exit 4
  fi
done
docker volume create --label sentinel.restore-drill=v1 "$VOLUME" >/dev/null
VOLUME_CREATED=1
docker network create --internal --label sentinel.restore-drill=v1 "$NETWORK" >/dev/null
NETWORK_CREATED=1
# One worker owns the media lock continuously through copy, verify and replay.
# Its finite lifetime also releases the lock when its host/Docker client dies.
docker run -d --rm --name "$CONTAINER" --network "$NETWORK" \
  --label sentinel.restore-drill=v1 --memory 1g --pids-limit 128 \
  -e "SENTINEL_RESTORE_TARGET_LSN=$TARGET_LSN" \
  --network-alias restored-postgres \
  -v "$LATEST:/source:ro" -v "$BACKUP_ROOT/base:/backup-lock" \
  -v "$(pwd -P)/scripts/sentinel-backup-media-lock.sh:/media-lock-helper:ro" \
  -v "$(pwd -P)/scripts/sentinel-restore-worker.sh:/restore-worker:ro" \
  -v "$VOLUME:/var/lib/postgresql/data" -v "$WAL_SOURCE:/archive:ro" \
  --entrypoint timeout \
  postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b \
  --kill-after=30s 1800 sh /restore-worker >/dev/null
CONTAINER_STARTED=1

for _ in $(seq 1 1200); do
  if docker exec "$CONTAINER" pg_isready -U sentinel -d sentinel >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$CONTAINER" pg_isready -U sentinel -d sentinel >/dev/null
for _ in $(seq 1 60); do
  REPLAYED="$(docker exec "$CONTAINER" psql -U sentinel -d sentinel -Atc \
    "SELECT CASE WHEN pg_last_wal_replay_lsn() >= '$TARGET_LSN'::pg_lsn
       AND pg_get_wal_replay_pause_state() = 'paused'
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

record_restore_evidence() {
  # The disposable database proves restore; the live primary stores only the
  # resulting operator evidence. This never feeds strategy or execution state.
  ${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel \
    -v ON_ERROR_STOP=1 -Atc "
      WITH evidence AS (
        SELECT jsonb_build_object(
          'base_backup','$NAME','marker','$MARKER','target_lsn','$TARGET_LSN',
          'system_identifier','$SYSTEM_ID','physical_only',false,
          'metadata_sha256','$METADATA_SHA256','runtime_image','$RUNTIME_IMAGE') AS proof
      )
      INSERT INTO sentinel_backup_evidence(kind,evidence_sha256,proof)
      SELECT 'RESTORE_DRILL',
             encode(sha256(convert_to(proof::text,'UTF8')),'hex'),proof
        FROM evidence;" >/dev/null
}

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

SEMANTIC_STARTED=1
docker run --rm --name "$CONTAINER-semantic" --label sentinel.restore-drill=v1 \
  --network "$NETWORK" --read-only --cap-drop ALL --memory 1g --pids-limit 128 \
  --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  -e SENTINEL_RESTORE_DATABASE_HOST=restored-postgres \
  -e SENTINEL_RESTORE_DATABASE_PASSWORD="$SENTINEL_POSTGRES_PASSWORD" \
  --entrypoint python "$RUNTIME_IMAGE" -c \
  'import runpy,signal; signal.alarm(600); runpy.run_module("sentinel.restore_validation",run_name="__main__")'
echo "restore_semantics_ready:true backup=$LATEST image=$RUNTIME_IMAGE"
if [ -n "$METADATA_SHA256" ]; then
  [ "$(metadata_digest)" = "$METADATA_SHA256" ] || {
    echo 'REFUSED: backup metadata changed during restore' >&2; exit 4; }
fi
record_restore_evidence
