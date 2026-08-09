#!/usr/bin/env bash
# retire-stocker.sh — take the Stocker LIVE stack out of service, permanently.
#
#   scripts/retire-stocker.sh            what would happen; changes nothing
#   scripts/retire-stocker.sh --yes      do it
#
# WHAT IT DOES
#   Stops and removes the Stocker LIVE stack's containers. That is all. The
#   repository, the images and every data volume stay exactly where they are.
#
# WHAT IT REFUSES, and why each one cost something to learn:
#
#   --volumes / -v     REFUSED, always, with no override. It would delete the
#                      trading database (every order, ranking, fill and audit
#                      row) and, if pointed at the backtest project, the 35M-row
#                      Sharadar corpus that costs a paid subscription month to
#                      rebuild. Retirement means the platform stops running, not
#                      that its history is destroyed — the whole retirement
#                      doctrine is "retire, do not erase".
#
#   the BACKTEST stack This script will not touch it. bt-postgres holds the
#                      Sharadar corpus and bt-engine runs the Wealth Core
#                      rehearsals, which are the evidence Sentinel is being built
#                      on. Three nightly baselines were already lost to a restart
#                      landing mid-sweep (2026-07-23/24/25). Use scripts/down.sh
#                      if you genuinely need that stack down.
#
#   an IN-FLIGHT job   Refuses while a bt-engine sweep or Wealth Core run is
#                      running, unless --force. The live stack and the backtest
#                      stack are separate, so stopping live cannot kill a
#                      rehearsal — but an operator retiring the platform mid-run
#                      is far more likely to be confused about which stack is
#                      which than to mean it.
#
# AFTER THIS, Sentinel owns the paper account:
#   docker compose -f docker-compose.sentinel.yml run --rm sentinel plan
#   docker compose -f docker-compose.sentinel.yml run --rm sentinel establish-ownership
set -uo pipefail

cd "$(dirname "$0")/.."

APPLY=0
FORCE=0
for a in "$@"; do
    case "$a" in
        --yes|-y)     APPLY=1 ;;
        --force|-f)   FORCE=1 ;;
        -v|--volumes)
            echo "REFUSED: --volumes would DELETE the trading database and, on the"
            echo "         backtest project, the 35M-row Sharadar corpus."
            echo "         Retirement stops the platform; it does not erase it."
            echo "         There is no override here. Run the raw docker command"
            echo "         yourself if you truly mean it."
            exit 2 ;;
        *)
            echo "unknown argument: $a"
            echo "usage: scripts/retire-stocker.sh [--yes] [--force]"
            exit 2 ;;
    esac
done

hr() { printf '\n\033[1m%s\033[0m\n' "$*"; }

hr "Stocker LIVE stack"
docker compose ps 2>/dev/null || echo "  (compose could not read the live project)"

# ── in-flight guard ─────────────────────────────────────────────────────────
# Best-effort and deliberately fail-SAFE toward refusing: an unreadable
# bt-postgres is a reason to stop and look, not to proceed. Live and backtest are
# separate projects so this is a confusion check, not a data-safety one.
busy=""
if bt_pg="$(docker compose -p stocker-bt -f docker-compose.backtest.yml ps -q bt-postgres 2>/dev/null)" \
   && [ -n "$bt_pg" ]; then
    busy="$(docker exec "$bt_pg" psql -U btuser -d backtest -tAc "
        SELECT string_agg(k, ', ') FROM (
            SELECT 'sweep' AS k FROM bt_sweeps WHERE status='running'
            UNION ALL SELECT 'wealth-core run' FROM bt_wealth_core_runs WHERE status='running'
            UNION ALL SELECT 'backtest run' FROM bt_runs WHERE status='running'
        ) t" 2>/dev/null | tr -d '[:space:]')"
fi

if [ -n "$busy" ] && [ "$FORCE" -eq 0 ]; then
    hr "REFUSED — a backtest-stack job is running ($busy)"
    echo "  Stopping the LIVE stack does not kill it: the two are separate compose"
    echo "  projects with separate databases. But retiring the platform while a"
    echo "  rehearsal is in flight is more often a mix-up than an intention."
    echo
    echo "  Wait for it, or pass --force if you know which stack you mean."
    exit 3
fi

hr "Backtest stack — NOT TOUCHED by this script"
docker compose -p stocker-bt -f docker-compose.backtest.yml ps 2>/dev/null \
    || echo "  (not running)"

if [ "$APPLY" -eq 0 ]; then
    hr "DRY RUN — nothing was changed"
    echo "  Would run:  docker compose down --remove-orphans"
    echo "  Would KEEP: every volume, image and the repository"
    echo "  Would LEAVE: the backtest stack running"
    echo
    echo "  Re-run with --yes to apply."
    exit 0
fi

hr "Stopping the Stocker live stack"
# --remove-orphans evicts containers whose service definitions are gone, which is
# the normal state after a compose file changes. NEVER --volumes.
docker compose down --remove-orphans
rc=$?

hr "Result"
docker compose ps 2>/dev/null || true
echo
if [ "$rc" -eq 0 ]; then
    echo "  Stocker live stack: STOPPED and REMOVED"
else
    echo "  compose down exited $rc — check the output above"
fi
echo "  Data volumes:       UNTOUCHED"
echo "  Backtest stack:     UNTOUCHED"
echo
echo "  Next:"
echo "    docker compose -f docker-compose.sentinel.yml run --rm sentinel plan"
echo "    docker compose -f docker-compose.sentinel.yml run --rm sentinel establish-ownership"
exit "$rc"
