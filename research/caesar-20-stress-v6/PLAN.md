# Caesar 20 stress validation v6

Purpose: test whether Caesar 20's historical edge survives realistic execution, ranking, and implementation perturbations while preserving causal PIT semantics.

Frozen research candidate: **Caesar 20** = 20 slots, 5% nominal entry weight.

Six preregistered arms:

1. `ENTRY_DELAY_1` — execute reserved entries one additional trading session later.
2. `ENTRY_DELAY_2` — execute reserved entries two additional trading sessions later.
3. `EXIT_DELAY_1` — execute ordinary stop/review exits one additional trading session later.
4. `RANK_TOP3_REVERSE` — deterministically reverse the first three ranked candidates each day before the existing eligibility/admission filters. This uses only same-session PIT-ranked information.
5. `COST_25BPS_RT` — 12.5 bps modeled cost on each side, 25 bps round trip.
6. `COST_50BPS_RT` — 25 bps modeled cost on each side, 50 bps round trip.

Every arm starts from the exact corrected 25-stock certified generated source, first applies only the Caesar 20 definition (`N_SLOTS=20`, `ENTRY_W=0.05`), then applies exactly one stress dimension above.

Frozen invariants: canonical PIT package and dataset hash, exact one-session dividend settlement, factual security classifier, 21-session cooldown, 119-session review, 30% trailing stop, one-at-a-time initialized admissions, terminal economics, defensive logic, and all other economic rules.

No performance target is used. No future prices, returns, winners, realized contributors, or strategy outcomes enter any decision. Ex-post winner-removal/contribution tests will be treated separately as diagnostics and will not be represented as causal promotion evidence.
