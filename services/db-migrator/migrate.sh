#!/bin/sh
set -e

MAX_RETRIES=20
DELAY=10

# Every phase is timed. Without this the only way to explain a slow deploy was
# to guess which step was slow — the log had no timestamps at all, and
# `docker compose logs` interleaves runs, so "db-migrator takes ages" was
# unattributable. api/scheduler gate on this container completing, so whatever
# is slow here delays the WHOLE stack.
_t0_total=$(date +%s)
say() { echo "[db-migrator] $*" >&2; }
phase() {           # phase <label> — prints elapsed since the previous phase
    _now=$(date +%s)
    if [ -n "${_t0_phase:-}" ]; then
        say "  ↳ ${_phase_label} took $((_now - _t0_phase))s"
    fi
    _t0_phase=$_now
    _phase_label="$1"
    say "$1"
}

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
            say "DB connection OK"
            return 0
        fi
        i=$((i + 1))
        if [ $i -lt $MAX_RETRIES ]; then
            say "Retry $i/$MAX_RETRIES in ${DELAY}s..."
            sleep $DELAY
        fi
    done
    say "FATAL: cannot connect to DB after $MAX_RETRIES attempts"
    exit 1
}

phase "waiting for the database"
wait_for_db

phase "current alembic state"
alembic -c /app/alembic.ini current 2>&1 || true

phase "alembic upgrade head"
alembic -c /app/alembic.ini upgrade head

# Refresh planner statistics after every deploy. The dashboard screener's
# /rankings/with-overlays query (rank_slope REGR + prior_rank + joins to
# fundamentals/universe_tickers/vetter_decisions) is plan-sensitive: as the
# universe grew (~2050 → ~2920 tickers) and the rankings table accumulated runs,
# stale statistics tipped the planner from index scans to seq scans and the query
# blew past the dashboard proxy timeout (the "screener shows no data" symptom).
#
# SCOPED, not a bare `ANALYZE`. A bare ANALYZE walks EVERY table — including
# daily_prices (millions of rows) and live_positions (a full book snapshot per
# sync run) — none of which the plan-sensitive query touches. On NAS disks that
# dominated the deploy while api and scheduler sat waiting on this container.
# Analyzing only the tables that motivated the fix keeps the benefit at a
# fraction of the cost. ANALYZE_TABLES overrides the list; ANALYZE_SKIP=true
# skips it entirely (autovacuum still keeps stats broadly fresh).
if [ "${ANALYZE_SKIP:-false}" = "true" ]; then
    phase "ANALYZE skipped (ANALYZE_SKIP=true)"
else
    phase "ANALYZE (scoped planner-statistics refresh)"
    python - <<'EOF' || say "WARNING: ANALYZE failed (non-fatal)"
import os, time
import psycopg2

DEFAULT = (
    # the screener's plan-sensitive join set
    "rankings,ranking_runs,fundamentals,universe_tickers,vetter_decisions,"
    # the other per-deploy dashboard reads that join on run ids
    "portfolio_holdings,portfolio_runs,delta_intents,delta_runs"
)
tables = [t.strip() for t in os.getenv("ANALYZE_TABLES", DEFAULT).split(",") if t.strip()]

conn = psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=30)
conn.set_isolation_level(0)  # ANALYZE cannot run inside a transaction block
done, skipped = [], []
with conn.cursor() as cur:
    for t in tables:
        # to_regclass keeps a fresh/partial database from failing the deploy,
        # and refuses to interpolate anything that is not a real relation.
        cur.execute("SELECT to_regclass(%s)", (t,))
        if cur.fetchone()[0] is None:
            skipped.append(t)
            continue
        t0 = time.monotonic()
        cur.execute(f'ANALYZE "{t}"')
        done.append(f"{t} {time.monotonic() - t0:.1f}s")
conn.close()
print(f"[db-migrator] ANALYZE complete: {', '.join(done) or 'nothing'}"
      + (f" | absent: {', '.join(skipped)}" if skipped else ""), flush=True)
EOF
fi

phase "final alembic state"
alembic -c /app/alembic.ini current 2>&1 || true

phase "done"
say "TOTAL $(($(date +%s) - _t0_total))s"
