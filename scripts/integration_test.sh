#!/usr/bin/env bash
# Integration test: runs the full pipeline with MOCK_DATA=true
# Usage: bash scripts/integration_test.sh
# Requires: Docker Compose running on the host

set -euo pipefail

BASE_URL_API="http://localhost:8000"
BASE_URL_AV="http://localhost:8001"
BASE_URL_FE="http://localhost:8002"
BASE_URL_RANKER="http://localhost:8003"

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

echo "=== Stocker integration test (MOCK_DATA=true) ==="
echo ""

# 1. Bring up with mock data
echo "Step 1: Starting services with MOCK_DATA=true..."
MOCK_DATA=true docker compose up -d --build
sleep 5

wait_healthy "$BASE_URL_API" "api"
wait_healthy "$BASE_URL_AV" "av-ingestor"
wait_healthy "$BASE_URL_FE" "factor-engine"
wait_healthy "$BASE_URL_RANKER" "ranker"

# 2. Health checks
echo ""
echo "Step 2: Health checks..."
check "api health" "$(curl -sf $BASE_URL_API/health)" '"status":"ok"'
check "av-ingestor health" "$(curl -sf $BASE_URL_AV/health)" '"status":"ok"'
check "factor-engine health" "$(curl -sf $BASE_URL_FE/health)" '"status":"ok"'
check "ranker health" "$(curl -sf $BASE_URL_RANKER/health)" '"status":"ok"'

# 3. Run pipeline
echo ""
echo "Step 3: Fetch universe..."
result=$(curl -sf -X POST $BASE_URL_AV/jobs/fetch-universe)
check "fetch-universe accepted" "$result" '"status":"started"'
sleep 5

echo "Step 4: Fetch data (mock, fast)..."
result=$(curl -sf -X POST $BASE_URL_AV/jobs/fetch-data)
check "fetch-data accepted" "$result" '"status":"started"'
sleep 15  # mock data is fast

echo "Step 5: Calculate factors..."
result=$(curl -sf -X POST $BASE_URL_FE/jobs/calculate)
check "calculate accepted" "$result" '"status":"started"'
sleep 15

echo "Step 6: Rank..."
result=$(curl -sf -X POST $BASE_URL_RANKER/jobs/rank)
check "rank accepted" "$result" '"status":"started"'
sleep 10

# 4. Verify results
echo ""
echo "Step 7: Verify results..."
regime=$(curl -sf $BASE_URL_FE/regime/current)
check "regime current returns data" "$regime" '"regime":'
check "regime has raw_regime field" "$regime" '"raw_regime":'

rankings=$(curl -sf "$BASE_URL_API/rankings?limit=10")
check "rankings endpoint returns data" "$rankings" '"count":'
check "rankings has at least one ticker" "$rankings" '"ticker":'

# 5. Tear down
echo ""
echo "Step 8: Tearing down..."
docker compose down -v
echo "  Done."

echo ""
echo "=== Results: $pass passed, $fail failed ==="
if [ $fail -gt 0 ]; then exit 1; fi
