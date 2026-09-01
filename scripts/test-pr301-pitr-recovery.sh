#!/usr/bin/env bash
set -euo pipefail

POSTGRES_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"

docker run --rm -i --network none --user postgres \
  --entrypoint bash "$POSTGRES_IMAGE" -seu <<'PR301_PITR_INNER'
work="$(mktemp -d /tmp/pr301-pitr.XXXXXX)"
primary="$work/primary"
base="$work/base"
restore="$work/restore"
archive="$work/archive"
mkdir -p "$archive"
cleanup() {
  pg_ctl -D "$primary" -m immediate stop >/dev/null 2>&1 || true
  pg_ctl -D "$restore" -m immediate stop >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

initdb -D "$primary" -A trust --no-locale >/dev/null
cat >> "$primary/postgresql.conf" <<EOF
listen_addresses = ''
unix_socket_directories = '$work'
wal_level = replica
max_wal_senders = 4
archive_mode = on
archive_timeout = 1
archive_command = 'test -f $archive/%f || cp %p $archive/%f'
EOF

pg_ctl -D "$primary" -o "-k $work" -w start >/dev/null
psql -h "$work" -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE TABLE pitr_probe (
  id text PRIMARY KEY,
  publication_fingerprint text NOT NULL
);
CHECKPOINT;
SQL

# The base backup predates both economic commits. WAL replay therefore decides
# exactly which one is visible in the reconstructed database.
pg_basebackup -h "$work" -D "$base" -Fp -X stream -c fast >/dev/null

fingerprint="$(printf publication-P | sha256sum | awk '{print $1}')"
p_xid="$(psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
  -v fingerprint="$fingerprint" <<'SQL'
BEGIN;
INSERT INTO pitr_probe(id, publication_fingerprint)
VALUES ('P', :'fingerprint');
SELECT pg_current_xact_id()::text;
COMMIT;
SQL
)"
p_xid="$(printf '%s\n' "$p_xid" | awk '/^[0-9]+$/ {v=$0} END {print v}')"
test -n "$p_xid"

psql -h "$work" -v ON_ERROR_STOP=1 -q \
  -c "INSERT INTO pitr_probe(id, publication_fingerprint) VALUES ('Q', repeat('f',64));"
psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c "SELECT pg_switch_wal();" >/dev/null

# Wait until the switched segment carrying P and Q has reached the archive.
for _ in $(seq 1 60); do
  archived="$(psql -h "$work" -Atq -c 'SELECT archived_count FROM pg_stat_archiver')"
  if [ "${archived:-0}" -ge 1 ]; then
    break
  fi
  sleep 1
done
archived="$(psql -h "$work" -Atq -c 'SELECT archived_count FROM pg_stat_archiver')"
test "${archived:-0}" -ge 1
pg_ctl -D "$primary" -m fast -w stop >/dev/null

cp -a "$base" "$restore"
cat >> "$restore/postgresql.auto.conf" <<EOF
restore_command = 'cp $archive/%f %p'
recovery_target_xid = '$p_xid'
recovery_target_inclusive = true
recovery_target_action = 'promote'
EOF
touch "$restore/recovery.signal"

pg_ctl -D "$restore" -o "-k $work" -w start >/dev/null

# Inclusive XID recovery must contain publication P, exclude the later economic
# commit Q, retain the exact durable fingerprint bytes, and have promoted.
test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='P'")" = 1
test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='Q'")" = 0
test "$(psql -h "$work" -Atq -c "SELECT publication_fingerprint FROM pitr_probe WHERE id='P'")" = "$fingerprint"
test "$(psql -h "$work" -Atq -c 'SELECT pg_is_in_recovery()')" = f

printf 'PR301_PITR_PASS xid=%s fingerprint=%s\n' "$p_xid" "$fingerprint"
PR301_PITR_INNER
