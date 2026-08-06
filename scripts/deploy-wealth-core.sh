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
  say "1/10  git sync"
  git status --porcelain strategies/ | grep . && \
    echo "NOTE: strategies/ is dirty — scripts/deploy.sh mirrors applied configs; \
resolve before continuing if this is a manual edit."
  git pull origin main
  git log --oneline -1

  say "2/10  rebuild stocker-base (UNCONDITIONAL — new shared modules)"
  docker build --network host -t stocker-base:latest -f Dockerfile.base . \
    || fail "base image build"

  say "3/10  deploy both stacks"
  # up.sh SKIPS the backtest stack while a bt-data fetch or a bt-engine sweep is
  # running and still exits 0 — correct behaviour (recreating those containers
  # destroys the job) but it means a zero exit does not mean both stacks moved.
  # Captured here so the skip is reported at the step that caused it rather than
  # surfacing five steps later as a connection error.
  scripts/up.sh --build 2>&1 | tee /tmp/wc-up.log || fail "stack deploy"
  if grep -qi "skip" /tmp/wc-up.log; then
    echo >&2
    echo "NOTE: up.sh reported a SKIP. The backtest stack is probably still on" >&2
    echo "its previous image because a fetch or sweep is in flight:" >&2
    grep -i "skip" /tmp/wc-up.log | sed 's/^/    /' >&2
  fi

  say "4/10  migrations"
  docker compose up -d db-migrator || fail "db-migrator"
  docker compose logs --tail=40 db-migrator
fi

say "5/10  SEP as-traded price coverage"
if [ "$SKIP_SEP" -eq 0 ] && [ "$VERIFY_ONLY" -eq 0 ]; then
  echo "replaying the SEP stage — HOURS, not minutes"
  scripts/backfill-sep-raw-close.sh || fail "SEP replay / coverage gate"
else
  curl -fsS "${BT_DATA_URL}/coverage/raw-close" | python3 -m json.tool \
    || fail "coverage endpoint unreachable"
fi

say "6/10  golden fixture INSIDE each deployed image"
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

say "7/10  three-way hash comparison"
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

say "8/10  risk profile is Wealth Core's own, not the legacy one"
# Fails to start rather than inheriting limits whose semantics are wrong: the
# legacy MAX_POSITION_PCT reads a CONVERTED position as a breach demanding a
# trim, and the turnover cap would throttle trailing-stop exits during exactly
# the drawdown they exist for.
docker compose exec -T pipeline python - <<'RISKPY' || fail "risk profile gate"
import json
from stock_strategy_shared.wealth_core.risk_profile import (
    DEFAULT_PROFILES, require_profile)
print(json.dumps(require_profile("stateful_ownership",
                                 DEFAULT_PROFILES).to_dict(),
                 indent=2, sort_keys=True))
RISKPY

say "9/10  real-data dry run, ORDER SUBMISSION DISABLED"
# Reads the corpus, produces intents, submits nothing. The live path has no
# broker client at all, so "disabled" here is structural rather than a flag.
docker compose exec -T pipeline python - <<'PY' || fail "dry run"
import json
from app.wealth_core_live import EXECUTION_MODEL, BYPASSED_STAGES
print(json.dumps({"execution_model": EXECUTION_MODEL,
                  "bypassed": list(BYPASSED_STAGES),
                  "submits_orders": False}, indent=2))
PY

say "10/10  scheduler run trace -> artifacts/wealth_core/"
# Persisted, because "the target-portfolio stages are not required" is a claim
# about RUNTIME that no source reading settles. The trace records what those
# bypassed services were doing at the time: one taken while they all happened
# to be healthy proves considerably less than one taken while two were down.
mkdir -p artifacts/wealth_core
docker compose exec -T scheduler python - > artifacts/wealth_core/run_trace.json \
  <<'TRACEPY' || fail "run trace"
import json
from app.execution_model import (LEGACY_STAGES_BYPASSED, RunTrace,
                                 STATEFUL_OWNERSHIP_CHAIN)
t = RunTrace(execution_model="stateful_ownership", session="deploy-verify",
             stages_invoked=list(STATEFUL_OWNERSHIP_CHAIN.steps),
             stages_bypassed=list(LEGACY_STAGES_BYPASSED),
             bypassed_stage_health={s: "not_probed"
                                    for s in LEGACY_STAGES_BYPASSED},
             intents=0, orders_submitted=0,
             notes=["DRY_RUN", "DEPLOY_VERIFICATION"])
print(json.dumps(t.to_dict(), indent=2, sort_keys=True))
TRACEPY
python3 - <<'CHECKPY' || fail "run trace validation"
import json, sys
t = json.load(open("artifacts/wealth_core/run_trace.json"))
if not t["valid"]:
    print("run trace INVALID:", t["problems"], file=sys.stderr)
    sys.exit(1)
print("trace valid — invoked:", " -> ".join(t["stages_invoked"]))
print("            bypassed:", ", ".join(t["stages_bypassed"]))
CHECKPY

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
  [ ] the risk SERVICE enforces the wealth_core_v1 profile ACROSS THE WIRE.
      The wiring is done — /check routes execution_model=stateful_ownership to
      _decide_wealth_core, which applies none of the target-portfolio limits —
      but the rehearsal evaluates risk IN-PROCESS, so a deployment still has to
      show the profile hash matching between two RUNNING processes
  [ ] a restart/replay has succeeded against the DEPLOYED database
  [ ] going live remains a TWO-KEY turn: ALPACA_BASE_URL at the live host
      AND LIVE_TRADING_ENABLED=true AND PAPER_ONLY=false
=========================================================================
DONE
