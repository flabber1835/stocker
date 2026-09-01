#!/usr/bin/env bash
set -euo pipefail

POSTGRES_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"

docker run --rm -i --network none --user postgres \
  --entrypoint bash "$POSTGRES_IMAGE" -seu <<'PR301_PITR_INNER'
work="$(mktemp -d /tmp/pr301-pitr.XXXXXX)"
primary="$work/primary"
base="$work/base"
branch="$work/branch"
ambiguous="$work/ambiguous"
restore="$work/restore"
archive="$work/archive"
mkdir -p "$archive"
cleanup() {
  for data in "$primary" "$branch" "$ambiguous" "$restore"; do
    pg_ctl -D "$data" -m immediate stop >/dev/null 2>&1 || true
  done
  rm -rf "$work"
}
trap cleanup EXIT

wait_for_archive() {
  file="$1"
  for _ in $(seq 1 60); do
    [ -f "$archive/$file" ] && return 0
    sleep 1
  done
  echo "archive did not receive $file" >&2
  return 1
}

timeline_hex() {
  psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8)"
}

xid_epoch() {
  psql -h "$work" -Atq -v ON_ERROR_STOP=1 -v xid8="$1" -c \
    "SELECT trunc(:'xid8'::numeric / 4294967296)::bigint"
}

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

# The base backup predates both branches. Capture its xid8 epoch after the
# backup; a publication target is admissible only when this epoch equals the
# publication's source xid8 epoch.
pg_basebackup -h "$work" -D "$base" -Fp -X stream -c fast >/dev/null
base_xid8="$(psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
  -c 'SELECT pg_snapshot_xmax(pg_current_snapshot())::text')"
base_epoch="$(xid_epoch "$base_xid8")"

fingerprint="$(printf publication-P | sha256sum | awk '{print $1}')"
p_row="$(psql -h "$work" -Atq -F '|' -v ON_ERROR_STOP=1 \
  -v fingerprint="$fingerprint" <<'SQL'
BEGIN;
INSERT INTO pitr_probe(id, publication_fingerprint)
VALUES ('P', :'fingerprint');
SELECT pg_current_xact_id()::text,
       (pg_current_xact_id()::xid)::text,
       substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8);
COMMIT;
SQL
)"
p_row="$(printf '%s\n' "$p_row" | awk -F'|' 'NF==3 {v=$0} END {print v}')"
IFS='|' read -r p_xid8 p_xid p_timeline_hex <<EOF
$p_row
EOF
test -n "$p_xid8" -a -n "$p_xid" -a -n "$p_timeline_hex"
p_epoch="$(xid_epoch "$p_xid8")"
test "$base_epoch" = "$p_epoch"

psql -h "$work" -v ON_ERROR_STOP=1 -q \
  -c "INSERT INTO pitr_probe(id, publication_fingerprint) VALUES ('Q', repeat('f',64));"
p_wal="$(psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
  -c 'SELECT pg_walfile_name(pg_current_wal_lsn())')"
psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c "SELECT pg_switch_wal();" >/dev/null
wait_for_archive "$p_wal"
pg_ctl -D "$primary" -m fast -w stop >/dev/null

# Fork history immediately after the base backup. The first write on timeline 2
# deliberately receives the same 32-bit XID as publication P did on timeline 1.
cp -a "$base" "$branch"
cat >> "$branch/postgresql.auto.conf" <<EOF
restore_command = 'cp $archive/%f %p'
recovery_target = 'immediate'
recovery_target_action = 'promote'
EOF
touch "$branch/recovery.signal"
pg_ctl -D "$branch" -o "-k $work" -w start >/dev/null
test "$(psql -h "$work" -Atq -c 'SELECT pg_is_in_recovery()')" = f
branch_timeline_hex="$(timeline_hex)"
test "$branch_timeline_hex" != "$p_timeline_hex"

r_row="$(psql -h "$work" -Atq -F '|' -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
INSERT INTO pitr_probe(id, publication_fingerprint)
VALUES ('R', repeat('a',64));
SELECT pg_current_xact_id()::text, (pg_current_xact_id()::xid)::text;
COMMIT;
SQL
)"
r_row="$(printf '%s\n' "$r_row" | awk -F'|' 'NF==2 {v=$0} END {print v}')"
IFS='|' read -r r_xid8 r_xid <<EOF
$r_row
EOF
test "$r_xid" = "$p_xid"
test "$(xid_epoch "$r_xid8")" = "$p_epoch"
r_wal="$(psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
  -c 'SELECT pg_walfile_name(pg_current_wal_lsn())')"
psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c "SELECT pg_switch_wal();" >/dev/null
wait_for_archive "$r_wal"
wait_for_archive "$branch_timeline_hex.history"
pg_ctl -D "$branch" -m fast -w stop >/dev/null

# Demonstrate the defect this test protects against. With PostgreSQL's default
# recovery_target_timeline=latest, the same XID resolves to branch R, not P.
cp -a "$base" "$ambiguous"
cat >> "$ambiguous/postgresql.auto.conf" <<EOF
restore_command = 'cp $archive/%f %p'
recovery_target_xid = '$p_xid'
recovery_target_inclusive = true
recovery_target_action = 'promote'
EOF
touch "$ambiguous/recovery.signal"
pg_ctl -D "$ambiguous" -o "-k $work" -w start >/dev/null
test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='P'")" = 0
test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='R'")" = 1
pg_ctl -D "$ambiguous" -m fast -w stop >/dev/null

# The persisted PR301/2 target names the original timeline explicitly. Recovery
# now includes P, excludes later Q and branch R, and promotes at exactly P.
cp -a "$base" "$restore"
cat >> "$restore/postgresql.auto.conf" <<EOF
restore_command = 'cp $archive/%f %p'
recovery_target_xid = '$p_xid'
recovery_target_timeline = '0x$p_timeline_hex'
recovery_target_inclusive = true
recovery_target_action = 'promote'
EOF
touch "$restore/recovery.signal"
pg_ctl -D "$restore" -o "-k $work" -w start >/dev/null

test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='P'")" = 1
test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='Q'")" = 0
test "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='R'")" = 0
test "$(psql -h "$work" -Atq -c "SELECT publication_fingerprint FROM pitr_probe WHERE id='P'")" = "$fingerprint"
test "$(psql -h "$work" -Atq -c 'SELECT pg_is_in_recovery()')" = f

printf 'PR301_PITR_PASS xid8=%s xid=%s epoch=%s timeline=0x%s branch=0x%s fingerprint=%s\n' \
  "$p_xid8" "$p_xid" "$p_epoch" "$p_timeline_hex" "$branch_timeline_hex" "$fingerprint"
PR301_PITR_INNER
