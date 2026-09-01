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

fail() {
  echo "PR301_PITR_REFUSED: $*" >&2
  exit 1
}

require_equal() {
  label="$1" got="$2" expected="$3"
  [ "$got" = "$expected" ] || \
    fail "$label: got=$got expected=$expected"
}

wait_for_archive() {
  file="$1"
  for _ in $(seq 1 60); do
    [ -f "$archive/$file" ] && return 0
    sleep 1
  done
  fail "archive did not receive $file"
}

timeline_hex() {
  psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT substring(pg_walfile_name(pg_current_wal_lsn()) from 1 for 8)"
}

xid_epoch() {
  case "$1" in
    ''|*[!0-9]*) fail "invalid xid8: $1" ;;
  esac
  psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT trunc($1::numeric / 4294967296)::bigint"
}

xid32() {
  case "$1" in
    ''|*[!0-9]*) fail "invalid xid8: $1" ;;
  esac
  psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c \
    "SELECT mod($1::numeric, 4294967296)::bigint"
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
[ -n "$p_xid8" ] && [ -n "$p_xid" ] && [ -n "$p_timeline_hex" ] || \
  fail "publication P did not report complete PITR identity"
p_epoch="$(xid_epoch "$p_xid8")"
require_equal "base/publication xid epoch" "$base_epoch" "$p_epoch"
require_equal "xid8/low-xid projection" "$(xid32 "$p_xid8")" "$p_xid"

psql -h "$work" -v ON_ERROR_STOP=1 -q \
  -c "INSERT INTO pitr_probe(id, publication_fingerprint) VALUES ('Q', repeat('f',64));"
p_wal="$(psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
  -c 'SELECT pg_walfile_name(pg_current_wal_lsn())')"
psql -h "$work" -Atq -v ON_ERROR_STOP=1 -c "SELECT pg_switch_wal();" >/dev/null
wait_for_archive "$p_wal"
pg_ctl -D "$primary" -m fast -w stop >/dev/null

# Fork history immediately after the base backup. Recovery/promotion itself may
# advance nextXid on some PostgreSQL builds. Observe nextXid without allocating
# one and consume harmless transactions until the branch's NEXT xid is exactly
# P's xid. R is then committed under the same 32-bit xid on a different WAL
# timeline, making the ambiguity deterministic rather than scheduler-sensitive.
cp -a "$base" "$branch"
cat >> "$branch/postgresql.auto.conf" <<EOF
restore_command = 'cp $archive/%f %p'
recovery_target = 'immediate'
recovery_target_action = 'promote'
EOF
touch "$branch/recovery.signal"
pg_ctl -D "$branch" -o "-k $work" -w start >/dev/null
require_equal "branch promoted" \
  "$(psql -h "$work" -Atq -c 'SELECT pg_is_in_recovery()')" "f"
branch_timeline_hex="$(timeline_hex)"
[ "$branch_timeline_hex" != "$p_timeline_hex" ] || \
  fail "promotion did not create a new WAL timeline"

aligned=0
for _ in $(seq 1 64); do
  next_xid8="$(psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
    -c 'SELECT pg_snapshot_xmax(pg_current_snapshot())::text')"
  next_xid="$(xid32 "$next_xid8")"
  next_epoch="$(xid_epoch "$next_xid8")"
  require_equal "branch/publication xid epoch" "$next_epoch" "$p_epoch"
  if [ "$next_xid" = "$p_xid" ]; then
    aligned=1
    break
  fi
  if [ "$next_xid" -gt "$p_xid" ]; then
    fail "fork next xid $next_xid already passed publication xid $p_xid"
  fi
  # pg_current_xact_id() allocates exactly one XID to this otherwise harmless
  # transaction; the next snapshot therefore advances by one.
  psql -h "$work" -Atq -v ON_ERROR_STOP=1 \
    -c 'SELECT pg_current_xact_id()::text' >/dev/null
done
[ "$aligned" -eq 1 ] || \
  fail "could not align fork next xid to publication xid $p_xid"

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
require_equal "fork reused publication xid" "$r_xid" "$p_xid"
require_equal "fork reused publication xid epoch" \
  "$(xid_epoch "$r_xid8")" "$p_epoch"
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
require_equal "latest timeline excludes original P" \
  "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='P'")" "0"
require_equal "latest timeline selected fork R" \
  "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='R'")" "1"
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

require_equal "explicit timeline includes P" \
  "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='P'")" "1"
require_equal "explicit timeline excludes later Q" \
  "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='Q'")" "0"
require_equal "explicit timeline excludes fork R" \
  "$(psql -h "$work" -Atq -c "SELECT count(*) FROM pitr_probe WHERE id='R'")" "0"
require_equal "publication fingerprint" \
  "$(psql -h "$work" -Atq -c "SELECT publication_fingerprint FROM pitr_probe WHERE id='P'")" \
  "$fingerprint"
require_equal "target recovery promoted" \
  "$(psql -h "$work" -Atq -c 'SELECT pg_is_in_recovery()')" "f"

printf 'PR301_PITR_PASS xid8=%s xid=%s epoch=%s timeline=0x%s branch=0x%s fingerprint=%s\n' \
  "$p_xid8" "$p_xid" "$p_epoch" "$p_timeline_hex" "$branch_timeline_hex" "$fingerprint"
PR301_PITR_INNER
