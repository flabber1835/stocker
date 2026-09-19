#!/bin/bash
# Run INSIDE the pinned PG16 image, network none, root, disposable filesystem.
set -euo pipefail
test "$(id -u)" = 0
test ! -e /tmp/maintenance-primary
export POSTGRES_USER=sentinel POSTGRES_DB=sentinel
mkdir /tmp/maintenance-primary /tmp/maintenance-socket /archive /source /backup-lock
chown postgres:postgres /tmp/maintenance-primary /tmp/maintenance-socket /archive
gosu postgres initdb -D /tmp/maintenance-primary -U sentinel -A trust --no-locale >/dev/null
cat >> /tmp/maintenance-primary/postgresql.conf <<'CONFIG'
listen_addresses = '127.0.0.1'
unix_socket_directories = '/tmp/maintenance-socket'
wal_level = replica
archive_mode = on
archive_command = 'test -f /archive/%f || cp %p /archive/%f'
CONFIG
cleanup() {
  gosu postgres pg_ctl -D /tmp/maintenance-primary -m immediate stop >/dev/null 2>&1 || true
  gosu postgres pg_ctl -D /var/lib/postgresql/data -m immediate stop >/dev/null 2>&1 || true
}
trap cleanup EXIT
gosu postgres pg_ctl -D /tmp/maintenance-primary -l /tmp/primary.log -w start >/dev/null
psql -h /tmp/maintenance-socket -U sentinel -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE DATABASE sentinel' >/dev/null
psql -h /tmp/maintenance-socket -U sentinel -d sentinel -v ON_ERROR_STOP=1 \
  -c 'CREATE TABLE marker (value text PRIMARY KEY)' >/dev/null
pg_basebackup -h /tmp/maintenance-socket -U sentinel -D /source -Fp -Xs -c fast
pg_verifybackup /source
psql -h /tmp/maintenance-socket -U sentinel -d sentinel -v ON_ERROR_STOP=1 \
  -c "INSERT INTO marker VALUES ('after-base-recovery')" >/dev/null
wal="$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_walfile_name(pg_current_wal_lsn())')"
export SENTINEL_RESTORE_TARGET_LSN="$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_current_wal_lsn()')"
psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_switch_wal()' >/dev/null
for _ in $(seq 1 100); do
  test ! -f "/archive/$wal" || break
  sleep .1
done
test -f "/archive/$wal"
gosu postgres pg_ctl -D /tmp/maintenance-primary -m fast -w stop >/dev/null
printf 'fixture metadata\n' >/source/sentinel-recovery-marker
printf 'fixture metadata\n' >/source/sentinel-pitr-base-identity
timeout --kill-after=10s 120 sh /restore-worker >/tmp/restored.log 2>&1 &
worker=$!
for _ in $(seq 1 100); do
  if psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc \
      "SELECT value FROM marker WHERE value='after-base-recovery'" 2>/dev/null | grep -qx after-base-recovery; then
    break
  fi
  kill -0 "$worker" || { cat /tmp/restored.log; exit 1; }
  sleep .1
done
if [ "$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_is_in_recovery()')" != t ]; then
  echo 'RECOVERY_TARGET_NOT_PAUSED: recovered automatically to archive end'; exit 1
fi
test "$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT value FROM marker')" = after-base-recovery
if [ "$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_get_wal_replay_pause_state()')" != paused ]; then
  echo 'RECOVERY_TARGET_NOT_PAUSED: replay has no stable target'; exit 1
fi
if flock -x -n /backup-lock/.sentinel-maintenance.lock true; then
  echo 'FAIL: actual PostgreSQL did not retain the worker media lock' >&2
  exit 1
fi
echo 'PG16_RESTORE_WORKER: marker replayed; exclusive retention fenced during actual PostgreSQL recovery'
test "$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_promote(true,10)')" = t
test "$(psql -h /tmp/maintenance-socket -U sentinel -d sentinel -Atc 'SELECT pg_is_in_recovery()')" = f
echo 'PG16_RESTORE_WORKER: explicit promotion succeeded after target pause'
gosu postgres pg_ctl -D /var/lib/postgresql/data -m fast -w stop >/dev/null
wait "$worker"
flock -x -n /backup-lock/.sentinel-maintenance.lock true
echo 'PG16_RESTORE_WORKER: shutdown released media lock'
# A changed source relation must be rejected by the real verification tool.
relation="$(find /source/base -type f -size +0c -print -quit)"
test -n "$relation"
printf CORRUPT | dd of="$relation" conv=notrunc status=none
if pg_verifybackup --ignore=sentinel-recovery-marker --ignore=sentinel-pitr-base-identity /source >/tmp/corrupt.log 2>&1; then
  echo 'FAIL: corrupted source passed physical verification' >&2
  exit 1
fi
cat /tmp/corrupt.log
echo 'PG16_RESTORE_WORKER: corrupted source refused'
