# Median-5 + 10 bp open-time sizing + EX3 full-PIT experiment

Objective: run one fresh canonical 20-year PIT replay that records both the pure Wealth Core book and the frozen EX3/Candidate-A overlay on that same book.

## Frozen Wealth Core configuration
- Median-5: 20 slots
- 5% target entry weight
- trailing-five causal rank-order hardening of the current top three
- 10 bp close-time admission cushion
- next-valid-open whole-share position sizing from actual opening price and actual available cash
- no prior-close share quantity binding
- one-session dividend settlement
- existing cooldown/review/stop/liquidity/cost/security-type/PIT semantics unchanged

## Recorded outputs
1. Pure Wealth Core metrics from the raw book NAV (`shadow_equity` / equivalent raw-book series).
2. Frozen EX3 / Candidate-A overlay metrics from `A_nav` on the same underlying Wealth Core path.
3. Incremental EX3 contribution: CAGR, max-drawdown, Sharpe, ending multiple, transition counts, and allocation statistics.

No tuning. No production change. Full canonical PIT window: 2006-07-31 through 2026-07-31.
