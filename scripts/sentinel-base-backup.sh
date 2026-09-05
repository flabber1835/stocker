#!/usr/bin/env bash
# Create and verify one physical PostgreSQL base backup. No broker access.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 2
}

. scripts/sentinel-backup-lib.sh
BACKUP_ROOT="$(sentinel_backup_root)"
export SENTINEL_BASE_BACKUP_LOCK_ROOT="$BACKUP_ROOT"
if ! "$PYTHON" scripts/sentinel_backup_lock.py verify >/dev/null 2>&1; then
  exec "$PYTHON" scripts/sentinel_backup_lock.py hold \
    bash scripts/sentinel-base-backup.sh "$@"
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="base-$STAMP"
STAGING=".$NAME.part-$$"
MARKER="sentinel-backup-$STAMP-$$"

COMPOSE=(docker compose -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml)
STAGING_CREATED=0
cleanup_staging() {
  local rc=$?
  if [ "$STAGING_CREATED" -eq 1 ]; then
    ${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
      staging="$1"
      case "$staging" in .base-*.part-*) ;; *) exit 2;; esac
      rm -rf -- "/sentinel-backup/base/$staging"
      sync -f /sentinel-backup/base
    ' sh "$STAGING" >/dev/null 2>&1 || true
  fi
  return "$rc"
}
trap cleanup_staging EXIT

xid_epoch() {
  "$PYTHON" - "$1" <<'PY'
import sys
print(int(sys.argv[1]) >> 32)
PY
}

pitr_source_row() {
  ${COMPOSE[@]} exec -T sentinel-postgres psql -U sentinel -d sentinel \
    -v ON_ERROR_STOP=1 -Atc \
    "SELECT pg_snapshot_xmax(pg_current_snapshot())::text || '|' ||
            substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8)"
}

${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
  find /sentinel-backup/base -mindepth 1 -maxdepth 1 -type d \
    -name ".base-*.part-*" -exec rm -rf -- {} +
  sync -f /sentinel-backup/base
'

MODE="$(${COMPOSE[@]} exec -T sentinel-postgres \
  psql -U sentinel -d sentinel -Atc "SHOW archive_mode")"
[ "$MODE" = "on" ] || {
  echo "REFUSED: archive_mode=$MODE; start the documented backup overlay" >&2
  exit 3
}
SYSTEM_ID="$(${COMPOSE[@]} exec -T sentinel-postgres \
  psql -U sentinel -d sentinel -Atc \
  "SELECT system_identifier::text FROM pg_control_system()")"
[[ "$SYSTEM_ID" =~ ^[0-9]+$ ]] || {
  echo "REFUSED: PostgreSQL system identifier is unavailable or malformed" >&2
  exit 4
}
WAL_NAMESPACE="cluster-$SYSTEM_ID"

PITR_BEFORE="$(pitr_source_row)"
IFS='|' read -r PITR_XID8_BEFORE PITR_TIMELINE_BEFORE <<EOF
$PITR_BEFORE
EOF
[[ "$PITR_XID8_BEFORE" =~ ^[0-9]+$ ]] && \
[[ "$PITR_TIMELINE_BEFORE" =~ ^[0-9A-F]{8}$ ]] || {
  echo "REFUSED: pre-backup PITR identity is malformed" >&2
  exit 4
}
PITR_EPOCH_BEFORE="$(xid_epoch "$PITR_XID8_BEFORE")"

STAGING_CREATED=1
${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
  staging="$1" final="$2"
  test ! -e "/sentinel-backup/base/$staging"
  test ! -e "/sentinel-backup/base/$final"
  export PGPASSWORD="$POSTGRES_PASSWORD"
  pg_basebackup -h 127.0.0.1 -U sentinel -D \
    "/sentinel-backup/base/$staging" -Fp -Xs -P -c fast
  pg_verifybackup "/sentinel-backup/base/$staging"
  psql -h 127.0.0.1 -U sentinel -d sentinel -Atc "SELECT pg_switch_wal()" >/dev/null
' sh "$STAGING" "$NAME"

PITR_AFTER="$(pitr_source_row)"
IFS='|' read -r PITR_XID8_AFTER PITR_TIMELINE_AFTER <<EOF
$PITR_AFTER
EOF
[[ "$PITR_XID8_AFTER" =~ ^[0-9]+$ ]] && \
[[ "$PITR_TIMELINE_AFTER" =~ ^[0-9A-F]{8}$ ]] || {
  echo "REFUSED: post-backup PITR identity is malformed" >&2
  exit 4
}
PITR_EPOCH_AFTER="$(xid_epoch "$PITR_XID8_AFTER")"
[ "$PITR_EPOCH_BEFORE" = "$PITR_EPOCH_AFTER" ] || {
  echo "REFUSED: base backup crossed a 32-bit transaction-id epoch" >&2
  exit 4
}
[ "$PITR_TIMELINE_BEFORE" = "$PITR_TIMELINE_AFTER" ] || {
  echo "REFUSED: base backup crossed a PostgreSQL WAL timeline" >&2
  exit 4
}
${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
  staging="$1" before="$2" after="$3" epoch="$4" timeline="$5" system_id="$6"
  metadata="/sentinel-backup/base/$staging/sentinel-pitr-base-identity"
  printf "schema=sentinel.base-backup-pitr/2\nsystem_identifier=%s\nxid8_before=%s\nxid8_after=%s\nxid_epoch=%s\ntimeline=0x%s\n" \
    "$system_id" "$before" "$after" "$epoch" "$timeline" > "$metadata"
  sync "$metadata"
' sh "$STAGING" "$PITR_XID8_BEFORE" "$PITR_XID8_AFTER" \
  "$PITR_EPOCH_AFTER" "$PITR_TIMELINE_AFTER" "$SYSTEM_ID"

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
  if ! ${COMPOSE[@]} exec -T -u postgres sentinel-postgres sh -ceu '
    namespace="$1" wal="$2"
    test -d "/sentinel-backup/wal/$namespace"
    test ! -L "/sentinel-backup/wal/$namespace"
    test -f "/sentinel-backup/wal/$namespace/$wal"
    test -r "/sentinel-backup/wal/$namespace/$wal"
  ' sh "$WAL_NAMESPACE" "$MARKER_WAL"; then
    sleep 1
    continue
  fi
  ${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
    name="$1" marker="$2" lsn="$3" wal="$4" system_id="$5"
    metadata="/sentinel-backup/base/$name/sentinel-recovery-marker"
    printf "marker=%s\nlsn=%s\nwal=%s\nsystem_identifier=%s\n" \
      "$marker" "$lsn" "$wal" "$system_id" > "$metadata"
    sync "$metadata"
  ' sh "$STAGING" "$MARKER" "$MARKER_LSN" "$MARKER_WAL" "$SYSTEM_ID"
  break
done
${COMPOSE[@]} exec -T sentinel-postgres \
  test -f "/sentinel-backup/base/$STAGING/sentinel-recovery-marker" || {
  echo "REFUSED: marker WAL $MARKER_WAL was not archived in $WAL_NAMESPACE" >&2; exit 4; }

${COMPOSE[@]} exec -T sentinel-postgres sh -ceu '
  staging="$1" final="$2"
  test -d "/sentinel-backup/base/$staging"
  test -f "/sentinel-backup/base/$staging/backup_manifest"
  test -f "/sentinel-backup/base/$staging/sentinel-recovery-marker"
  test -f "/sentinel-backup/base/$staging/sentinel-pitr-base-identity"
  test ! -e "/sentinel-backup/base/$final"
  mv -T --no-clobber -- "/sentinel-backup/base/$staging" "/sentinel-backup/base/$final"
  sync -f /sentinel-backup/base
  test ! -e "/sentinel-backup/base/$staging"
  test -d "/sentinel-backup/base/$final"
' sh "$STAGING" "$NAME"
STAGING_CREATED=0
${COMPOSE[@]} exec -T sentinel-postgres \
  test -f "/sentinel-backup/base/$NAME/sentinel-recovery-marker" || {
  echo "REFUSED: promoted backup lost its post-base recovery marker" >&2; exit 4; }
${COMPOSE[@]} exec -T sentinel-postgres \
  test -f "/sentinel-backup/base/$NAME/sentinel-pitr-base-identity" || {
  echo "REFUSED: promoted backup lost its PITR base identity" >&2; exit 4; }

echo "SENTINEL_BASE_BACKUP_DB_MUTATION=RECOVERY_MARKER_SCHEMA_AND_ROW"
echo "verified_base_backup:$BACKUP_ROOT/base/$NAME"
