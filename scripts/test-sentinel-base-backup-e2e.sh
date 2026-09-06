#!/usr/bin/env bash
# Exercise the actual production base-backup/status scripts against a real
# PostgreSQL container and the real backup overlay. No broker or Sharadar access.
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_ROOT="$(mktemp -d /tmp/sentinel-backup-e2e.XXXXXX)"
export SENTINEL_BACKUP_DIR="$BACKUP_ROOT"
export SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1
export SENTINEL_POSTGRES_PASSWORD="sentinel-backup-e2e-password"
export SENTINEL_PUBLICATION_RECEIPT_KEY="sentinel-backup-e2e-receipt-key"
export SENTINEL_FORCE_CPU_LIMITS=1

POSTGRES_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
COMPOSE=(docker compose -f docker-compose.sentinel.yml -f docker-compose.sentinel-backup.yml)

cleanup() {
  local rc=$?
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  # Production intentionally creates root/postgres-owned durable artifacts.
  # Remove them through the pinned container as root so test cleanup does not
  # turn a successful production backup into a false CI failure.
  if [ -d "$BACKUP_ROOT" ]; then
    docker run --rm --network none \
      -v "$BACKUP_ROOT:/cleanup" --entrypoint sh "$POSTGRES_IMAGE" \
      -ceu 'find /cleanup -mindepth 1 -delete' >/dev/null 2>&1 || true
    rm -rf "$BACKUP_ROOT" || true
  fi
  return "$rc"
}
trap cleanup EXIT

mkdir -p "$BACKUP_ROOT/wal" "$BACKUP_ROOT/base"
# The production WAL writer is PostgreSQL's container uid. CI uses a temporary
# directory on the runner, so make the parent writable before the production
# marker initializer narrows the marker itself to its reviewed mode.
chmod 0777 "$BACKUP_ROOT/wal" "$BACKUP_ROOT/base"

bash scripts/sentinel-compose.sh --initialize-backup >/tmp/sentinel-backup-e2e-init.txt
"${COMPOSE[@]}" up -d sentinel-postgres

container_id="$("${COMPOSE[@]}" ps -q sentinel-postgres)"
[ -n "$container_id" ] || {
  echo "E2E_REFUSED: sentinel-postgres container was not created" >&2
  exit 1
}

healthy=0
for _ in $(seq 1 60); do
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
  if [ "$state" = healthy ]; then
    healthy=1
    break
  fi
  if [ "$state" = dead ] || [ "$state" = exited ]; then
    break
  fi
  sleep 1
done
[ "$healthy" -eq 1 ] || {
  echo "E2E_REFUSED: sentinel-postgres did not become healthy" >&2
  "${COMPOSE[@]}" logs --no-color sentinel-postgres >&2 || true
  exit 1
}

set +e
backup_output="$(bash scripts/sentinel-base-backup.sh 2>&1)"
backup_rc=$?
set -e
printf '%s\n' "$backup_output"
if [ "$backup_rc" -ne 0 ]; then
  echo "E2E_REFUSED: production sentinel-base-backup.sh failed rc=$backup_rc" >&2
  exit "$backup_rc"
fi

printf '%s\n' "$backup_output" | grep -q '^SENTINEL_BASE_BACKUP_DB_MUTATION=RECOVERY_MARKER_SCHEMA_AND_ROW$'
backup_path="$(printf '%s\n' "$backup_output" | sed -n 's/^verified_base_backup://p')"
[ -n "$backup_path" ] || {
  echo "E2E_REFUSED: verified base-backup path evidence was not emitted" >&2
  exit 1
}

status_output="$(bash scripts/sentinel-backup-status.sh --backup "$backup_path")"
printf '%s\n' "$status_output"
printf '%s\n' "$status_output" | grep -q '^backup_ready:true '

echo "sentinel_base_backup_e2e:PASS"
