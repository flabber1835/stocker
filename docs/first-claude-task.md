# Current State and Next Priorities

This file tracks where the project stands and what to build next.
It replaces the original first-task prompt (phases 1–4 are complete).

## What Is Built

See `docs/build-phases.md` for full details.

Phases 1–4.5 are complete:
- Docker Compose stack (postgres, redis, api, dashboard)
- Strategy schema and validator
- Alpha Vantage ingestor (universe + daily data)
- Factor engine, ranker, portfolio-builder
- LLM vetter (Tavily + Ollama/OpenAI, advisory only)
- Dashboard with universe / rank / vetter / portfolio / live tabs
- DB schema for alpaca_sync_runs and live_positions

## What to Build Next

### Phase 5: Backtester

The most useful next step before touching live trading. The ranker has historical
ranking runs in Postgres. A backtester can replay those against forward returns
to measure whether the factor weights and regime logic actually work.

Starting point: forward return attribution against existing `ranking_runs` rows.

### Phase 6 (remainder): Alpaca Paper Trading Services

- `alpaca-sync` service: reads account, positions, orders, fills from Alpaca API and writes to the existing `alpaca_sync_runs` / `live_positions` tables
- `risk-service`: hard safety gate, deterministic, heavily tested
- `trade-executor`: paper trading only, requires prior risk approval
- `intraday-monitor`: signal creation only, no direct trading

### Phase 7: Scheduler

Automate the daily/monthly pipeline with a scheduler service.
