#!/bin/sh
set -e

# pg_isready passes on 127.0.0.1 inside the postgres container before the
# bridge IP (e.g. 192.168.64.2) is routable from other containers on NAS.
# The `if python` form is used deliberately: `set -e` would abort the script
# on a bare `python; rc=$?` when python exits 1, bypassing the retry loop.
MAX_RETRIES=20
DELAY=10

wait_for_db() {
    i=0
    while [ $i -lt $MAX_RETRIES ]; do
        if python - <<'EOF'
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
        then
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
