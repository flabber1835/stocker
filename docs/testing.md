# Testing

Use `pytest`.

## Priority Test Targets

```text
strategy-validator
risk-service
factor-engine
ranker
backtester
intraday-monitor
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
risk-service blocks unsafe trades
trade-executor cannot run without risk approval
```

## Service Expectations

Every service should have:

```text
health endpoint
unit tests
clear README
typed Pydantic models where useful
```

## Example Commands

```bash
make test
pytest
docker compose run --rm strategy-validator pytest
```

## Early Testing Philosophy

Test the safety boundary first.

The first important tests should prove:

```text
bad strategy configs are rejected
dangerous risk limits are rejected
no order can be submitted without risk approval
paper trading is the default
```
