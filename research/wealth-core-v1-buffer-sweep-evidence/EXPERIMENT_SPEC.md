# Wealth Core V1 — $100k cash-buffer sweep v1

## Objective

Run a formal six-arm cash-buffer sweep on the frozen Wealth Core V1 $100k 20-year PIT replay to determine how much uncommitted cash is needed to absorb close-to-open execution uncertainty while quantifying the close-time opportunity cost created by the reserve.

This is an execution-mechanics experiment. Historical CAGR is an observed path outcome and is not the selection criterion.

## Tested arms

Run every arm independently on the same authority:

- 0 bp
- 5 bp
- 10 bp
- 15 bp
- 20 bp
- 25 bp

Whole shares only. Fractional shares are prohibited.

## Frozen authority

Base durable evidence head:

`38eb1a0dd3ac9a37c4466198c420bd00747e6a13`

Frozen $100k V1 authority:

- run: `34267327656`
- artifact: `10073578819`
- source SHA-256: `32cd228010e09b5be42271cd6d0c38831fe7fbc74e725f592949146c48104e0f`
- daily SHA-256: `8a2e4f948720674a56737ee6291df0aff12e02a74d74b1ec5f0c75f9929adee6`
- summary SHA-256: `929ed3baacd1bb66e8174d7a6822e362e5c90da75355177d33bab3ac9f201878`

Canonical PIT dataset SHA-256:

`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`

Pinned sources:

- formal replay source: `27bb992087182c42c3c051e62bf837895f5d2ab7`
- classifier source: `ba74e79490beb8950611b1d17f5d124833b3d91e`
- runtime source: `887f479b15ad861313da666ad698034d3847121c`

Measurement window:

- start: `2006-07-31`
- end: `2026-07-31`
- sessions: `5,032`
- initial capital: `$100,000`
- dividend lag: `1 session`

## Prior 10 bp cross-check authority

The 10 bp arm must reproduce the successful prior primary replay:

- run: `34283531740`
- artifact: `10079799925`
- CAGR: `15.488287845556004%`
- ending equity: `$1,646,091.825445194`
- max drawdown: `-49.042738751414783%`
- Sharpe: `0.805082394739427`
- completed entries: `519`
- gap-clipped entries: `19`
- one-share entries: `23`
- cash-limited close decisions: `124`
- q=0 candidate skips: `1,004`
- entries below 1% intended size: `33`

A mismatch fails closed.

## Frozen economics

Freeze:

- Wealth Core V1 stock selection
- ranking and candidate ordering
- exits and review rules
- position target logic
- execution costs/slippage
- PIT dataset
- historical security-type overlays
- terminal-event handling
- one-session dividend timing
- integer-share execution
- initial capital
- measurement window

The only economic experimental variable is buffer basis points.

No Sentinel allocation or exposure-controller metric is used.

## Buffer rule

For buffer `b` basis points:

`buffer_fraction = b / 10,000`

At close-time sizing:

1. Calculate current close NAV.
2. Reserve `buffer_fraction * close_NAV`.
3. Only cash above the reserve is available to size a new purchase.
4. Share quantity is the largest permitted whole-share quantity under the normal position target and available uncommitted cash.

At next-open execution:

1. Calculate current open NAV.
2. Reserve `buffer_fraction * open_NAV`.
3. Only cash above the reserve is available to execute the planned order.
4. If the planned whole-share quantity is unaffordable, reduce it to the largest affordable whole-share quantity.
5. If zero whole shares are affordable, block the trade.
6. A buy may never spend the reserve.

At 0 bp this rule must be economically identical to frozen V1.

## Separate financing phenomena

Report these separately:

1. **Close-time cash scarcity** — uncommitted cash after the required reserve cannot fund even one share at the close.
2. **Close-time target granularity** — the normal 4% intended target cannot fund one whole share even though uncommitted cash itself is not the binding constraint. This is reported separately so whole-share price granularity is not mislabeled as cash scarcity.
3. **Next-open complete failure** — the order was planned at the close but zero shares can be purchased at the next open.
4. **Next-open gap clipping** — the order was planned at the close but fewer than the planned shares can be purchased at the next open.

For every next-open clipped or blocked order, retain the close plan, next-open price, close-to-open gap, actual cash, reserve, uncommitted cash, notionals, quantities, and whether the next-open price alone would have exceeded the close-time uncommitted cash.

## Required arm metrics

Portfolio performance:

- CAGR
- maximum drawdown
- Sharpe
- ending equity
- ending multiple

Entry/execution behavior:

- completed entries
- cash-limited close decisions
- q=0 candidate skips
- q=0 close skips caused by cash scarcity
- q=0 close skips caused by target granularity
- next-open complete failures
- gap-clipped entries
- one-share entries
- entries below 1%, 5%, 10%, 25%, 50%, and 99% of intended size
- minimum, average, and maximum entry fraction

Buffer integrity:

- minimum post-buy cash excess over the required reserve
- reserve violations
- minimum actual cash
- fractional-share buys
- assertion that every buy quantity is an integer

Gap attribution:

- all next-open shortfall events
- events where the next-open price alone exceeds the close-time uncommitted cash for the planned quantity
- positive-gap shortfall events
- shortfall events with a positive gap greater than 2.5%
- maximum and median close-to-open gap among shortfall events

## Path divergence versus 0 bp

For each nonzero arm report:

- first date where holdings diverge
- number of close buy decisions that differ
- number of executed entry dates that differ
- number of ticker admissions that differ
- number of exits that differ
- final holding-set difference
- cumulative sessions with differing holdings

Holding-set comparisons use the frozen replay's emitted security identities, not ticker text alone.

## Saturation criteria

Execution saturation is evaluated before performance.

Report:

- smallest tested buffer with zero next-open complete failures, if any
- marginal reduction in gap-clipped fills for every +5 bp step
- marginal increase in all close-time q=0 skips for every +5 bp step
- marginal CAGR change for every +5 bp step, explicitly as path-dependent

For this experiment, define **substantial gap-clipping saturation** as:

> the smallest tested buffer below 25 bp after which every remaining +5 bp step reduces gap-clipped fills by at most one trade.

This count-based definition is preregistered before observing the sweep results. Raw counts and marginals remain authoritative even if this threshold is not met.

A mechanically sensible execution point, if one exists within the tested grid, is the smallest tested level satisfying both:

- zero next-open complete failures, and
- the preregistered gap-clipping saturation criterion.

This is not a production recommendation and does not use historical CAGR to choose the point.

## Certification gates

Fail closed unless all are true:

- 0 bp reproduces the exact frozen V1 daily SHA-256
- 0 bp reproduces the exact frozen V1 summary SHA-256
- 10 bp reproduces the prior primary 10 bp performance and key execution counts
- canonical PIT dataset hash is identical in every arm
- package-integrity evidence is identical in every arm
- final-corpus validation evidence is identical in every arm
- dividend lag is exactly one session in every arm
- whole shares only
- no fractional-share buys
- all buy quantities are integers
- self-financing cash ledger
- no negative cash outside an explicitly modeled mechanism; this harness requires minimum actual cash >= 0
- zero reserve violations
- no Sentinel metrics
- no production strategy modification

## Deliverables

The durable evidence package must contain:

1. this experiment specification
2. generated arm source for every buffer level
3. individual `RESULT.json` files
4. `SWEEP_RESULT.json`
5. `comparison.csv`
6. per-arm daily outputs
7. per-arm five-column transaction CSVs with exactly:
   - Transaction date
   - Buy or sell
   - Ticker
   - Ticker name
   - Amount of shares
8. `combined-transactions.csv` with leading `Buffer basis points`
9. combined gap/clipping event CSV
10. logs
11. PIT/package/corpus validation evidence
12. SHA-256 manifest
13. provenance
14. `INSIGHTS.md`

Ticker name remains blank when authoritative company-name text is absent from the frozen replay path.

## Research discipline

Run all six arms. Preserve favorable and unfavorable results. Do not stop early. Do not optimize for CAGR. Treat irregular performance as path dependence and quantify holding-path divergence. Do not modify production code. Do not write to main. Do not merge.
