#!/usr/bin/env bash
# Re-backfill the Sharadar SEP stage so bt_prices.close_unadjusted is populated.
#
# WHY THIS EXISTS AS A SCRIPT. The SEP stage always fetched `closeunadj`; the
# mapper discarded it. So the column is not a new data requirement, it is a
# REPLAY of data already paid for — but it is a multi-hour, ~35M-row job, and
# running it by hand is where a half-finished corpus comes from.
#
# The price corpus is REWRITTEN IN PLACE by UPSERT. Nothing is dropped and no
# volume is touched, so an interrupted run leaves a partially covered corpus
# rather than a broken one — and the coverage report below is how you find out
# which. NEVER pass --volumes to any compose command here: that deletes the
# corpus this script exists to repair.
set -euo pipefail

BT_DATA_URL="${BT_DATA_URL:-http://localhost:8030}"
START="${1:-2003-01-01}"
END="${2:-$(date +%F)}"

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

say "pre-flight: bt-data reachable, and running THIS build?"
# Three different failures used to print the same message here ("not
# reachable"), which sent the reader to restart a stack that was already up.
# They need different fixes, so they are diagnosed separately:
#
#   container not running   scripts/up.sh SKIPS the backtest stack while a
#                           bt-data fetch or a bt-engine sweep is in flight, and
#                           that is deliberate — recreating those containers
#                           destroys the job. The deploy is not broken; the
#                           stack was intentionally left alone.
#   /health fails           the service is genuinely down or still starting.
#   /health ok, coverage    the container is running a STALE IMAGE that predates
#     endpoint 404          the coverage endpoint. Rebuilding is the fix, and
#                           restarting would achieve nothing.
BT_COMPOSE="docker compose -f docker-compose.backtest.yml"

if ! $BT_COMPOSE ps --services --filter status=running 2>/dev/null | grep -qx bt-data; then
  echo "bt-data container is NOT running." >&2
  $BT_COMPOSE ps 2>&1 | sed 's/^/    /' >&2
  echo >&2
  echo "Most likely: scripts/up.sh SKIPPED the backtest stack because a" >&2
  echo "bt-data fetch or a bt-engine sweep is in flight — that guard exists" >&2
  echo "because recreating those containers destroys the running job." >&2
  echo >&2
  echo "  check:  $BT_COMPOSE logs --tail=50 bt-data" >&2
  echo "  check:  curl -s localhost:8031/runs/latest   # bt-engine, is a sweep live?" >&2
  echo "  then :  scripts/up.sh            # once nothing is in flight" >&2
  echo "  or   :  scripts/up.sh --force    # DESTROYS a running sweep" >&2
  fail "backtest stack not running"
fi

if ! curl -fsS --max-time 10 "${BT_DATA_URL}/health" >/dev/null 2>&1; then
  echo "bt-data container is running but /health does not answer at ${BT_DATA_URL}." >&2
  $BT_COMPOSE logs --tail=50 bt-data 2>&1 | sed 's/^/    /' >&2
  fail "bt-data unhealthy"
fi

if ! curl -fsS --max-time 30 "${BT_DATA_URL}/coverage/raw-close" >/dev/null 2>&1; then
  echo "bt-data answers /health but NOT /coverage/raw-close." >&2
  echo "That endpoint ships with Wealth Core, so this container is running an" >&2
  echo "image built before it. Restarting will not help — rebuild:" >&2
  echo >&2
  echo "  docker build --network host -t stocker-base:latest -f Dockerfile.base ." >&2
  echo "  $BT_COMPOSE up -d --build bt-data" >&2
  fail "bt-data image predates the coverage endpoint"
fi

say "coverage BEFORE"
curl -fsS "${BT_DATA_URL}/coverage/raw-close" | python3 -m json.tool

say "backfilling SEP ${START} .. ${END} (hours, not minutes)"
curl -fsS -X POST "${BT_DATA_URL}/jobs/backfill-prices" \
  -H 'content-type: application/json' \
  -d "{\"start_date\":\"${START}\",\"end_date\":\"${END}\"}" \
  | python3 -m json.tool

say "coverage AFTER"
REPORT="$(curl -fsS "${BT_DATA_URL}/coverage/raw-close?hash=1")"
echo "${REPORT}" | python3 -m json.tool

# The gate. A partially covered corpus is the dangerous state: every query
# succeeds, most prices are right, and the marks are silently wrong for whatever
# was missed.
python3 - "$REPORT" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
if not r.get("operational"):
    print("\nRAW-CLOSE COVERAGE IS NOT OPERATIONAL", file=sys.stderr)
    print(f"  coverage        {r['coverage']:.4%}", file=sys.stderr)
    print(f"  null rows       {r['rows_null']:,}", file=sys.stderr)
    print(f"  unusable days   {r['sessions_unusable_count']:,} "
          f"(sample {r['sessions_unusable_sample'][:5]})", file=sys.stderr)
    print(f"  uncovered names {r['tickers_uncovered_sample'][:10]}", file=sys.stderr)
    print("\nWealth Core marks the book in the AS-TRADED domain and will refuse "
          "to run. Re-run this script for the missing DATE range; a ticker with "
          "no closeunadj at all will not be fixed by re-running.", file=sys.stderr)
    sys.exit(2)
print(f"\nOPERATIONAL — coverage {r['coverage']:.4%}, "
      f"{r['first_covered_date']} .. {r['last_covered_date']}")
print(f"normalized input hash: {r.get('normalized_input_hash')}")
PY
