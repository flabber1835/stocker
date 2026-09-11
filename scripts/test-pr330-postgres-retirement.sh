#!/usr/bin/env bash
set -euo pipefail

TEST_IMAGE="${1:-sentinel-test:ci}"
POSTGRES_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"
network="pr330-pg-${RANDOM}-$$"
postgres="pr330-postgres-${RANDOM}-$$"
password="pr330-ci-postgres"

# Fast exact-surface regression gate. Keep this network-disabled: every test in
# the list exercises deterministic reconciliation, retirement, split-chain, or
# frozen-source authority behavior and must not depend on live vendor state.
docker run --rm --network none \
  "$TEST_IMAGE" \
  tests/sentinel/test_issue_162_predecessor_closes.py \
  tests/sentinel/test_issue_168_noop_bar_upserts.py \
  tests/sentinel/test_issue_185_sep_reconciliation.py \
  tests/sentinel/test_maintenance_future_cursor_refusal.py \
  tests/sentinel/test_sep_observation_authority.py \
  tests/sentinel/test_sep_frozen_source_authority.py \
  tests/sentinel/test_sep_retirement_mutation_authority.py \
  tests/sentinel/test_sep_retirement_postgres.py \
  tests/sentinel/test_sep_retirement_source_authority.py \
  tests/sentinel/test_recent_sep_reconciliation.py \
  tests/sentinel/test_sep_negative_space_economic_guards.py \
  tests/sentinel/test_sep_negative_space_p1_regressions.py \
  tests/sentinel/test_sep_negative_space_self_heal.py \
  tests/sentinel/test_sep_reconciliation_action_order.py \
  -q -ra

echo "PR330_TARGETED_PASS"

cleanup() {
  docker rm -f "$postgres" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$network" >/dev/null
docker run -d --rm \
  --name "$postgres" \
  --network "$network" \
  -e POSTGRES_PASSWORD="$password" \
  -e POSTGRES_DB=sentinel \
  "$POSTGRES_IMAGE" >/dev/null

ready=0
for _ in $(seq 1 60); do
  if docker exec "$postgres" pg_isready -U postgres -d sentinel >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "PR330_POSTGRES_REFUSED: PostgreSQL did not become ready" >&2
  exit 1
fi

docker run --rm \
  --network "$network" \
  -e SENTINEL_DATABASE_URL="postgresql://postgres:${password}@${postgres}:5432/sentinel" \
  -e SENTINEL_PUBLICATION_RECEIPT_KEY="pr330-test-receipt-key-pr330-test-receipt-key-pr330-test-receipt-key" \
  "$TEST_IMAGE" \
  tests/postgres/test_pr330_retirement_boundaries.py -q -ra

echo "PR330_POSTGRES_PASS"
