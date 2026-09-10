#!/usr/bin/env bash
# Prove the production archive command survives recovery promotion to a new
# PostgreSQL timeline and preserves the history object needed for later PITR.
set -euo pipefail
cd "$(dirname "$0")/.."
image="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"

docker run --rm -i --network none --user postgres \
  -v "$PWD/scripts/sentinel-archive-wal.sh:/lab/archive.sh:ro" \
  --entrypoint bash "$image" -seu <<'INNER'
work="$(mktemp -d /tmp/sentinel-timeline-lab.XXXXXX)"
primary="$work/primary"
base="$work/base"
restored="$work/restored"
fresh="$work/fresh"
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
fail() { echo "BACKUP_TIMELINE_FAIL: $*" >&2; exit 1; }

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
sql() { psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c "$1"; }
system_id="$(sql 'SELECT system_identifier::text FROM pg_control_system()')"
namespace="$archive/cluster-$system_id"

sql "CREATE TABLE timeline_lab(id integer PRIMARY KEY, note text NOT NULL);
     INSERT INTO timeline_lab VALUES (1,'before-base'); CHECKPOINT;" >/dev/null
pg_basebackup -h "$work" -D "$base" -Fp -Xs -c fast >/dev/null
pg_verifybackup "$base" >/dev/null
sql "INSERT INTO timeline_lab VALUES (2,'after-base');" >/dev/null
target_lsn="$(sql 'SELECT pg_current_wal_lsn()')"
required_wal="$(sql 'SELECT pg_walfile_name(pg_switch_wal())')"
for _ in $(seq 1 80); do
  [ -f "$namespace/$required_wal" ] && break
  sleep 0.1
done
[ -f "$namespace/$required_wal" ] || fail "post-base WAL was not archived"
pg_ctl -D "$primary" -m fast -w stop >/dev/null

cp -a "$base" "$restored"
cat >> "$restored/postgresql.auto.conf" <<EOF
archive_mode = on
archive_command = '/bin/sh /lab/archive.sh %p %f $archive'
restore_command = 'cp $namespace/%f %p'
recovery_target_lsn = '$target_lsn'
recovery_target_action = 'promote'
recovery_target_timeline = '1'
unix_socket_directories = '$work'
listen_addresses = ''
EOF
touch "$restored/recovery.signal"
pg_ctl -D "$restored" -l "$work/restored.log" -w start >/dev/null || {
  cat "$work/restored.log" >&2
  fail "restored cluster did not start"
}
promoted=0
for _ in $(seq 1 80); do
  if [ "$(sql 'SELECT pg_is_in_recovery()' 2>/dev/null || true)" = f ]; then
    promoted=1
    break
  fi
  sleep 0.1
done
[ "$promoted" -eq 1 ] || {
  cat "$work/restored.log" >&2
  fail "restored cluster remained in recovery"
}

new_wal="$(sql 'SELECT pg_walfile_name(pg_switch_wal())')"
new_timeline="${new_wal:0:8}"
[ "$new_timeline" = "00000002" ] || fail "promotion did not create timeline 2: $new_wal"
history="00000002.history"
for _ in $(seq 1 80); do
  [ -f "$namespace/$history" ] && [ -f "$namespace/$history.sha256" ] && \
  [ -f "$namespace/$new_wal" ] && break
  sleep 0.1
done
[ -f "$namespace/$history" ] || fail "timeline history was not archived"
[ -f "$namespace/$history.sha256" ] || fail "timeline history checksum was not archived"
[ -f "$namespace/$new_wal" ] || fail "timeline-2 WAL was not archived"
checksum="$(sed -n 's/^sha256=//p' "$namespace/$history.sha256")"
observed="$(sha256sum "$namespace/$history" | awk '{print $1}')"
[ "$checksum" = "$observed" ] || fail "timeline history checksum does not match"

sql "INSERT INTO timeline_lab VALUES (3,'timeline-two');" >/dev/null
pg_basebackup -h "$work" -D "$fresh" -Fp -Xs -c fast >/dev/null
pg_verifybackup "$fresh" >/dev/null
grep -Eq '"Timeline"[[:space:]]*:[[:space:]]*2' "$fresh/backup_manifest" || \
  fail "fresh base backup is not bound to timeline 2"

printf 'BACKUP_TIMELINE_PASS system_id=%s history=%s wal=%s fresh_timeline=2\n' \
  "$system_id" "$history" "$new_wal"
INNER