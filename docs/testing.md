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
risk-service          ⬜ built, no tests
trade-executor        ⬜ built, no tests
alpaca-sync           ⬜ built, no tests
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
conviction boosts attenuated by flag count
crash isolation: one ticker crash does not abort the vetter loop
risk-service blocks unsafe trades          (when built)
trade-executor cannot run without approval (when built)
```

## Test Gaps to Address

```text
ranker: no unit tests for composite scoring or regime-weight application
portfolio-builder: no test for conviction boost attenuation by hallucination_flag_count
llm-vetter: no test for _format_ticker_message with quantitative context
llm-vetter: no test for fetch_av_news concurrency / semaphore behaviour
llm-vetter: no end-to-end agentic loop test (requires mock Ollama client)

risk-service:
  kill switch path (KILL_SWITCH=true rejects everything)
  paper-only guard (PAPER_ONLY=true rejects live)
  notional limit (notional > MAX_ORDER_NOTIONAL rejected)
  qty validation (qty <= 0 rejected)
  live trading guard (trade_type="live" requires LIVE_TRADING_ENABLED=true)

trade-executor:
  risk_rejected persistence (writes alpaca_orders row but does NOT call Alpaca)
  no-credentials short circuit (empty ALPACA_API_KEY → records failed row, no call)
  double-submit protection

api /trade/approve:
  sizing math for entries: floor(account_value × weight / last_price)
  exit-qty pulled from latest live_positions row
  audit-row insertion on failure paths (risk reject, missing intent, etc.)
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
