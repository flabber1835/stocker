# Wealth Core V1 — 10 bp open-time sizing results, insights, and recommendation

## Status

Research-only evidence. No production change is authorized by this note.

- Workflow run: `34294467743`
- Trigger head: `428e9792bd7c63d604a95dfc3ae40a2b0fcc1fe8`
- Persisted evidence head before this note: `0615269b521ba65f58345e8fa21baefd377ac0a6`
- Canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Initial capital: $100,000
- Measurement window: 2006-07-31 through 2026-07-31
- Dividend lag: 1 session
- Cash cushion: 10 bp

## Experiment design

The certified 10 bp Wealth Core control froze a share quantity at the prior close and then attempted to execute that quantity at the next open.

The two experimental arms changed only the execution-sizing boundary:

1. **Open-time whole shares** — the close selects the ticker and intended 4% dollar target; the next open calculates the largest affordable whole-share quantity from the actual opening price and actual cash.
2. **Open-time fractional shares** — the close selects the ticker and intended 4% dollar target; the next open calculates the exact fractional quantity from the actual opening price and actual cash.

The 10 bp cash cushion is a close-time admission cushion and is released into the execution funding pool at the open. No share quantity is frozen at the prior close.

## Results

| Metric | Certified 10 bp control | Open-time whole shares | Open-time fractional |
|---|---:|---:|---:|
| CAGR | 15.488288% | 14.647576% | 14.214093% |
| Max drawdown | -49.042739% | -50.569358% | -50.957407% |
| Sharpe | 0.805082 | 0.757490 | 0.748440 |
| Ending equity | $1,646,091.83 | $1,422,872.69 | $1,318,352.68 |
| Completed entries | 519 | 521 | 515 |
| Next-open blocks | 1 | 0 | 0 |
| Gap-clipped entries | 19 | 0 | 0 |
| Invalid-open blocks | n/a | 0 | 0 |
| Zero-quantity blocks | n/a | 0 | 0 |
| Whole-share rounding underfill | n/a | $21,402.80 cumulative | $0.00 |
| Fractional buy rows | 0 | 0 | 515 |

The whole-share arm recorded 522 close admissions and 521 completed entries while still recording zero next-open blocks under the experiment's execution accounting. The fractional arm recorded 515 close admissions and 515 completed entries.

## Main insight

The fragile behavior comes from binding the **share quantity** at the prior close.

That quantity is derived from yesterday's price, while execution occurs at today's opening price. An overnight gap can therefore force a smaller fill or a complete failure even though Wealth Core's economic decision — which stock it wants and how much capital it wants allocated — has not changed.

This introduces execution noise into portfolio construction. Small price differences can change share counts, whether a trade occurs, slot occupancy, future admissions, exits, and ultimately the long-run portfolio path.

The open-time sizing experiment removed that failure mode completely in both tested arms:

- zero next-open blocks;
- zero gap-clipped entries;
- zero invalid-open blocks;
- zero zero-quantity execution blocks.

The performance differences are not evidence that open-time sizing is mechanically inferior. Both experimental arms diverged materially from the certified control path beginning on 2006-11-02, so CAGR, drawdown, and Sharpe differences are path-dependent consequences of altered sizing and admissions.

## Fractional-share insight

Fractional shares are not required to solve the close-to-open binding problem.

Open-time whole-share sizing already eliminated all measured next-open execution failures. Fractional sizing adds sizing precision: the whole-share arm left $21,402.80 of cumulative intended execution budget unused because of integer rounding, while the fractional arm reduced rounding underfill to effectively zero.

Therefore fractional shares solve a second-order precision issue, not the primary execution-binding problem.

## Recommendation

For production design discussion, prefer the following Wealth Core execution contract:

### Close

Bind only the economic decision:

- selected ticker;
- intended dollar target / portfolio weight;
- slot reservation and decision provenance.

Do **not** bind a share quantity using the close price.

### Next valid open

Using the actual executable opening price and actual available cash:

1. calculate the executable dollar budget;
2. calculate the share quantity at that price;
3. execute the trade;
4. record any difference between intended target and actual funded amount as sizing telemetry rather than treating it as a failed prior-close share order.

### Initial production preference

Use **open-time whole-share sizing first**.

Reasons:

- it eliminated all measured next-open blocks and gap clipping in this 20-year PIT experiment;
- it preserves the current whole-share operational model;
- it avoids introducing broker-specific fractional-share behavior into the first production change;
- its remaining distortion is measurable and limited to whole-share rounding.

Fractional shares should remain a separate optional enhancement. They provide exact sizing but add execution/broker/corporate-action operational complexity without being necessary to solve the primary binding problem.

## Important limitation

Open-time sizing guarantees execution of an admitted trade only to the extent that there is positive executable cash and a valid market price/volume at the open. It does **not** guarantee that every trade receives the full intended 4% target when available cash is insufficient. In this experiment, the whole-share arm recorded 118 cash-limited open executions and the fractional arm 114.

If the future requirement becomes "every admitted trade must always receive its full intended target size," that is a different financing problem and would require additional spendable cash, margin/borrowing, or a different admission policy.

## Production-design conclusion

The evidence supports changing Wealth Core from **close-bound share quantity** to **close-bound economic intent with open-time quantity determination**.

Recommended first implementation candidate: **10 bp close-time admission cushion + open-time whole-share sizing**.

Fractional shares are not recommended as part of the first implementation. Evaluate them separately if eliminating the remaining whole-share rounding error is operationally worthwhile.
