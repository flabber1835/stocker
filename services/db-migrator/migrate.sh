#!/bin/sh
set -e

# Wait for postgres to accept connections before running alembic.
# pg_isready (the docker healthcheck) returns 0 as soon as the postmaster
# accepts connections, but psycopg2 occasionally hits "connection refused"
# in the brief window between pg_isready succeeding and the backend being
# fully ready on the docker bridge network.  Retry up to 5 times.

MAX_RETRIES=5
DELAY=5

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
