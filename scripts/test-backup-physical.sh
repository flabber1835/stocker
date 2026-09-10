#!/usr/bin/env bash
# Real PostgreSQL recovery falsifiers in one disposable, offline container.
set -euo pipefail
cd "$(dirname "$0")/.."
POSTGRES_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
# Replay the actual NAS ownership incident under Docker before physical replay.
bash scripts/test-backup-marker-container-authority.sh
docker run --rm -i --network none --user postgres \
  -v "$PWD/scripts/sentinel-archive-wal.sh:/lab/archive.sh:ro" \
  --entrypoint bash "$POSTGRES_IMAGE" -seu <<'BACKUP_PHYSICAL_INNER'
work="$(mktemp -d /tmp/sentinel-backup-lab.XXXXXX)"
primary="$work/primary"
base="$work/base"
restored="$work/restored"
archive="$work/archive"
mkdir "$archive"
printf '%s\n' sentinel-independent-durable-target-v1 \
  > "$archive/.sentinel-independent-durable-target-v1"
cleanup() {
  pg_ctl -D "$primary" -m immediate stop >/dev/null 2>&1 || true
  pg_ctl -D "$restored" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
fail() { echo "BACKUP_PHYSICAL_FAIL: $*" >&2; exit 1; }
sql() { psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c "$1"; }
wait_archive() {
  for _ in $(seq 1 50); do
    [ -f "$namespace/$1" ] && return 0
    sleep 0.2
  done
  fail "archive missing $1"
}
initdb -D "$primary" -A trust --no-locale >/dev/null
cat >> "$primary/postgresql.conf" <<EOF
listen_addresses = ''
unix_socket_directories = '$work'
wal_level = replica
max_wal_senders = 4
archive_mode = on
archive_command = '/bin/sh /lab/archive.sh %p %f $archive'
EOF
pg_ctl -D "$primary" -l "$work/primary.log" -w start >/dev/null
system_id="$(sql 'SELECT system_identifier::text FROM pg_control_system()')"
namespace="$archive/cluster-$system_id"
sql "CREATE TABLE backup_lab (id integer PRIMARY KEY, amount numeric NOT NULL, note text NOT NULL);
     INSERT INTO backup_lab VALUES (1, 123.45, 'before-base'); CHECKPOINT;" >/dev/null
pg_basebackup -h "$work" -D "$base" -Fp -Xs -c fast >/dev/null
pg_verifybackup "$base"
sql "INSERT INTO backup_lab VALUES (2, 987.65, 'after-base-first');" >/dev/null
middle="$(sql 'SELECT pg_walfile_name(pg_switch_wal())')"
wait_archive "$middle"
sql "INSERT INTO backup_lab VALUES (3, 0.01, 'after-base-second');" >/dev/null
sql "SELECT pg_create_restore_point('backup-lab-target')" >/dev/null
marker="$(sql 'SELECT pg_walfile_name(pg_switch_wal())')"
wait_archive "$marker"
expected="$(sql "SELECT string_agg(id::text || ':' || amount::text || ':' || note, '|' ORDER BY id) FROM backup_lab")"
pg_ctl -D "$primary" -m fast -w stop >/dev/null

# Verify creation-time success cannot conceal later corruption of a relation.
relation="$(find "$base/base" -type f -size +8192c | head -1)"
[ -n "$relation" ] || fail "no relation available for corruption falsifier"
cp "$relation" "$work/original-relation"
printf BAD | dd of="$relation" bs=1 seek=4096 conv=notrunc status=none
if pg_verifybackup "$base" >"$work/verify-corrupt.log" 2>&1; then
  fail "corrupted relation passed manifest verification"
fi
cp "$work/original-relation" "$relation"
pg_verifybackup "$base" >/dev/null
echo 'BACKUP_PHYSICAL_PASS post_creation_bit_rot_refused'

cp "$namespace/$middle" "$work/middle"
cp "$namespace/$marker" "$work/marker"
for scenario in clean missing-middle truncated-marker repaired; do
  cp "$work/middle" "$namespace/$middle"
  cp "$work/marker" "$namespace/$marker"
  case "$scenario" in
    missing-middle) rm "$namespace/$middle" ;;
    truncated-marker) truncate -s 128 "$namespace/$marker" ;;
  esac
  rm -rf "$restored"
  cp -a "$base" "$restored"
  pg_verifybackup "$restored" >/dev/null
  cat >> "$restored/postgresql.auto.conf" <<EOF
archive_mode = off
restore_command = 'cp $namespace/%f %p'
recovery_target_name = 'backup-lab-target'
recovery_target_action = promote
recovery_target_timeline = '1'
EOF
  touch "$restored/recovery.signal"
  pg_ctl -D "$restored" -l "$work/$scenario.log" -W start >/dev/null
  recovered=0
  for _ in $(seq 1 60); do
    if [ "$(sql 'SELECT pg_is_in_recovery()' 2>/dev/null || true)" = f ]; then
      recovered=1
      break
    fi
    pg_ctl -D "$restored" status >/dev/null 2>&1 || break
    sleep 0.2
  done
  case "$scenario" in
    clean|repaired)
      [ "$recovered" -eq 1 ] || { cat "$work/$scenario.log" >&2; fail "$scenario failed recovery"; }
      actual="$(sql "SELECT string_agg(id::text || ':' || amount::text || ':' || note, '|' ORDER BY id) FROM backup_lab")"
      [ "$actual" = "$expected" ] || fail "$scenario restored contents differ"
      ;;
    *) [ "$recovered" -eq 0 ] || fail "$scenario falsely recovered" ;;
  esac
  pg_ctl -D "$restored" -m immediate stop >/dev/null 2>&1 || true
  printf 'BACKUP_PHYSICAL_PASS %s\n' "$scenario"
done
printf 'BACKUP_PHYSICAL_PASS exact_rows=%s system_id=%s\n' "$expected" "$system_id"
BACKUP_PHYSICAL_INNER
