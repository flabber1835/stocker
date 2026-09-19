#!/bin/sh
# PG16 container worker: retain fd 9 across copy and the PostgreSQL process.
set -eu
printf '%s\n' "${SENTINEL_RESTORE_TARGET_LSN:-}" | grep -Eq '^[0-9A-F]+/[0-9A-F]+$' || {
  echo 'REFUSED: restore worker requires the recorded target LSN' >&2; exit 4; }
. /media-lock-helper
sentinel_media_lock /backup-lock shared
cp -a /source/. /var/lib/postgresql/data/
pg_verifybackup --ignore=sentinel-recovery-marker --ignore=sentinel-pitr-base-identity \
  /var/lib/postgresql/data
chown -R postgres:postgres /var/lib/postgresql/data
chmod 700 /var/lib/postgresql/data
touch /var/lib/postgresql/data/recovery.signal
chown postgres:postgres /var/lib/postgresql/data/recovery.signal
exec docker-entrypoint.sh postgres -c 'restore_command=cp /archive/%f %p' -c 'listen_addresses=*' \
  -c "recovery_target_lsn=$SENTINEL_RESTORE_TARGET_LSN" -c recovery_target_action=pause
