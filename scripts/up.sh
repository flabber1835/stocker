#!/usr/bin/env bash
# up.sh — bring up BOTH stacks (live + backtest) with one command.
#
# The stacks are deliberately SEPARATE compose projects (own bt-postgres, own
# namespace): a live `up -d --build` must never recreate backtest containers
# mid-backfill/backtest, and merging projects would re-prefix the bt data
# volume (the 35M-row corpus would mount as empty). This wrapper gives the
# one-command experience without those risks.
#
# Usage: scripts/up.sh            (both stacks, no rebuild)
#        scripts/up.sh --build    (both stacks, rebuild changed images)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ARGS=()
[ "${1:-}" = "--build" ] && ARGS+=(--build)

echo "── live stack ──"
docker compose up -d "${ARGS[@]}"
echo "── backtest stack ──"
docker compose -f docker-compose.backtest.yml up -d "${ARGS[@]}"
# Plain `ps` (default table): --format Go templates with \t are not parsed by
# every compose version on the NAS, and a cosmetic status print must never make
# the deploy look failed.
echo "── status: live ──"
docker compose ps || true
echo "── status: backtest ──"
docker compose -f docker-compose.backtest.yml ps || true
