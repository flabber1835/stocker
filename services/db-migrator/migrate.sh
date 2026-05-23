#!/bin/sh
set -e

# Wait for postgres to accept connections before running alembic.
# Root cause on Synology NAS: pg_isready uses -h 127.0.0.1 (localhost inside
# the postgres container), so depends_on:service_healthy fires before the
# docker bridge network IP is routable.  psycopg2 then gets "Connection timed
# out" on the bridge IP.  We retry up to MAX_RETRIES times with a hard
# connect_timeout so we fail fast per attempt and don't wait for the OS
# TCP timeout (~120s).  Total budget: 10 x (10s timeout + 10s delay) = 200s.

MAX_RETRIES=10
DELAY=10

wait_for_db() {
    i=0
    while [ $i -lt $MAX_RETRIES ]; do
        python - <<'EOF'
import os, sys, psycopg2
url = os.environ.get("DATABASE_URL", "")
try:
    conn = psycopg2.connect(url, connect_timeout=10)
    conn.close()
    sys.exit(0)
except Exception as e:
    print(f"[db-migrator] DB not ready: {e}", flush=True)
    sys.exit(1)
EOF
        rc=$?
        if [ $rc -eq 0 ]; then
            echo "[db-migrator] DB connection OK" >&2
            return 0
        fi
        i=$((i + 1))
        if [ $i -lt $MAX_RETRIES ]; then
            echo "[db-migrator] Retry $i/$MAX_RETRIES in ${DELAY}s..." >&2
            sleep $DELAY
        fi
    done
    echo "[db-migrator] FATAL: cannot connect to DB after $MAX_RETRIES attempts" >&2
    exit 1
}

wait_for_db

echo "[db-migrator] Running: alembic upgrade head" >&2
alembic -c /app/alembic.ini upgrade head
echo "[db-migrator] Migration complete" >&2
