# Second five-run Champion alpha validation

Status: PREREGISTERED. These five arms are fixed before viewing any result from this round.

Authoritative corrected baseline: workflow run 34071569702, artifact 10001317230, 20y CAGR 18.8008888001%, max drawdown -24.9136616725%, Sharpe 1.0363365863, exact one-session dividend settlement.

The first five causal experiments falsified immediate slot reuse, unrestricted multi-refill, age-59 weak review, and staged recovery as alpha improvements. This round probes structural questions that follow from those failures while preserving the successful baseline mechanisms wherever the arm does not explicitly change them.

## Fixed arms

1. CONCENTRATED_20
   - N_SLOTS: 25 -> 20
   - ENTRY_W: 0.04 -> 0.05
   - Keeps nominal fully invested book capacity at 100%.
   - Tests whether the ranking edge is concentrated enough that the lowest five baseline slots dilute alpha.

2. DIVERSIFIED_30
   - N_SLOTS: 25 -> 30
   - ENTRY_W: 0.04 -> 1/30 (0.03333333333333333)
   - Keeps nominal fully invested book capacity at 100%.
   - Tests whether additional diversification improves risk-adjusted compounding enough to offset admitting lower-ranked candidates.

3. LATE_REVIEW_159
   - REVIEW_AGE: 119 -> 159 sessions.
   - Leaves stop logic, ranking, cooldowns, admission cadence, and sizing unchanged.
   - The age-59 review was strongly destructive; this tests the directional implication that additional patience may be valuable.

4. LONGER_SLOT_COOLDOWN_42
   - Only empty-slot reuse delay: 21 -> 42 sessions.
   - Security-specific cooldown remains exactly 21 sessions.
   - Leaves one-admission-per-day and all selection logic unchanged.
   - Immediate slot reuse was destructive; this tests whether additional vacancy patience adds value.

5. TIGHTER_STOP_25
   - Trailing stop threshold: 30% below peak -> 25% below peak (STOP_RET 0.70 -> 0.75).
   - Leaves review age, cooldowns, portfolio size, sizing, and defensive controller unchanged.
   - Tests whether individual-loss containment can improve difficult transitions such as 2018 while retaining the long-horizon stock-selection engine.

## Hard experimental contract

Exactly five historical replays are authorized. No parameter sweep, rerun with altered economics, or result-dependent replacement arm is authorized. Infrastructure/preflight failures before historical replay do not consume an economic experiment slot.

Every arm must:
- rebuild from the exact corrected one-session certified source identity;
- consume the immutable canonical PIT package pinned by digest f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c and dataset hash 5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993;
- execute a fresh chronological 2006-07-31 through 2026-07-31 replay with 5,032 measurement sessions;
- use no prerecorded decisions, holdings, NAV paths, crisis dates, or oracle outputs;
- preserve next-session execution timing and exact one-session dividend settlement;
- preserve the factual security-type classifier and fail closed on classification coverage changes;
- record exact source, runtime, corpus, classifier, and variant hashes;
- remain isolated from main and production branches.

If a variant exposes a genuinely new security classification requirement, stop that arm and emit the exact security/interval gap. Do not infer classification from price, returns, survival, ranks, or strategy outcomes.

Primary comparison: 20-year CAGR versus the 18.8008888001% corrected baseline. Secondary comparisons: ending multiple, max drawdown, Sharpe, 5/10/15-year windows, holdings, transactions, allocation exposure, and classification/PIT provenance.
