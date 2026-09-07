# Median-5 statistical closure v14

Eight analysis slots were granted after the fresh full-PIT Median-5 recertification was launched.

The battery is preregistered as:

1. DSR — Deflated Sharpe Ratio with a documented research-trial lower bound of 41 and 100/250-trial sensitivities.
2. PBO_CSCV — combinatorially symmetric-style cross validation over the six hardening discovery candidates plus fresh Median-5, using 15 contiguous blocks and all 6,435 choose-7 partitions.
3. REALITY_CHECK — White-style circular block bootstrap across that hardening candidate family relative to SPY.
4. ROLLING_WINDOWS — monthly-ending 3/5/7/10-year realized-path stability.
5. TEMPORAL_LEAVEOUT — descriptive leave-one-calendar-year-out return-path analysis. This is explicitly not presented as a causal strategy replay.
6. BLOCK_BOOTSTRAP — paired 20-session circular block bootstrap of Median-5 and SPY returns.
7. CONTRIBUTOR_CONCENTRATION — exact security holding-day exposure concentration from the certified selected-position witness. This does not claim per-security P&L attribution; a true winner-removal experiment would require additional causal replays/telemetry.
8. WORST_REGIME — descriptive calendar and contemporaneous SPY-volatility decomposition, including the worst 252-session realized period.

Every job is gated on successful completion of fresh full-PIT recertification run 34160387335 and independently verifies its RESULT.json asserts PIT=true, prerecorded_decisions_used=false, 5,032 sessions, 2006-07-31 through 2026-07-31, and exact one-session dividend settlement.

No strategy parameter is changed by this battery. No result is used to tune Median-5 inside these jobs.
