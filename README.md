# Prompt-to-Portfolio Stock Strategy System

This repository is intended to become a Docker Compose based microservices system for stock selection, portfolio construction, intraday monitoring, risk validation, and paper/live trading.

## Core Idea

```text
Prompt
  → LLM-generated strategy config
  → validated YAML/JSON
  → backtest
  → approval
  → monthly portfolio ranking
  → intraday monitoring
  → risk validation
  → Alpaca order execution
```

## Key Boundary

```text
LLM = config, interpretation, explanation
Python = deterministic engine
Risk service = hard safety gate
Trade executor = only service allowed to place orders
```

## Initial Data Sources

- Alpha Vantage Premium for monthly research data
- Alpaca API for real-time monitoring and paper/live trading

## Initial Build Goal

Start with a sturdy Docker Compose skeleton:

```text
postgres
redis
api
dashboard
strategy-validator
shared Python schemas
sample strategy config
pytest tests
```

No real Alpha Vantage or Alpaca calls should be implemented in the first phase.

## Planned Commands

```bash
docker compose up
make test
```

## Documentation

Read these before coding:

```text
CLAUDE.md
docs/architecture.md
docs/service-boundaries.md
docs/llm-boundaries.md
docs/risk-safety-rules.md
docs/data-sources.md
docs/build-phases.md
```
