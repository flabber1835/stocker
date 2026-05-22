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
```

## Testing Philosophy

Test the safety boundary first, then correctness of deterministic engines.

Priority order:
1. Config validation (strategy schema) — bad configs must be rejected before reaching any service
2. Risk service safety rules — when built, every hard rule needs a test
3. Deterministic engines (factor-engine, ranker, backtester) — same inputs → same outputs
4. Advisory layers (vetter) — hallucination detection and override logic
5. Integration paths — end-to-end with mocked external services
