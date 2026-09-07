# Champion portfolio-size robustness sweep

Purpose: test whether the 20-holding result from round 2 is a broad concentration effect or an isolated historical optimum.

Reference baseline: corrected certified 25-slot strategy, 20y CAGR 18.8008888001%, max drawdown -24.9136616725%, Sharpe 1.0363365863.

Exactly five economic replays are authorized and preregistered before outcomes:

- SIZE_16: N_SLOTS=16, ENTRY_W=0.0625
- SIZE_18: N_SLOTS=18, ENTRY_W=0.05555555555555555
- SIZE_20: N_SLOTS=20, ENTRY_W=0.05
- SIZE_22: N_SLOTS=22, ENTRY_W=0.045454545454545456
- SIZE_24: N_SLOTS=24, ENTRY_W=0.041666666666666664

For every arm, nominal full-book entry capacity remains 100%. All other certified semantics remain fixed: ranking, eligibility, PIT classifier, 21-session slot/security cooldown, one-at-a-time initialized admissions, review age 119, 30% trailing stop, market-risk controller, next-session execution, transaction costs, and exact one-session dividend settlement.

No parameter sweep beyond these five points, no adaptive reruns, and no result-dependent substitution. Each replay must use the immutable canonical PIT corpus hash 5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993, the same frozen classifier authority, 5032 measurement sessions from 2006-07-31 through 2026-07-31, and no prerecorded decisions.

Interpretation rule fixed before outcomes: evidence for a robust concentration effect requires a broad neighborhood around 20 holdings to improve on the 25-stock certified baseline on return and preferably Sharpe/drawdown. A sharp isolated peak at 20 is treated as backtest-sensitive. No result from this sweep is automatically promoted to production.