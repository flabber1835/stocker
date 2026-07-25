#!/usr/bin/env bash
# up.sh — bring up BOTH stacks (live + backtest) with one command.
#
# The stacks are deliberately SEPARATE compose projects (own bt-postgres, own
# namespace): a live `up -d --build` must never recreate backtest containers
# mid-backfill/backtest, and merging projects would re-prefix the bt data
# volume (the 35M-row corpus would mount as empty). This wrapper gives the
# one-command experience without those risks.
#
# INDEPENDENCE IS THE POINT: a failure in one stack must NOT stop the other
# from coming up (an llm-gateway build error once aborted the script before the
# backtest stack was touched). Each stack is attempted, both results are
# reported, and the script exits non-zero only at the very end.
#
# IN-FLIGHT GUARD (the same one down.sh has): recreating bt-engine while a sweep
# runs does NOT just pause it — bt-engine marks every `running` bt_sweeps row
# 'RESTART_ABORTED: engine restarted mid-sweep' on ITS OWN STARTUP. So a deploy
# during an experiment silently destroys it. That is exactly what happened on
# 2026-07-23/24/25: three consecutive nightly baselines aborted, no candidate was
# ever validated, and the weekly review reported the lane as non-functional for a
# 4th week. up.sh had no guard while down.sh did — a deploy was the one path that
# could kill a job without warning. The LIVE stack still comes up either way.
#
# Usage: scripts/up.sh            (both stacks, no rebuild)
#        scripts/up.sh --build    (both stacks, rebuild changed images)
#        scripts/up.sh --force    (recreate the bt stack even mid-job)
set -uo pipefail          # deliberately NOT -e: see above
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ARGS=()
FORCE=0
for a in "$@"; do
    case "$a" in
        --build)      ARGS+=(--build) ;;
        --force|-f)   FORCE=1 ;;
        *) echo "unknown argument: $a"
           echo "usage: scripts/up.sh [--build] [--force]"; exit 2 ;;
    esac
done

bt_busy=""
if [ "$FORCE" -eq 0 ]; then
    if curl -sf --max-time 5 http://localhost:8030/runs/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        bt_busy="a bt-data fetch (backfill/topup)"
    fi
    if curl -sf --max-time 5 http://localhost:8031/sweeps/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        bt_busy="${bt_busy:+$bt_busy and }a bt-engine sweep/experiment"
    fi
fi

# 17 of the service images are `FROM stocker-base:latest` — a LOCALLY built
# image that compose never builds for you. If it is missing (fresh host, after
# a prune) every one of those builds fails, which reads as a random service
# error. Build it once, up front, so the failure can't happen.
if ! docker image inspect stocker-base:latest >/dev/null 2>&1; then
    echo "── stocker-base:latest missing — building it first ─────────"
    if ! docker build --network host -t stocker-base:latest -f Dockerfile.base .; then
        echo "!! could not build stocker-base — every service build will fail"
        exit 1
    fi
fi

live_rc=0
bt_rc=0
bt_skipped=0

echo "── live stack ──────────────────────────────────────────────"
docker compose up -d "${ARGS[@]}" || live_rc=$?
[ "$live_rc" -ne 0 ] && echo "!! live stack FAILED (rc=$live_rc) — continuing to the backtest stack"

echo
echo "── backtest stack ──────────────────────────────────────────"
if [ -n "$bt_busy" ]; then
    # SKIPPED, not failed: the live stack is deployed and the running job keeps
    # its slot. Recreating bt-engine here would mark the sweep RESTART_ABORTED.
    echo "SKIPPED: $bt_busy is RUNNING."
    echo "  Recreating bt-engine now would abort it (bt-engine marks every"
    echo "  'running' sweep RESTART_ABORTED on its own startup) — three nightly"
    echo "  baselines were lost that way on 2026-07-23/24/25."
    echo "  The live stack above IS deployed. Re-run once the job finishes:"
    echo "      scripts/up.sh${ARGS[*]:+ ${ARGS[*]}}"
    echo "  or override deliberately:"
    echo "      scripts/up.sh${ARGS[*]:+ ${ARGS[*]}} --force"
    bt_skipped=1
else
    docker compose -f docker-compose.backtest.yml up -d "${ARGS[@]}" || bt_rc=$?
    [ "$bt_rc" -ne 0 ] && echo "!! backtest stack FAILED (rc=$bt_rc)"
fi

# Plain `ps` (default table): --format Go templates with \t are not parsed by
# every compose version on the NAS, and a cosmetic status print must never make
# the deploy look failed.
echo
echo "── status: live ──"
docker compose ps || true
echo "── status: backtest ──"
docker compose -f docker-compose.backtest.yml ps || true

echo
if [ "$live_rc" -eq 0 ] && [ "$bt_rc" -eq 0 ]; then
    if [ "$bt_skipped" -eq 1 ]; then
        echo "✓ live stack up · backtest stack SKIPPED (job in flight — see above)"
    else
        echo "✓ both stacks up"
    fi
    exit 0
fi
echo "✗ live=$( [ "$live_rc" -eq 0 ] && echo ok || echo FAILED ) " \
     "backtest=$( [ "$bt_rc" -eq 0 ] && echo ok || echo FAILED )"
echo "  Re-run a single stack to see the full build log, e.g.:"
echo "    docker compose up -d --build llm-gateway"
exit 1
