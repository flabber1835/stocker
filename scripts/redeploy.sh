#!/usr/bin/env bash
#
# redeploy.sh — atomically sync this checkout to origin/main and bring the WHOLE
# stack onto that exact code, then verify it's live. One command, no partial
# restarts, no guessing.
#
# Why this exists: deploying is bind-mount based (code is mounted into containers),
# so the failure modes are (1) restarting only SOME services → mixed code, (2)
# pulling only SOME commits → half-deployed, (3) the browser caching old JS, and
# (4) restarting mid-chain → looks like a loop. This script removes all four by
# always doing the full thing and printing proof at the end.
#
# Your .env is gitignored, so `git reset --hard` does NOT touch it.
# Postgres/Redis data live in named volumes, so recreate does NOT lose data.
#
# Usage:  ./scripts/redeploy.sh        (or:  make redeploy)

set -euo pipefail
cd "$(dirname "$0")/.."          # repo root, regardless of where it's invoked

bold() { printf '\033[1m%s\033[0m\n' "$1"; }

bold "==> 1/4  Syncing to origin/main (.env preserved — it's gitignored)"
git fetch origin main
git reset --hard origin/main
echo "    HEAD is now: $(git log --oneline -1)"

bold "==> 2/4  Recreating the FULL stack on this code (no partial restarts)"
# --force-recreate re-execs every container so each one re-imports the freshly
# bind-mounted code AND picks up any docker-compose.yml / .env changes.
docker compose up -d --force-recreate

bold "==> 3/4  Waiting for services to report healthy..."
sleep 10
docker compose ps

bold "==> 4/4  Verifying the new code is actually live"
HEAD_SHA="$(git rev-parse --short HEAD)"
ORIGIN_SHA="$(git rev-parse --short origin/main)"
if [ "$HEAD_SHA" = "$ORIGIN_SHA" ]; then
  echo "    [ok] checkout == origin/main ($HEAD_SHA)"
else
  echo "    [!!] checkout ($HEAD_SHA) != origin/main ($ORIGIN_SHA)"
fi

echo -n "    [..] pipeline running latest code: "
docker compose exec -T pipeline sh -c 'grep -c "excess_dd_21d" /app/app/main.py' 2>/dev/null \
  | sed 's/^/matches=/' || echo "could not check (pipeline not up?)"

echo -n "    [..] dashboard serving cache-busted JS: "
docker compose exec -T dashboard python -c \
  "import urllib.request as u; print('yes' if 'dashboard.js?v=' in u.urlopen('http://127.0.0.1:8000/').read().decode() else 'NO')" \
  2>/dev/null || echo "could not check (dashboard not up?)"

echo -n "    [..] api returning rankings: "
docker compose exec -T api python -c \
  "import urllib.request,json; print('count=', json.load(urllib.request.urlopen('http://127.0.0.1:8000/rankings/with-overlays?limit=1')).get('count'))" \
  2>/dev/null || echo "could not check (api not up?)"

bold "==> Done."
echo "Now HARD-REFRESH the browser (or use a Private window) so it drops cached JS."
echo "Do NOT run this while a chain is mid-flight — let the current run finish first,"
echo "or trigger a fresh run from the dashboard afterward."
