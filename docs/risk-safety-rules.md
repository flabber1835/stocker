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

## Implemented Safety Controls (Phase 6)

These are actually enforced in code today.

```text
KILL_SWITCH env var      — if "true", risk-service rejects all checks
LIVE_TRADING_ENABLED     — must be "true" for trade_type=="live" to pass; default "false"
PAPER_ONLY               — when "true", any live trade is rejected; default "true"
MAX_ORDER_NOTIONAL       — default $50,000 per order
qty > 0 validation       — enforced in risk-service /check

Human approval required for every paper trade — every order today requires a
  manual button click on the dashboard Trade Proposal tab. The system does not
  auto-submit, even after the delta engine fires.

trade-executor short-circuits when Alpaca credentials are empty
llm-vetter cannot place trades; vetter is informational only
```

## Planned Safety Controls (future)

Not yet implemented. Tracked here so they don't get forgotten.

```text
max daily turnover cap
max daily loss cap
max position size cap (per-ticker weight)
max position count
staleness check (reject if market data > N hours old)
Alpaca availability check (reject if last alpaca-sync failed or stale)
persist risk-service decisions to a risk_decisions audit table
  (check_id is currently returned but not stored server-side)
```

## Trade Intent Flow

Actual flow as of Phase 6 (paper trading):

```text
delta-engine
  → delta_intents
  → dashboard human approval (Trade Proposal tab)
  → api /trade/approve
  → risk-service /check
  → trade-executor /jobs/submit
  → Alpaca
```

`intraday-monitor` will become a second producer of trade intents once built. The
risk-service interface is designed so both producers go through the same gate.

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
