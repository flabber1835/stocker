#!/usr/bin/env bash
# Integration test: runs the full pipeline with MOCK_DATA=true
# Usage: bash scripts/integration_test.sh
# Requires: Docker Compose running on the host

set -euo pipefail

BASE_URL_API="http://localhost:8000"
BASE_URL_AV="http://localhost:8001"
BASE_URL_FE="http://localhost:8002"
BASE_URL_RANKER="http://localhost:8003"
BASE_URL_PB="http://localhost:8008"

pass=0
fail=0

check() {
    local desc="$1"
    local result="$2"
    local expect="$3"
    if echo "$result" | grep -q "$expect"; then
        echo "  PASS: $desc"
        pass=$((pass + 1))
    else
        echo "  FAIL: $desc"
        echo "        expected to find: $expect"
        echo "        got: $result"
        fail=$((fail + 1))
    fi
}

wait_healthy() {
    local url="$1"
    local name="$2"
    local max=30
    local i=0
    echo "Waiting for $name..."
    until curl -sf "$url/health" > /dev/null 2>&1; do
        i=$((i + 1))
        if [ $i -ge $max ]; then echo "TIMEOUT waiting for $name"; exit 1; fi
        sleep 2
    done
    echo "  $name is up"
}

# Poll until a condition function returns 0, with a timeout.
# Usage: poll_until <description> <max_seconds> <function_name>
poll_until() {
    local desc="$1"
    local max="$2"
    local fn="$3"
    local elapsed=0
    printf "  Polling: %s (max %ss)..." "$desc" "$max"
    until $fn 2>/dev/null; do
        sleep 2
        elapsed=$((elapsed + 2))
        if [ $elapsed -ge $max ]; then
            echo ""
            echo "  TIMEOUT: $desc after ${max}s"
            return 1
        fi
        printf '.'
    done
    echo " ok (${elapsed}s)"
}

check_universe_populated() {
    local count
    count=$(curl -sf "$BASE_URL_AV/status" | python3 -c 'import sys,json; print(json.load(sys.stdin)["universe_tickers"])')
    [ "${count:-0}" -gt 0 ]
}

check_prices_populated() {
    local count
    count=$(curl -sf "$BASE_URL_AV/status" | python3 -c 'import sys,json; print(json.load(sys.stdin)["price_rows"])')
    [ "${count:-0}" -gt 0 ]
}

check_regime_exists() {
    curl -sf "$BASE_URL_FE/regime/current" | \
        python3 -c 'import sys,json; d=json.load(sys.stdin); exit(0 if d.get("regime") else 1)'
}

check_rankings_exist() {
    curl -sf "$BASE_URL_API/rankings?limit=1" | \
        python3 -c 'import sys,json; d=json.load(sys.stdin); exit(0 if d.get("count",0)>0 else 1)'
}

echo "=== Stocker integration test (MOCK_DATA=true) ==="
echo ""

# 0. Tear down any leftover state from a previous run (volumes included so DB starts fresh)
echo "Step 0: Cleaning up any prior run..."
docker compose down -v --remove-orphans 2>/dev/null || true
echo "  Done."

# 1. Bring up with mock data
echo "Step 1: Starting services with MOCK_DATA=true..."
MOCK_DATA=true docker compose up -d --build
sleep 5

wait_healthy "$BASE_URL_API"    "api"
wait_healthy "$BASE_URL_AV"     "av-ingestor"
wait_healthy "$BASE_URL_FE"     "factor-engine"
wait_healthy "$BASE_URL_RANKER" "ranker"
wait_healthy "$BASE_URL_PB"     "portfolio-builder"

# 2. Health checks
echo ""
echo "Step 2: Health checks..."
check "api health"              "$(curl -sf $BASE_URL_API/health)"    '"status":"ok"'
check "av-ingestor health"      "$(curl -sf $BASE_URL_AV/health)"     '"status":"ok"'
check "factor-engine health"    "$(curl -sf $BASE_URL_FE/health)"     '"status":"ok"'
check "ranker health"           "$(curl -sf $BASE_URL_RANKER/health)"  '"status":"ok"'
check "portfolio-builder health" "$(curl -sf $BASE_URL_PB/health)"    '"status":"ok"'

# 3. Run pipeline — each step polls until the previous job is done before continuing
echo ""
echo "Step 3: Fetch universe..."
result=$(curl -sf -X POST $BASE_URL_AV/jobs/fetch-universe)
check "fetch-universe accepted" "$result" '"status":"started"'
poll_until "universe snapshot populated" 60 check_universe_populated

echo "Step 4: Fetch data (mock, fast)..."
result=$(curl -sf -X POST $BASE_URL_AV/jobs/fetch-data)
check "fetch-data accepted" "$result" '"status":"started"'
poll_until "price rows populated" 120 check_prices_populated

echo "Step 5: Calculate factors..."
result=$(curl -sf -X POST $BASE_URL_FE/jobs/calculate)
check "calculate accepted" "$result" '"status":"started"'
poll_until "regime snapshot written" 60 check_regime_exists

echo "Step 6: Rank..."
result=$(curl -sf -X POST $BASE_URL_RANKER/jobs/rank)
check "rank accepted" "$result" '"status":"started"'
poll_until "rankings written" 30 check_rankings_exist

echo "Step 7: Build portfolio..."
result=$(curl -sf -X POST $BASE_URL_PB/jobs/build)
check "build accepted" "$result" '"status":"started"'
pb_run_id=$(echo "$result" | python3 -c 'import sys,json; print(json.load(sys.stdin)["run_id"])')

check_portfolio_done() {
    local s
    s=$(curl -sf "$BASE_URL_PB/runs/$pb_run_id" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
    [ "$s" = "success" ]
}
poll_until "portfolio run complete" 60 check_portfolio_done

# 4. Verify results
echo ""
echo "Step 8: Verify results..."
regime=$(curl -sf $BASE_URL_FE/regime/current)
check "regime current returns data" "$regime" '"regime":'
check "regime has raw_regime field" "$regime" '"raw_regime":'

rankings=$(curl -sf "$BASE_URL_API/rankings?limit=10")
check "rankings endpoint returns data" "$rankings" '"count":'
check "rankings has at least one ticker" "$rankings" '"ticker":'

portfolio=$(curl -sf "$BASE_URL_API/portfolio")
check "portfolio endpoint returns run" "$portfolio" '"run_id":'
check "portfolio has holdings" "$portfolio" '"holdings":'

# 5. Tear down
echo ""
echo "Step 9: Tearing down..."
docker compose down -v
echo "  Done."

echo ""
echo "=== Results: $pass passed, $fail failed ==="
if [ $fail -gt 0 ]; then exit 1; fi
