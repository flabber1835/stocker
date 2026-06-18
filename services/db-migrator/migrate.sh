#!/bin/sh
set -e

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

# Show current alembic state before upgrading
echo "[db-migrator] Current alembic state:" >&2
alembic -c /app/alembic.ini current 2>&1 || true

echo "[db-migrator] Running: alembic upgrade head" >&2
alembic -c /app/alembic.ini upgrade head
echo "[db-migrator] Migration complete" >&2

# Refresh planner statistics after every deploy. The dashboard screener's
# /rankings/with-overlays query (rank_slope REGR + prior_rank + joins to
# fundamentals/universe_tickers/vetter_decisions) is plan-sensitive: as the
# universe grew (~2050 → ~2920 tickers) and the rankings table accumulated runs,
# stale statistics tipped the planner from index scans to seq scans and the query
# blew past the dashboard proxy timeout (the "screener shows no data" symptom).
# ANALYZE is cheap (a sampled stats refresh, not a rewrite) and idempotent, so
# running it on every deploy keeps plans healthy as the data keeps growing.
echo "[db-migrator] Running: ANALYZE (refresh planner statistics)" >&2
python - <<'EOF' || echo "[db-migrator] WARNING: ANALYZE failed (non-fatal)" >&2
import os, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=30)
conn.set_isolation_level(0)  # ANALYZE cannot run inside a transaction block
with conn.cursor() as cur:
    cur.execute("ANALYZE")
conn.close()
print("[db-migrator] ANALYZE complete", flush=True)
EOF

# Show final state
echo "[db-migrator] Final alembic state:" >&2
alembic -c /app/alembic.ini current 2>&1 || true
