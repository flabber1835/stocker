#!/usr/bin/env bash
# Real production base creation and runtime SQL reads on the same private media.
set -euo pipefail
cd "$(dirname "$0")/.."
source_root="$PWD"
image="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
work="$(mktemp -d /tmp/sentinel-runtime-media.XXXXXXXX)"
repo="$work/repo"
export SENTINEL_BACKUP_DIR="$work/media"
export SENTINEL_BACKUP_DURABLE_TARGET_ATTESTED=1
export COMPOSE_PROJECT_NAME="backup-runtime-${work##*.}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME,,}"
export PYTHONPATH="$source_root"
export SENTINEL_HOST_PYTHON="${SENTINEL_HOST_PYTHON:-python3}"
compose=(docker compose --project-directory "$repo" -f "$repo/docker-compose.sentinel.yml"
         -f "$repo/docker-compose.sentinel-backup.yml")
fail() { echo "BACKUP_RUNTIME_FAIL: $*" >&2; exit 1; }
cleanup() {
  result=$?
  if [ "$result" -ne 0 ]; then "${compose[@]}" logs --no-color || true; fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker run --rm --network none -v "$work:/probe" --entrypoint sh "$image" \
    -ceu 'chmod -R 0777 /probe' >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
mkdir -p "$repo/scripts" "$work/socket" "$SENTINEL_BACKUP_DIR"/{base,wal}
for name in sentinel-base-backup.sh sentinel-backup-status.sh sentinel-backup-lib.sh \
            sentinel-backup-metadata-access.sh sentinel-archive-wal.sh \
            sentinel_host_python.py sentinel_backup_lock.py; do
  cp "scripts/$name" "$repo/scripts/$name"
done
cp docker-compose.sentinel-backup.yml "$repo/"
cat > "$repo/docker-compose.sentinel.yml" <<EOF
services:
  sentinel-postgres:
    image: $image
    environment:
      POSTGRES_USER: sentinel
      POSTGRES_DB: sentinel
      POSTGRES_PASSWORD: synthetic-runtime-probe
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./scripts/sentinel-backup-metadata-access.sh:/lab/metadata-access.sh:ro
      - $work/socket:/var/run/postgresql
networks:
  default:
    internal: true
volumes:
  pgdata:
EOF
docker run --rm --network none -v "$SENTINEL_BACKUP_DIR:/probe" --entrypoint sh "$image" \
  -ceu 'chown postgres:postgres /probe/wal; chmod 0700 /probe/wal;
        chown 0:0 /probe/base; chmod 0700 /probe/base'
docker run --rm --network none -v "$work/socket:/socket" --entrypoint sh "$image" \
  -ceu 'chown postgres:postgres /socket; chmod 0755 /socket'
initialize() { (cd "$repo"; . scripts/sentinel-backup-lib.sh; sentinel_backup_root --initialize-markers); }
initialize
"${compose[@]}" up -d --wait --wait-timeout 90 sentinel-postgres
sql() { "${compose[@]}" exec -T sentinel-postgres psql -U sentinel -d sentinel -Atq -v ON_ERROR_STOP=1 -c "$1"; }
sql 'CREATE TABLE private_payload (id integer PRIMARY KEY); INSERT INTO private_payload VALUES (42);'
created="$(cd "$repo"; bash scripts/sentinel-base-backup.sh)"
printf '%s\n' "$created"
backup="$(printf '%s\n' "$created" | sed -n 's/^verified_base_backup://p')"
name="${backup##*/}"
[[ "$name" =~ ^base-[0-9]{8}T[0-9]{6}Z$ ]] || fail "missing completed production base"
# The host probe reaches the network-isolated database through its Unix socket.
url="host=$work/socket user=sentinel dbname=sentinel"
probe() { "$SENTINEL_HOST_PYTHON" tests/backup/physical_runtime_probe.py "$url" "$1"; }
probe ready
(cd "$repo"; bash scripts/sentinel-backup-status.sh --backup "$backup")

# Reject aliasing and ownership drift before applying any metadata grant.
"${compose[@]}" exec -T sentinel-postgres sh -ceu '
  work="$(mktemp -d)"
  trap "rm -rf \"$work\"" 0
  printf retained > "$work/outside"
  chmod 0600 "$work/outside"
  for attack in directory-symlink metadata-symlink metadata-hardlink foreign-owner; do
    root="$work/$attack"
    base="$root/base-20260910T120000Z"
    mkdir -p "$base"
    chmod 0700 "$root" "$base"
    for name in backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity; do
      printf metadata > "$base/$name"
      chmod 0600 "$base/$name"
    done
    case "$attack" in
      directory-symlink) mv "$base" "$work/aliased-base"; ln -s "$work/aliased-base" "$base" ;;
      metadata-symlink) rm "$base/backup_manifest"; ln -s "$work/outside" "$base/backup_manifest" ;;
      metadata-hardlink) rm "$base/backup_manifest"; ln "$work/outside" "$base/backup_manifest" ;;
      foreign-owner) chown postgres:postgres "$base/backup_manifest" ;;
    esac
    if sh /lab/metadata-access.sh "$root"; then
      echo "invalid grant accepted: $attack" >&2; exit 1
    fi
    test "$(stat -c %a "$root")" = 700
    test "$(stat -c %a "$work/outside")" = 600
    test "$(cat "$work/outside")" = retained
    echo "BACKUP_RUNTIME_PASS grant_refused_$attack"
  done
'

# PostgreSQL can read metadata, but cannot modify metadata or retained payload.
"${compose[@]}" exec -T -u postgres sentinel-postgres sh -ceu '
  base="/sentinel-backup/base/$1"
  test ! -w /sentinel-backup/base
  test ! -w "$base"
  test ! -r "$base/global/pg_control"
  for name in backup_manifest backup_label sentinel-recovery-marker sentinel-pitr-base-identity; do
    test -r "$base/$name"
    test ! -w "$base/$name"
  done
' sh "$name"
printf 'BACKUP_RUNTIME_IDENTITIES host_uid=%s host_groups=%s\n' "$(id -u)" "$(id -G)"
"${compose[@]}" exec -T sentinel-postgres id postgres
"${compose[@]}" exec -T sentinel-postgres stat -c 'metadata_owner=%u:%g mode=%a' \
  "/sentinel-backup/base/$name/backup_manifest"
# Bind mounts use numeric groups. A host in PostgreSQL's numeric group receives
# the same metadata read grant. Payload reads and all backup writes stay denied.
if cat "$backup/global/pg_control" >/dev/null 2>&1; then fail "host can read private backup payload"; fi
test ! -w "$backup/backup_manifest"
test ! -w "$SENTINEL_BACKUP_DIR/base"
"${compose[@]}" exec -T -u 65534:65534 sentinel-postgres sh -ceu '
  test ! -r "/sentinel-backup/base/$1/backup_manifest"
  test ! -w /sentinel-backup/base
' sh "$name"
echo 'BACKUP_RUNTIME_PASS host_payload_and_write_denial unrelated_uid_metadata_denial'

# Reproduce the previous root-only layout, then exercise the supported upgrade.
"${compose[@]}" exec -T sentinel-postgres chmod 0700 /sentinel-backup/base "/sentinel-backup/base/$name"
probe unavailable
initialize
probe ready

system_id="$(sql 'SELECT system_identifier::text FROM pg_control_system()')"
"${compose[@]}" exec -T sentinel-postgres mv "/sentinel-backup/wal/cluster-$system_id" /sentinel-backup/wal/disconnected
probe unavailable
"${compose[@]}" exec -T sentinel-postgres mv /sentinel-backup/wal/disconnected "/sentinel-backup/wal/cluster-$system_id"
probe ready

# A missing mount marker fences a valid retained base, then heals on reconnection.
"${compose[@]}" exec -T sentinel-postgres mv /sentinel-backup/base/.sentinel-independent-durable-target-v1 /sentinel-backup/base/disconnected-marker
probe unavailable
"${compose[@]}" exec -T sentinel-postgres mv /sentinel-backup/base/disconnected-marker /sentinel-backup/base/.sentinel-independent-durable-target-v1
probe ready
printf 'BACKUP_RUNTIME_PASS production_private_media_composition\n'
