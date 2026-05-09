# Risk and Safety Rules

## Default Safety Posture

The system must default to safety.

Defaults:

```text
paper trading only
human approval required for live orders
no live credentials in repo
no secrets committed
no direct LLM trading
no order without risk approval
no trade if config invalid
no trade if market data stale
no trade if kill switch is active
```

## Non-Negotiable Safety Laws

These should be hard-coded or centrally enforced by `risk-service`.

```text
max position size
max daily turnover
max order size
max daily loss
no trade if data is stale
no trade if config is invalid
no trade if Alpaca data is unavailable
paper/live mode guard
kill switch
human approval requirement for live trading
```

## Trade Intent Flow

```text
intraday-monitor or portfolio-builder
  → trade intent
  → risk-service
  → approved/rejected decision
  → trade-executor
  → Alpaca order
```

## LLM Restrictions

The LLM may suggest risk rules, but it cannot bypass or weaken enforced safety limits at runtime.

## Initial Trading Mode

Use Alpaca paper trading only until:

```text
strategy config is validated
backtest results are acceptable
paper trading behavior is reviewed
risk-service tests pass
trade-executor tests pass
human approval is enabled
```

## Auditability

Every signal, decision, and order should be traceable:

```text
strategy config
input data timestamp
signal trigger
risk decision
order request
order result
fill result
```
