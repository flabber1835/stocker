# Median-5 open-sizing 10 bp: zero-quantity block investigation

Status: research diagnosis and harness fix prepared. No follow-up backtest has been run after this fix.

## Prior full-PIT run

- Workflow run: `34299991647`
- Trigger head: `d4645497b280d6a80579b204f4dde8a022f42593`
- Artifact: `10085231668`
- Artifact digest: `sha256:3c1f99f2b839cbe57d28e3638b1115851bab69aae1f00a81f99623465f3d1c0b`
- Canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Measurement window: 2006-07-31 through 2026-07-31, 5,032 sessions
- Wealth Core: Median-5, 20 slots, 5% targets, 10 bp close-time admission cushion, next-open whole-share sizing, one-session dividends
- EX3 / Candidate-A was recorded in parallel from the same underlying Wealth Core path.

The economic replay step completed successfully. The workflow-level failure came later from the result-persistence step and did not invalidate the preserved replay artifact.

## Prior headline result

| Metric | Wealth Core | Wealth Core + EX3 | EX3 incremental contribution |
|---|---:|---:|---:|
| 20y CAGR | 16.749342% | 20.217119% | +3.467776 pp/year |
| Max drawdown | -50.338058% | -24.502859% | +25.835199 pp |
| Sharpe | 0.825236 | 1.075339 | +0.250103 |
| Ending multiple | 22.136883x | 39.752015x | +17.615131x |

## Execution telemetry that triggered the investigation

- close admissions: 429
- completed entries: 424
- next-open blocks: 5
- invalid-open blocks: 0
- zero-quantity blocks: 5
- fractional buys: 0

The five blocks were not five independent economic incidents. They were the same unaffordable AMZN candidate admitted on five consecutive closes while the portfolio had 19 of 20 slots occupied.

## Exact blocked events

| Decision date | Execution date | Ticker | Close price | Open price | Cash at open | 10 bp reserve at close | Cash above reserve at close | Result |
|---|---|---|---:|---:|---:|---:|---:|---|
| 2015-12-04 | 2015-12-07 | AMZN | $672.64 | $674.729927 | $283.521942 | $247.889342 | $35.632600 | 0 shares |
| 2015-12-07 | 2015-12-08 | AMZN | $669.83 | $663.130210 | $283.521942 | $247.694282 | $35.827660 | 0 shares |
| 2015-12-08 | 2015-12-09 | AMZN | $677.33 | $678.010199 | $283.521942 | $250.077472 | $33.444470 | 0 shares |
| 2015-12-09 | 2015-12-10 | AMZN | $664.79 | $665.580000 | $283.521942 | $246.479382 | $37.042560 | 0 shares |
| 2015-12-10 | 2015-12-11 | AMZN | $662.32 | $651.229827 | $283.521942 | $247.536602 | $35.985340 | 0 shares |

During this episode the raw Wealth Core book remained at `held_count = 19`. The full cash balance at each open was only `$283.521942`, while one AMZN share cost more than $650 before modeled transaction cost. Therefore the correct open-time whole-share quantity was necessarily zero.

On 2015-12-11 the selected candidate changed to VRSN. At the 2015-12-14 open, VRSN opened at $88.95 and the system bought 3 whole shares for $267.11685 gross, filling the twentieth slot.

## Root cause

The problem was not overnight gap clipping and not a failure of open-time sizing.

The close-time admission contract checked only whether any positive cash remained above the 10 bp reserve:

`cash - reserve > 0`

That condition admitted AMZN even though the spendable cash above the reserve was far below the cost of one whole share at the known close price. The next-open sizing logic then correctly computed:

`floor(execution_budget / (open_price * (1 + COST))) = 0`

After the zero-share open, the reservation cleared. Median-5 selected AMZN again at the next close, repeating the same economically impossible admission.

## Fix

For whole-share execution, close admission now has an additional necessary affordability gate:

`cash_above_10bp_reserve >= close_price * (1 + COST)`

If this is false:

- the candidate is recorded as `Q0_SKIP`;
- `q0_reason = WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE`;
- no slot is reserved for that candidate;
- the admission loop continues down the Median-5 ranked candidate order.

This is **not close-time quantity binding**. The close still binds only the selected economic intent when the candidate passes admission. Exact share quantity remains determined at the next valid open from actual opening price and actual available cash.

## Remaining edge case

A candidate affordable for one whole share at the close can still become unaffordable after an extreme overnight upward gap or a material reduction in available cash before execution. Therefore the next-open zero-quantity guard remains required.

The purpose of this fix is narrower: do not admit a whole-share trade that is already known to be impossible at the decision close.

## Evidence changes for the next authorized run

The experiment runner now:

- applies the whole-share close-affordability gate after the frozen open-sizing transformation;
- fail-closes unless the gate appears exactly once in generated source;
- preserves `close-decisions.csv` as first-class output evidence;
- records the admission rule in `RESULT.json`;
- keeps whole-share quantity determination at the next valid open.

The workflow is now `workflow_dispatch` only. Repository edits cannot automatically launch the next expensive replay.

## Current state

Fix prepared; **not yet empirically rerun**. No claim is made yet about the number of remaining open blocks or about changed CAGR, drawdown, Sharpe, transactions, holdings, or EX3 contribution. Those require a fresh full-PIT replay when explicitly authorized.
