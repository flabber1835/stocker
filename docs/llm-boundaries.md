# LLM Boundaries

## Allowed LLM Responsibilities

The LLM may:

```text
convert natural-language prompts into strategy YAML/JSON
explain rankings
summarize news
classify thematic exposure
suggest strategy changes
generate reports
explain trade signals
```

## Forbidden LLM Responsibilities

The LLM must not:

```text
submit orders
bypass risk-service
change live config without validation
invent missing data
override safety limits
directly decide position sizing without deterministic checks
directly modify approved strategy registry
```

## Correct Pattern

```text
LLM proposes
Python validates
Backtester tests
Human/system approves
Risk-service gates
Trade-executor executes
```

## Config, Not Code

The LLM should create structured strategy configs, not arbitrary Python code.

Example:

```yaml
portfolio_strategy:
  rebalance: monthly
  ranking:
    quality: 0.35
    momentum: 0.25
    value: 0.15

trading_behavior:
  rules:
    - name: trim_big_winner
      trigger:
        intraday_return_gt: 0.06
      action:
        type: trim
        percent_of_position: 0.25
```

## Provider Abstraction

The system should support API LLMs or local LLMs through `llm-gateway`.

Other services should not care which model is behind the gateway.
