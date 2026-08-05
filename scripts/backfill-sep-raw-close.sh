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

say "pre-flight: is the column even there?"
# init_bt.sql is re-applied idempotently on bt-data startup, so the ALTER has
# normally already run. If it has not, the backfill would succeed and write
# nothing, which is the one outcome worth failing fast on.
if ! curl -fsS "${BT_DATA_URL}/coverage/raw-close" >/dev/null 2>&1; then
  echo "bt-data is not reachable at ${BT_DATA_URL}." >&2
  echo "Start the backtest stack first: scripts/up.sh" >&2
  exit 1
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
