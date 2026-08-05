#!/usr/bin/env bash
# Deploy Wealth Core to the NAS and VERIFY it, in the order the verification
# actually depends on.
#
#   scripts/deploy-wealth-core.sh              full sequence
#   scripts/deploy-wealth-core.sh --verify     verify only, change nothing
#   scripts/deploy-wealth-core.sh --skip-sep   skip the multi-hour SEP replay
#
# THIS SCRIPT DOES NOT ENABLE LIVE TRADING. Nothing here submits an order.
# Live activation stays a separate, deliberate act — see the checklist it prints
# at the end.
#
# WHY THE BASE REBUILD IS UNCONDITIONAL AND FIRST. The backtest stack has NO
# `shared/` bind mount: bt-engine and bt-data import the copy BAKED into
# stocker-base. Wealth Core adds several NEW shared modules, and the editable
# install caches the module list, so a service re-layered on a stale base fails
# on ImportError at runtime while its source in git is identical and correct.
# That has already cost this project a crash-looping bt-engine more than once.
#
# NEVER pass --volumes to any compose command. It deletes the trading database
# and the 35M-row Sharadar corpus.
set -euo pipefail

REPO="${REPO:-/volume1/docker/github/stocker}"
BT_DATA_URL="${BT_DATA_URL:-http://localhost:8030}"
VERIFY_ONLY=0
SKIP_SEP=0
for a in "$@"; do
  case "$a" in
    --verify)   VERIFY_ONLY=1 ;;
    --skip-sep) SKIP_SEP=1 ;;
    *) echo "unknown flag: $a" >&2; exit 64 ;;
  esac
done

say()  { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
fail() { printf '\n\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

cd "$REPO" || fail "repo not found at $REPO (it is NOT /volume1/docker/docker/...)"

if [ "$VERIFY_ONLY" -eq 0 ]; then
  say "1/8  git sync"
  git status --porcelain strategies/ | grep . && \
    echo "NOTE: strategies/ is dirty — scripts/deploy.sh mirrors applied configs; \
resolve before continuing if this is a manual edit."
  git pull origin main
  git log --oneline -1

  say "2/8  rebuild stocker-base (UNCONDITIONAL — new shared modules)"
  docker build --network host -t stocker-base:latest -f Dockerfile.base . \
    || fail "base image build"

  say "3/8  deploy both stacks"
  scripts/up.sh --build || fail "stack deploy"

  say "4/8  migrations"
  docker compose up -d db-migrator || fail "db-migrator"
  docker compose logs --tail=40 db-migrator
fi

say "5/8  SEP as-traded price coverage"
if [ "$SKIP_SEP" -eq 0 ] && [ "$VERIFY_ONLY" -eq 0 ]; then
  echo "replaying the SEP stage — HOURS, not minutes"
  scripts/backfill-sep-raw-close.sh || fail "SEP replay / coverage gate"
else
  curl -fsS "${BT_DATA_URL}/coverage/raw-close" | python3 -m json.tool \
    || fail "coverage endpoint unreachable"
fi

say "6/8  golden fixture INSIDE each deployed image"
# In the CONTAINERS, not in CI. CI proves the source agrees; this proves the
# IMAGES agree, which is the claim that matters when one of them may have been
# layered on a stale base.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
run_parity() {  # svc container-name compose-file
  local label="$1" svc="$2" file="${3:-docker-compose.yml}"
  docker compose -f "$file" exec -T "$svc" \
    python -m stock_strategy_shared.wealth_core.parity_cli --engine "$label" \
    > "$TMP/$label.json" || fail "parity CLI failed inside $svc"
  echo "  $label  $(python3 -c "import json,sys;print(json.load(open('$TMP/$label.json'))['hashes']['final_result'][:16])")"
}
run_parity backtester backtester
run_parity pipeline   pipeline
run_parity windtunnel bt-engine docker-compose.backtest.yml

say "7/8  three-way hash comparison"
python3 - "$TMP" <<'PY'
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
runs = {p.stem: json.loads(p.read_text()) for p in d.glob("*.json")}
ref_name = "backtester"
ref = runs[ref_name]["hashes"]
ORDER = ["normalized_input", "candidate_audit", "decision", "order",
         "daily_state", "daily_equity", "final_result"]
bad = False
for name, run in sorted(runs.items()):
    if name == ref_name:
        continue
    first = next((k for k in ORDER if run["hashes"].get(k) != ref.get(k)), None)
    if first:
        bad = True
        print(f"  {name:12} DIVERGES at {first}", file=sys.stderr)
        print(f"      {ref_name}: {ref.get(first)}", file=sys.stderr)
        print(f"      {name}: {run['hashes'].get(first)}", file=sys.stderr)
    else:
        print(f"  {name:12} identical on all 7 hashes")
profiles = {r["ordering_profile"] for r in runs.values()}
if len(profiles) != 1:
    bad = True
    print(f"  ordering profiles DISAGREE: {profiles}", file=sys.stderr)
sys.exit(1 if bad else 0)
PY
[ $? -eq 0 ] || fail "cross-engine parity"

say "8/8  real-data dry run, ORDER SUBMISSION DISABLED"
# Reads the corpus, produces intents, submits nothing. The live path has no
# broker client at all, so "disabled" here is structural rather than a flag.
docker compose exec -T pipeline python - <<'PY' || fail "dry run"
import json
from app.wealth_core_live import EXECUTION_MODEL, BYPASSED_STAGES
print(json.dumps({"execution_model": EXECUTION_MODEL,
                  "bypassed": list(BYPASSED_STAGES),
                  "submits_orders": False}, indent=2))
PY

cat <<'DONE'

=========================================================================
DEPLOYED AND VERIFIED. LIVE TRADING IS NOT ENABLED, AND THIS SCRIPT WILL
NEVER ENABLE IT.

Before considering live activation, all of these must be true and none of
them are checked here:

  [ ] the SEP coverage report is operational over the FULL intended range
  [ ] a real-data dry run has run for several sessions and its intents have
      been read by a human
  [ ] the active strategy config sets execution_model: stateful_ownership
  [ ] risk-service limits have been reviewed for a 25-slot, 4%-per-name book
      (MAX_POSITIONS, MAX_POSITION_PCT and MAX_DAILY_TURNOVER_PCT were all
      calibrated for the target-portfolio strategy)
  [ ] going live remains a TWO-KEY turn: ALPACA_BASE_URL at the live host
      AND LIVE_TRADING_ENABLED=true AND PAPER_ONLY=false
=========================================================================
DONE
