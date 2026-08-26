# Orion Strategy Principles

**Status:** research design constraint. This file does not activate or promote a strategy.

## Economic theses

- **Wealth Core — Pick winners and let them compound.**
- **Sentinel — Protect compounding when weakness becomes broad and systemic.**
- **LD-RC — Do not restore full risk until leadership is healthy again.**
- **Fastgate — Respond early to an acute shock, but require persistence before fully de-risking.**

## Layer ownership

Each return-sensitive layer gets one job:

1. **Wealth Core chooses what to own.** It identifies persistent leaders and lets successful holdings compound.
2. **Sentinel owns confirmed de-risking.** It decides when portfolio/market weakness is sufficiently broad and systemic to justify reducing risky exposure.
3. **LD-RC owns re-entry after a confirmed defensive episode.** It may delay a return to full risk while leadership remains unhealthy; it should not become a second independent crash detector.
4. **Fastgate owns only the early-warning interval.** A first acute warning may reduce exposure provisionally; full de-risking requires persistence/confirmation. A cleared provisional warning must not create a separate long recovery lock.

## Rule-admission test

A new return-sensitive rule is admitted only when all are true:

1. It maps directly to one of the four theses above.
2. Its input is causally available by the decision cutoff.
3. Its economic rationale exists independently of an observed backtest improvement.
4. Its benefit is not concentrated in one historical episode and survives structural ablation / independent time blocks where evidence is available.
5. It does not duplicate another layer's job.
6. It does not require adding replacement thresholds merely to recover CAGR lost during simplification.

If a rule fails this test, delete it rather than tune it.

## Anti-backfit rule

Simplification experiments are structural ablations, not parameter searches. Do not sweep thresholds, recovery lengths, exposure levels, or crisis dates to maximize historical CAGR. Prefer a materially simpler rule with slightly lower historical CAGR when its economic mechanism is clearer and its behavior is more stable.

## What this simplicity constraint does not apply to

PIT reconstruction, security/issuer identity, Sharadar price and volume domains, corporate actions, delistings, accounting, execution timing, restart safety, shadow-book parity, and certification are **correctness infrastructure**, not alpha rules. They remain as rigorous as necessary even when the investment logic is simple.

## Current LD-RC research direction

The next simplification is deliberately one-sided: keep Sentinel's de-risking logic frozen and test whether LD-RC can be reduced to a minimal re-entry guard using only recent-leadership health. The experiment order and anti-backfit constraints are recorded in GitHub issue #318 before results are observed.
