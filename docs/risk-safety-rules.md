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
KILL_SWITCH              — if active, risk-service rejects all checks (see hot-flip below)
LIVE_TRADING_ENABLED     — must be "true" for trade_type=="live" to pass; default "false"
PAPER_ONLY               — when "true", any live trade is rejected; default "true"
MAX_ORDER_NOTIONAL       — default $50,000 per order
MAX_ORDER_DAILY_TURNOVER_PCT — default 0.50 (50%); per-day sell-side cap (see below)
qty > 0 validation       — enforced in risk-service /check
notional > 0 validation  — enforced in risk-service /check

Human approval required for every paper trade — every order today requires a
  manual button click on the dashboard Trade Proposal tab. The system does not
  auto-submit, even after the delta engine fires.

trade-executor short-circuits when Alpaca credentials are empty
llm-vetter cannot place trades; vetter is informational only
```

### MAX_DAILY_TURNOVER_PCT — sell-side daily turnover cap

Rejects an `exit` or `sell_trim` once today's cumulative sell notional plus
this order would exceed `account_value × MAX_DAILY_TURNOVER_PCT`. Default is
0.50 (50% of portfolio). Entries and buy_adds are NOT counted — they deploy
idle cash, not portfolio churn. The cap is designed to prevent flipping
half the portfolio in a single day on a regime change (15 exits × $3.3K
= $49.5K ≈ 50% of $100K), while leaving cold-boot capital deployment
unconstrained.

Scoping uses the simulation date when available (trade-executor passes
`sim_date` derived from `delta_runs.run_date` for the intent's run), and
falls back to wall-clock `CURRENT_DATE` otherwise. This makes the cap
behave correctly in both production (each calendar day is its own scope)
and harness simulations (each simulated day is its own scope, even though
all submissions happen on one wall-clock day).

Set `MAX_DAILY_TURNOVER_PCT=1.0` to effectively disable the cap.

### KILL_SWITCH hot-flip (no restart required)

All four safety env vars are re-read on every `/check` call, so changing the Docker
environment variable alone would require restarting the container (because
`os.getenv()` reads the frozen process environment). To hot-flip the kill switch
at runtime without any restart, use the control file:

```bash
# Activate kill switch immediately (blocks all new trades):
docker exec stocker-risk-service-1 touch /tmp/kill_switch

# Deactivate:
docker exec stocker-risk-service-1 rm /tmp/kill_switch
```

The file takes precedence over the `KILL_SWITCH` env var when present. The
`KILL_SWITCH` env var still works as the startup default (read from process
environment at container launch). If the file exists, all `/check` calls are
rejected regardless of the env var value.

## Planned Safety Controls (future)

Not yet implemented. Tracked here so they don't get forgotten.

```text
max daily loss cap
max position size cap (per-ticker weight)
max position count
staleness check on factor data (reject if market data > N hours old)
Alpaca availability check (reject if last alpaca-sync failed or stale)
```

Note: exit-sizing staleness IS enforced (`EXIT_SYNC_MAX_AGE_HOURS`, default 24h)
inside trade-executor — refuses to size an exit from a stale alpaca-sync. The
"staleness check" above refers to a broader rule that would also reject entries
when underlying factor data is too old.

## Audit Trail

Every approval click produces a chain of audit rows so any trade can be traced
back to its origin:

```text
delta_intents.id
  ← alpaca_orders.intent_id          (which proposal triggered this order)

execution_traces.trace_id
  ← alpaca_orders.trace_id           (per-click trace, one trace per approval)
  ← alpaca_sync_runs.trace_id        (per-sync trace, one trace per sync)
execution_steps.trace_id
  ← step-by-step audit of every trace (status, input/output JSON, duration, errors)

risk_decisions.decision_id
  ← alpaca_orders.risk_check_id      (which rule + env snapshot drove the decision)
```

The `risk_decisions` table captures the env snapshot at decision time
(`KILL_SWITCH`, `PAPER_ONLY`, `LIVE_TRADING_ENABLED`, `MAX_ORDER_NOTIONAL`)
so a later config change cannot rewrite the rationale of historical decisions.
`MAX_DAILY_TURNOVER_PCT` is read on every `/check` call but is not yet
persisted in the env snapshot — when the cap rejects, the rule_triggered
column is `daily_turnover_limit` and the reason text records the actual
limit and today's running total.

## Trade Intent Flow

Actual flow as of Phase 6 (paper trading):

```text
delta-engine                                    [proposes]
  → delta_intents row
  → dashboard human review (Trade Proposal tab)
  → human button click
  → api /trade/approve                          [thin proxy: UUID + idempotency]
  → trade-executor /jobs/submit                 [orchestrator]
      → load_intent
      → size_order
      → risk-service /check                     [→ risk_decisions row]
      → record alpaca_orders                    [→ audit row, always]
      → POST Alpaca /v2/orders                  [only if approved + credentials]
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
