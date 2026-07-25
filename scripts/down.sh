#!/usr/bin/env bash
# down.sh — stop the stacks safely. The counterpart to up.sh.
#
# TWO HARD SAFETY PROPERTIES, both learned the expensive way:
#
#  1. `--volumes` / `-v` IS REFUSED, always. It would delete the Postgres data
#     volume (every order, ranking and audit row) and bt-postgres (the 35M-row
#     Sharadar corpus that costs a paid subscription month to rebuild). There is
#     no flag to override this here — if you genuinely want that, run the raw
#     docker command yourself and mean it.
#
#  2. TAKING THE BACKTEST STACK DOWN MID-JOB IS BLOCKED unless you pass --force.
#     Recreating bt-data/bt-engine during a backfill or an experiment kills the
#     job — that repeatedly cost hours of reloading. The check is best-effort
#     (if the services are unreachable it cannot be in-flight anyway).
#
# Like up.sh, one stack failing NEVER stops the other from being brought down.
#
# Usage:
#   scripts/down.sh                     both stacks
#   scripts/down.sh live                live stack only (backtest keeps running)
#   scripts/down.sh backtest            backtest stack only
#   scripts/down.sh [...] --force       proceed even if a bt job is in flight
#   scripts/down.sh [...] --remove-orphans
#                                       evict containers whose service was
#                                       removed/renamed (run once after pulling
#                                       a new compose file)
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

TARGET="both"
FORCE=0
EXTRA=()

for a in "$@"; do
    case "$a" in
        live|backtest|both) TARGET="$a" ;;
        --force|-f)         FORCE=1 ;;
        --remove-orphans)   EXTRA+=(--remove-orphans) ;;
        -v|--volumes)
            echo "REFUSED: --volumes would DELETE the trading database and the"
            echo "         35M-row Sharadar corpus. down.sh will never do that."
            echo "         Stopping containers does NOT touch your data."
            exit 2 ;;
        *)
            echo "unknown argument: $a"
            echo "usage: scripts/down.sh [live|backtest|both] [--force] [--remove-orphans]"
            exit 2 ;;
    esac
done

# ── in-flight guard (backtest stack only) ────────────────────────────────────
if [ "$TARGET" != "live" ] && [ "$FORCE" -eq 0 ]; then
    busy=""
    if curl -sf --max-time 5 http://localhost:8030/runs/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        busy="a bt-data fetch (backfill/topup)"
    fi
    if curl -sf --max-time 5 http://localhost:8031/sweeps/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        busy="${busy:+$busy and }a bt-engine sweep/experiment"
    fi
    if [ -n "$busy" ]; then
        echo "BLOCKED: $busy is RUNNING."
        echo "  Taking the backtest stack down now kills it. Price data resumes"
        echo "  from the last completed year-chunk, but an experiment restarts."
        echo "  Wait for it, take only the live stack down:"
        echo "      scripts/down.sh live"
        echo "  or override deliberately:"
        echo "      scripts/down.sh ${TARGET} --force"
        exit 3
    fi
fi

live_rc=0
bt_rc=0

if [ "$TARGET" = "both" ] || [ "$TARGET" = "live" ]; then
    echo "── stopping live stack ─────────────────────────────────────"
    docker compose down "${EXTRA[@]+"${EXTRA[@]}"}" || live_rc=$?
    [ "$live_rc" -ne 0 ] && echo "!! live stack down FAILED (rc=$live_rc) — continuing"
fi

if [ "$TARGET" = "both" ] || [ "$TARGET" = "backtest" ]; then
    echo "── stopping backtest stack ─────────────────────────────────"
    docker compose -f docker-compose.backtest.yml down "${EXTRA[@]+"${EXTRA[@]}"}" || bt_rc=$?
    [ "$bt_rc" -ne 0 ] && echo "!! backtest stack down FAILED (rc=$bt_rc)"
fi

echo
echo "── remaining containers ──"
docker compose ps || true
docker compose -f docker-compose.backtest.yml ps || true
echo
echo "Data volumes are untouched — 'scripts/up.sh' brings everything back."

[ "$live_rc" -eq 0 ] && [ "$bt_rc" -eq 0 ] && exit 0
exit 1
