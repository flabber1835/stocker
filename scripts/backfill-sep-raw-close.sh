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

# `curl -f` fails identically on 404 and 500, and those are opposite problems:
# one means the image is old, the other means the image is current and the
# request BROKE. Reporting either as "stale image" sends the reader to rebuild a
# container that is already correct. So the status is read explicitly and the
# body is shown — the traceback in it is the actual diagnosis.
COV_BODY="$(mktemp)"
COV_CODE="$(curl -sS -o "$COV_BODY" -w '%{http_code}' --max-time 60 \
             "${BT_DATA_URL}/coverage/raw-close" 2>/dev/null || echo 000)"
case "$COV_CODE" in
  200) : ;;
  404)
    echo "bt-data answers /health but /coverage/raw-close is 404." >&2
    echo "That endpoint ships with Wealth Core, so this container is running an" >&2
    echo "image built before it. Restarting will not help — rebuild:" >&2
    echo >&2
    echo "  docker build --network host -t stocker-base:latest -f Dockerfile.base ." >&2
    echo "  $BT_COMPOSE up -d --build bt-data" >&2
    fail "bt-data image predates the coverage endpoint" ;;
  *)
    echo "/coverage/raw-close returned HTTP ${COV_CODE}. The endpoint EXISTS, so" >&2
    echo "the image is current and the request itself failed. Body:" >&2
    head -c 2000 "$COV_BODY" | sed 's/^/    /' >&2
    echo >&2
    echo "Most likely bt_prices.close_unadjusted does not exist yet. bt-data" >&2
    echo "re-applies init_bt.sql on startup, so check that it did:" >&2
    echo >&2
    echo "  $BT_COMPOSE logs bt-data | grep -i 'init_bt\|ALTER\|close_unadj'" >&2
    echo "  psql \"\$BT_DATABASE_URL\" -c '\\d bt_prices'   # is the column there?" >&2
    fail "coverage endpoint errored (HTTP ${COV_CODE})" ;;
esac
rm -f "$COV_BODY"

say "planner statistics"
# VACUUM (ANALYZE) is not housekeeping here. It sets reltuples, which the
# coverage report uses instead of COUNT(*), AND it sets the VISIBILITY MAP,
# which is what lets an index-only scan skip the heap. Without it every probe
# pays a random heap read per row, and on this box that is the difference
# between a diagnostic answering in seconds and one timing out. Cheap to skip
# if it has already run.
$BT_COMPOSE exec -T bt-postgres psql -U btuser -d backtest \
  -c "VACUUM (ANALYZE) bt_prices;" 2>&1 | tail -2 || \
  echo "VACUUM skipped (non-fatal)" >&2

say "coverage BEFORE"
curl -fsS "${BT_DATA_URL}/coverage/raw-close" | python3 -m json.tool

say "backfilling SEP ${START} .. ${END} (hours, not minutes)"
# QUERY PARAMETERS, not a JSON body. The endpoint declares `start_date: str` as a
# bare parameter, which FastAPI reads from the query string — a JSON body gets a
# 422 with no hint as to why. Every other bt-data job endpoint takes query params
# too, so posting a body here was inconsistent with the service as well as wrong.
curl -fsS -X POST \
  "${BT_DATA_URL}/jobs/backfill-prices?start_date=${START}&end_date=${END}&force=true" \
  | python3 -m json.tool

# THE JOB IS FIRE-AND-FORGET. bt-data returns {"status":"started"} immediately and
# does the work in a background task, so checking coverage now would report ~0%
# and fail the gate on a replay that is running perfectly. Poll until the run row
# reaches a terminal state instead.
say "waiting for the SEP stage (this is the multi-hour part)"
WAITED=0
while :; do
  STATE="$(curl -fsS "${BT_DATA_URL}/runs/latest" 2>/dev/null | python3 -c '
import json, sys
runs = json.load(sys.stdin).get("runs", [])
row = next((r for r in runs if r.get("job_type") == "backfill_prices"), None)
print("missing" if row is None else row.get("status") or "unknown")
' 2>/dev/null || echo unreachable)"

  case "$STATE" in
    success) echo "  SEP stage: success after ${WAITED}m"; break ;;
    failed)
      echo "  SEP stage FAILED after ${WAITED}m" >&2
      curl -fsS "${BT_DATA_URL}/runs/latest" | python3 -c '
import json, sys
for r in json.load(sys.stdin).get("runs", []):
    if r.get("job_type") in ("backfill_prices", "backfill_chunk"):
        print(f"  {r.get(\"status\"):8} {r.get(\"date_min\")}..{r.get(\"date_max\")} "
              f"{r.get(\"rows_written\")} rows  {(r.get(\"error_message\") or \"\")[:160]}")
' >&2 || true
      fail "SEP replay failed — the corpus is PARTIALLY covered, not broken; "\
           "re-running resumes from the missing date range" ;;
    running)
      # Chunk progress is the useful signal: the run row stays 'running' for
      # hours while individual years complete underneath it.
      DONE="$(curl -fsS "${BT_DATA_URL}/runs/latest" 2>/dev/null | python3 -c '
import json, sys
runs = json.load(sys.stdin).get("runs", [])
print(sum(1 for r in runs
          if r.get("job_type") == "backfill_chunk" and r.get("status") == "success"))
' 2>/dev/null || echo "?")"
      printf '  %sm elapsed, run=running, recent completed chunks=%s\n' "$WAITED" "$DONE" ;;
    missing)  printf '  %sm elapsed, no backfill_prices run row yet\n' "$WAITED" ;;
    *)        printf '  %sm elapsed, state=%s\n' "$WAITED" "$STATE" ;;
  esac

  sleep 60
  WAITED=$((WAITED + 1))
  if [ "$WAITED" -gt "${SEP_REPLAY_MAX_MINUTES:-720}" ]; then
    fail "SEP replay still running after ${WAITED}m; not failing the corpus, "\
         "just giving up on WAITING. Check: curl -s ${BT_DATA_URL}/runs/latest"
  fi
done

say "coverage AFTER"
REPORT="$(curl -fsS "${BT_DATA_URL}/coverage/raw-close?hash=1")"
echo "${REPORT}" | python3 -m json.tool

# The gate. A partially covered corpus is the dangerous state: every query
# succeeds, most prices are right, and the marks are silently wrong for whatever
# was missed.
python3 - "$REPORT" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
if not r.get("column_present"):
    print("\nbt_prices.close_unadjusted DOES NOT EXIST.", file=sys.stderr)
    for n in r.get("notes", []):
        print(f"  {n}", file=sys.stderr)
    sys.exit(2)
if not r.get("operational"):
    print("\nRAW-CLOSE COVERAGE IS NOT OPERATIONAL", file=sys.stderr)
    print(f"  coverage        {r['coverage']:.4%}"
          f"{'' if r.get('exact') else '  (SAMPLED)'}", file=sys.stderr)
    print(f"  rows (est)      {r.get('rows_total_estimate', 0):,}", file=sys.stderr)
    print(f"  unusable days   {r['sessions_unusable_count']:,} "
          f"(sample {r['sessions_unusable_sample'][:5]})", file=sys.stderr)
    print(f"  covered range   {r.get('first_covered_date')} .. "
          f"{r.get('last_covered_date')}", file=sys.stderr)
    print("\nWealth Core marks the book in the AS-TRADED domain and will refuse "
          "to run. Re-run this script for the missing DATE range. For exact "
          "counts and the per-ticker gaps (a full scan, minutes):", file=sys.stderr)
    print("  curl -s 'localhost:8030/coverage/raw-close?exact=1'", file=sys.stderr)
    sys.exit(2)
print(f"\nOPERATIONAL — coverage {r['coverage']:.4%}"
      f"{'' if r.get('exact') else ' (SAMPLED)'}, "
      f"{r['first_covered_date']} .. {r['last_covered_date']}")
print(f"normalized input hash: {r.get('normalized_input_hash')}")
PY
