# Testing

Use `pytest`. Run from the `tests/` directory after `pip install -e ../shared`.

## Test Coverage (current)

```text
tests/shared/          27 tests  — StrategyConfig, VetterConfig, FactorEngineConfig,
                                   UniverseConfig, IntradayConfig schema validation
tests/llm_vetter/      29 tests  — hallucination detection, auto-override,
                                   crash isolation, _build_summary, contradiction checks
tests/av_ingestor/      9 tests  — ticker validation, dollar volume, incremental skip
tests/portfolio_builder/ 8 tests — greedy selection, sector caps, covariance
tests/backtester/      28 tests  — simulate.py (7), metrics.py (8), plus edge cases
```

## Priority Test Targets

```text
strategy-validator    ✅ covered via shared/test_strategy_schema.py
llm-vetter            ✅ covered via llm_vetter/test_vetter.py
factor-engine         ✅ covered via regression tests
backtester            ✅ covered via backtester/test_simulate.py + test_metrics.py
risk-service          ✅ covered via risk_service/test_check.py (21 tests)
trade-executor        ✅ covered via trade_executor/test_sizing.py + test_endpoints.py (16 tests)
alpaca-sync           ✅ covered via alpaca_sync/test_parse_helpers.py + test_endpoints.py (16 tests)
intraday-monitor      ⬜ not yet built
ranker                ⬜ unit tests pending
```

## Required Test Types

```text
valid strategy config passes
invalid strategy config fails
unsafe risk limits are rejected
unknown LLM-generated fields are rejected
factor calculations are deterministic
rankings are reproducible
backtest output is reproducible
hallucination flags correctly detect contradictions
crash isolation: one ticker crash does not abort the vetter loop
risk-service blocks unsafe trades          ✅ tested
trade-executor sizing math is deterministic ✅ tested
```

## Test Gaps to Address

```text
ranker: no unit tests for composite scoring or regime-weight application
llm-vetter: no test for _format_ticker_message with quantitative context
llm-vetter: no test for fetch_av_news concurrency / semaphore behaviour
llm-vetter: no end-to-end agentic loop test (requires mock Ollama client)

api /trade/approve:
  integration test for full proxy → trade-executor flow (needs DB fixture)

trade-executor (end-to-end):
  POST /jobs/submit happy path with DB + mocked risk-service + mocked Alpaca
  POST /jobs/submit risk_rejected end-to-end persistence
  double-submit protection at the DB unique-index level

risk-service:
  test that risk_decisions rows are written (needs DB fixture)

alpaca-sync:
  execution_traces + execution_steps written per sync (needs DB fixture)
```

## Service Expectations

Every service should have:

```text
health endpoint
unit tests
typed Pydantic models where useful
```

## Example Commands

```bash
cd tests && pip install -e ../shared
pytest                          # all tests
pytest shared/ -v               # schema tests only
pytest llm_vetter/ -v           # vetter tests only
pytest backtester/ -v           # backtester tests only
pytest scheduler/ -v            # supervisor state machine + restart recovery
```

## Black-box harness (full-system simulation)

`tests/harness/` runs the system against simulated AV / Anthropic / Tavily
APIs (services `av-sim`, `anthropic-sim`, `tavily-sim`) plus `alpaca-sim`
for broker calls. All four simulators are gated behind the `[test]` profile
so plain `docker compose up` does NOT start them.

Activate the harness with the profile plus the overlay file:

```bash
docker compose --profile test \
  -f docker-compose.yml -f tests/harness/docker-compose.yml up -d --build
python tests/harness/run.py            # drive the harness
```

The overlay redirects `av-ingestor`, `llm-gateway`, `llm-vetter`, and
`trade-executor`/`alpaca-sync` traffic to the local simulators and slows
the scheduler tick so the harness drives the pipeline directly.

## DB query-contract tier (real Postgres)

`tests/integration/` runs the real, type-sensitive service SQL against a real,
fully-migrated Postgres — the gap that let two production bugs ship green:

- vetter held-tickers query selected `id` instead of `run_id`
  → `operator does not exist: uuid = integer`
- penalty-box query bound a `str` (`date.today().isoformat()`) to a DATE column
  → `'str' object has no attribute 'toordinal'`

The per-service unit tests mock the DB, so they exercise Python logic but never
the actual SQL. This tier closes that gap.

```bash
python -m pytest tests/integration/        # uses an ephemeral local Postgres
STOCKER_TEST_DSN=postgresql://... python -m pytest tests/integration/  # reuse an existing DB
```

How it works (`tests/integration/conftest.py`):
1. If `STOCKER_TEST_DSN` is set, that database is used.
2. Otherwise a throwaway Postgres cluster is created via `initdb`/`pg_ctl`
   (run as the `postgres` system user when the test runner is root).
3. `alembic upgrade head` applies the real migrations.
4. Tests run the queries through async SQLAlchemy + asyncpg (the production stack).

If neither a DSN nor the Postgres binaries are available, the whole tier skips
cleanly so bare runners stay green. Each recently-fixed bug has both a positive
test (correct query runs) and a negative test (the old buggy query still raises),
so the tier is proven to catch that class of regression.

When you add a query that joins tables or compares typed columns (UUID FKs,
DATE/TIMESTAMP, enums), add a contract test here — a green unit test is not
enough.

## Testing Philosophy

Test the safety boundary first, then correctness of deterministic engines.

Priority order:
1. Config validation (strategy schema) — bad configs must be rejected before reaching any service
2. Risk service safety rules — when built, every hard rule needs a test
3. Deterministic engines (factor-engine, ranker, backtester) — same inputs → same outputs
4. Advisory layers (vetter) — hallucination detection and override logic
5. Integration paths — end-to-end with mocked external services
