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
docker compose up           # core stocker only (excludes test harness + stubs)
make test
```

### Docker compose profiles

Services are grouped behind profiles so `docker compose up` starts only the
operational core. Add `--profile <name>` to include extras:

```text
(default)   core: postgres, redis, db-migrator, api, av-ingestor, pipeline,
            strategy-validator, llm-gateway, llm-vetter, portfolio-builder,
            alpaca-sync, risk-service, trade-executor, backtester, scheduler,
            dashboard
--profile test      adds alpaca-sim, av-sim, anthropic-sim, tavily-sim
                    (mock APIs for tests/harness/)
--profile optional  adds strategy-config-service, intraday-monitor, evaluator
                    (currently stubs)
--profile ollama    adds ollama + ollama-init (local LLM)
--profile monitor   adds playwright-monitor (dashboard screenshot service)
```

Run the black-box test harness with the simulator profile + overlay:

```bash
docker compose --profile test -f docker-compose.yml -f tests/harness/docker-compose.yml up -d
```

When pulling a new compose file, run `docker compose down --remove-orphans`
once to evict containers from old service definitions that the current file
no longer declares.

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
