# Wealth Core V2 — S&P 500 PIT next-open sizing with 10 bp

## Objective

Run a research-only 20-year Wealth Core V2 replay on historical S&P 500 membership using the execution contract called **next-open sizing**: close-bound economic intent, next-valid-open whole-share quantity determination.

## Fixed terms

- Initial capital: $100,000.
- Warmup start: 2006-01-03.
- Measurement: 2006-07-31 through 2026-07-31 (5,032 sessions expected).
- Wealth Core: formal V2 economics based on the reviewed formal A/B authority.
- Entry target: 4% of close NAV.
- Slots: 25.
- Whole shares only.
- Transaction costs, exits, review age, cooldown, liquidity/capacity, terminal handling, PIT security type logic, and dividend timing remain frozen.
- Dividend lag remains exactly one session.
- No Sentinel/EX3 performance is used to select or tune the result.

## Universe

Use the repository's pinned dated S&P 500 membership reconstruction and approved causal Sharadar identity mappings, intersected with the canonical full-PIT market/security tape on each session.

The S&P membership reconstruction is explicitly labeled **best-effort PIT** by the repository and is not claimed as formally certified. Ambiguous or unresolved membership/identity sessions remain excluded fail-closed. The experiment must report this limitation.

Pinned membership dataset SHA-256:
`1981828b71073be4d0fcf4addb37a56c844a29219090eb0c8fbc535d393bdb2d`

Canonical PIT dataset SHA-256:
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`

## Wealth Core V2 authority

Formal A/B trigger head: `26b324f4da0f80cf790048103a0d92c1c0df3920`.
Formal run: `34189070385`.
Artifact: `10042774099`.
Experiment base head: `880209078f2b4817e837431984dc0ba0bf0b9d79`.

## Next-open sizing

### Close

Wealth Core selects the ticker and binds the intended dollar target only.

A 10 bp close-admission cushion is protected:

`buffer = 0.001 * close_nav`

The V2 full-target reservation is admitted only when the intended 4% dollar target is fully fundable from uncommitted cash after the 10 bp cushion.

No share quantity is calculated or bound at the close.

### Next valid open

Using the actual raw opening price:

`execution_budget = min(reserved_dollar_target, actual_cash_before_buy)`

`shares = floor(execution_budget / (open_price * (1 + cost)))`

The capacity rule is evaluated against this actual open-time share quantity. The buy remains pending if the next session is not executable under frozen market/capacity rules.

## Required outputs

Report at minimum:

- Wealth Core CAGR, maximum drawdown, Sharpe, ending equity/multiple.
- SPY CAGR, maximum drawdown, Sharpe, ending multiple.
- admissions, buys, sells, next-open zero-quantity blocks, cash-limited open executions, delayed executions, and maximum delay.
- whole-share rounding underfill.
- minimum/median entry-open weight and counts below 1%, 2%, and 3%.
- resolved S&P membership counts and membership provenance/limitations.
- generated-source hashes, transaction/order blotter, position lifecycle, daily observer, and integrity checksums.

Research only. Do not modify production or main. Do not merge.
