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
# Usage: scripts/up.sh            (both stacks, no rebuild)
#        scripts/up.sh --build    (both stacks, rebuild changed images)
set -uo pipefail          # deliberately NOT -e: see above
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ARGS=()
[ "${1:-}" = "--build" ] && ARGS+=(--build)

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

echo "── live stack ──────────────────────────────────────────────"
docker compose up -d "${ARGS[@]}" || live_rc=$?
[ "$live_rc" -ne 0 ] && echo "!! live stack FAILED (rc=$live_rc) — continuing to the backtest stack"

echo
echo "── backtest stack ──────────────────────────────────────────"
docker compose -f docker-compose.backtest.yml up -d "${ARGS[@]}" || bt_rc=$?
[ "$bt_rc" -ne 0 ] && echo "!! backtest stack FAILED (rc=$bt_rc)"

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
    echo "✓ both stacks up"
    exit 0
fi
echo "✗ live=$( [ "$live_rc" -eq 0 ] && echo ok || echo FAILED ) " \
     "backtest=$( [ "$bt_rc" -eq 0 ] && echo ok || echo FAILED )"
echo "  Re-run a single stack to see the full build log, e.g.:"
echo "    docker compose up -d --build llm-gateway"
exit 1
