# E3 broad-universe stability basin diagnostic

Base head: `3f27834db427e71d9bb8d0b6160c8835b739c906`

Objective: map a stable parameter basin around E3 on the original broad-universe Strategy 9 surface. This is a robustness diagnostic, not a strategy optimization pass.

Primary sensitive inherited parameters:
- recovery persistence (`LDRC_REC`)
- divergence recent-leadership threshold (`LDRC_R20`)
- divergence SPY r20 floor
- full-persistence recent r40 floor
- healthy damaged ceiling

Secondary surfaces:
- E3 WC r20 floor
- E3 recent-vs-WC margin
- E3 SPY-vs-WC margin
- SPY V-rebound threshold
- LD drawdown threshold
- defensive allocation ceiling
- FAST damaged threshold

Acceptance focus: broad local stability in CAGR, max drawdown, Sharpe, allocation path, crisis release timing, and 5/10/15/20-year consistency. No parameter will be selected solely for maximum CAGR.

Parallel E5 and PIT-corpus work must remain untouched.
