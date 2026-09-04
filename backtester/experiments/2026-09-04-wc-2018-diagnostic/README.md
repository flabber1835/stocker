# Wealth Core 2018 structural-deterioration diagnostic

Research-only diagnostic. No economic candidate is being tested in this pass, so it consumes **0 additional experiments** from the owner-authorized 10-experiment budget. Current completed economic experiment count remains 3/10.

Objective: quantify how much of the 2018 Wealth Core drawdown came from holdings that remained in the portfolio after they had already failed Wealth Core's own admission-quality conditions.

Primary diagnostic condition for each held security, evaluated causally on each session close:

- security is no longer in the current top-10% momentum candidate pool; and
- its recent 21-session return is negative.

The diagnostic must record, for every Wealth Core holding from 2018-06-01 through 2019-03-31 where available:

- date, ticker/security identity, holding age and weight;
- current momentum score/rank and top-decile pool membership;
- recent 21-session return;
- entry date, actual exit date and exit reason where available;
- daily and cumulative contribution to Wealth Core P&L;
- first date the deterioration condition became true;
- sessions retained after first deterioration;
- loss or gain accumulated while retained after deterioration.

Required aggregate outputs:

1. 2018 Wealth Core total return and max drawdown.
2. Share of 2018 portfolio loss attributable to post-deterioration retention.
3. Number and percentage of held names that entered the deterioration state.
4. Median/mean/max sessions retained after deterioration.
5. Top contributors to post-deterioration losses.
6. Counterfactual-free event ledger showing exactly what the existing strategy knew and when. No hypothetical exit economics in this diagnostic.

Decision rule:

- If a material share of 2018 loss occurs after holdings have failed both existing admission-quality tests, classify the retention asymmetry as a structural Wealth Core defect and authorize a single fresh candidate replay as Experiment #4.
- If the share is small, reject this mechanism and investigate the one-admission-per-day rebuilding bottleneck or another structural mechanism before spending Experiment #4.

No new fitted thresholds, dates, rankings, or market-regime rules are introduced by this diagnostic.
