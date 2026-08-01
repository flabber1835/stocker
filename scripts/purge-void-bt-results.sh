#!/usr/bin/env bash
# Purge void wind-tunnel RESULTS so the evaluator cannot reason over them.
#
# WHY. Every backtest result produced before 2026-07-25 is void for two
# independent, proven reasons:
#
#   1. the simulator's stale-price bleed (a re-entry left last_seen stale, so the
#      delist sweep booked live positions out — the run that drifted to -96%), and
#   2. the factor-coverage gap: earnings_surprise (weight 0.12 in the active
#      config) was null on every row, so composite_scores renormalized over 0.88
#      and every run scored a config nobody asked for.
#
# Neither is a numbers-are-a-bit-off problem; the results describe a different
# simulator running a different strategy. They are DERIVED artifacts — deleting
# them loses nothing that cannot be recomputed, and leaving them in place gives
# the evaluator (which has read-only SQL access to these tables via bt_sql_query,
# plus the artifacts/bt/*.json bridge) decision-grade-looking evidence that is
# simply wrong.
#
# WHAT IS NOT TOUCHED. The source corpus — bt_prices (~35M rows), bt_fundamentals,
# bt_earnings, bt_universe, bt_data_runs — is expensive to refetch and was never
# implicated. Neither is anything in the live trading database.
#
# Usage:
#   scripts/purge-void-bt-results.sh              # dry run: counts only
#   scripts/purge-void-bt-results.sh --yes        # actually delete
#   scripts/purge-void-bt-results.sh --yes --force  # skip the in-flight guard
set -euo pipefail

cd "$(dirname "$0")/.."

CONFIRM=0
FORCE=0
for a in "$@"; do
    case "$a" in
        --yes|-y)   CONFIRM=1 ;;
        --force|-f) FORCE=1 ;;
        *) echo "unknown argument: $a"
           echo "usage: scripts/purge-void-bt-results.sh [--yes] [--force]"
           exit 2 ;;
    esac
done

# Results tables ONLY. Ordered children-before-parents so the deletes are valid
# regardless of whether FKs are declared.
# bt_sweep_equity / bt_sweep_trades: per-session curves and fills for sweep legs. Purged with the rest —
# leaving it behind would keep a readable island of VOID equity paths after the
# summaries that explain them are gone.
RESULT_TABLES="bt_sweep_results bt_sweep_aggregates bt_sweeps bt_trades bt_positions bt_equity bt_runs bt_sweep_equity bt_sweep_trades bt_sweep_positions"
# Named explicitly so a future reader can see what is deliberately preserved.
CORPUS_TABLES="bt_prices bt_fundamentals bt_earnings bt_universe bt_data_runs"

PG="docker compose -p stocker-bt -f docker-compose.backtest.yml exec -T bt-postgres"
PSQL="$PG psql -U btuser -d backtest -tAq"

# ── in-flight guard ─────────────────────────────────────────────────────────
# Same rule as up.sh/down.sh: deleting bt_sweeps rows under a running sweep
# destroys the job's own audit row mid-write.
if [ "$FORCE" -eq 0 ]; then
    busy=""
    if curl -sf --max-time 5 http://localhost:8030/runs/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        busy="a bt-data fetch"
    fi
    if curl -sf --max-time 5 http://localhost:8031/sweeps/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        busy="${busy:+$busy and }a bt-engine sweep"
    fi
    if [ -n "$busy" ]; then
        echo "BLOCKED: $busy is RUNNING — purging now would delete its audit row"
        echo "  mid-write. Wait for it, or override with --force."
        exit 3
    fi
fi

echo "── current row counts (backtest DB) ─────────────────────────────────────"
for t in $RESULT_TABLES; do
    n=$($PSQL -c "SELECT COUNT(*) FROM $t" 2>/dev/null || echo "n/a")
    printf '  %-22s %s\n' "$t" "$n"
done
echo "── PRESERVED (source corpus, never implicated) ──────────────────────────"
for t in $CORPUS_TABLES; do
    n=$($PSQL -c "SELECT COUNT(*) FROM $t" 2>/dev/null || echo "n/a")
    printf '  %-22s %s\n' "$t" "$n"
done

if [ "$CONFIRM" -eq 0 ]; then
    echo
    echo "DRY RUN — nothing deleted. Re-run with --yes to purge the results tables."
    exit 0
fi

echo
echo "── purging results tables ───────────────────────────────────────────────"
# One transaction: a partial purge would leave the leaderboard pointing at
# sweep rows whose results are gone, which reads as "a sweep that found nothing"
# — a worse lie than the one being removed.
sql="BEGIN;"
for t in $RESULT_TABLES; do
    sql="$sql DELETE FROM $t;"
done
sql="$sql COMMIT;"
$PSQL -c "$sql"
echo "  deleted."

echo "── clearing the artifact bridge ─────────────────────────────────────────"
# The evaluator reads these files directly (packet sections backtest_lab /
# experiment_lane), so purging only the DB would leave the same void numbers
# reaching the prompt by the other route.
for f in artifacts/bt/latest_sweep.json artifacts/bt/promotion.json; do
    if [ -f "$f" ]; then
        rm -f "$f"
        echo "  removed $f"
    fi
done
# experiments.json is the lane's own scheduling state (weekly counters, queued
# proposals). Its RESULTS are void but its queue is not, so the file is left in
# place deliberately — bt-scheduler rewrites the result blocks on the next run.
echo "  kept artifacts/bt/experiments.json (lane scheduling state, not results)"

echo
echo "Done."
echo
# DELIBERATELY no assertions about corpus or gate state here. This epilogue used
# to say "re-backfill SF1" and "sweeps will be refused with 422 until SUE parity
# lands" — both true when written, both false within a day, and a script that
# confidently restates a stale world is worse than one that says nothing. Point
# at the checker instead; it reads the live system.
echo "  What is actually deployed, whether the gates enforce, and whether the"
echo "  active config is scorable:"
echo "      scripts/deploy-all.sh --verify"
echo
echo "  Corpus completeness (all three should be non-zero):"
echo "      docker compose -p stocker-bt -f docker-compose.backtest.yml exec -T bt-postgres \\"
echo "        psql -U btuser -d backtest -tAqc \"SELECT count(*) FROM bt_earnings\""
echo
echo "  The experiment lane fires its own baseline on the daily schedule — there"
echo "  is no manual trigger, and a hand-fired sweep would NOT be recorded as the"
echo "  promotion yardstick."
