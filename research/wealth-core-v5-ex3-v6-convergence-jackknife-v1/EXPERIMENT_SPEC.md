# Wealth Core V5 + Sentinel EX3 V6 convergence jackknife v1

## Objective

Test whether one research-only convergence release materially reduces Sentinel EX3 V6 sensitivity to small Wealth Core V5 path perturbations.

This is a robustness experiment. It does not authorize production changes or parameter tuning.

## Frozen control authority

System: Wealth Core V5 + Sentinel EX3 V6 (`r40_m04_rec8`).

Sentinel EX3 V6 control configuration:

- REC = 8
- full-recovery R40 floor = -4%
- divergence R20 threshold = -8.5%
- SPY V rebound = +11%
- Core DD divergence = -10%
- divergence SPY floor = 0%
- divergence ceiling = 55%
- FAST damaged breadth = 88%
- healthy damaged ceiling = 63%

Exact selected-source SHA-256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`.

Canonical PIT measurement window: 2006-07-31 through 2026-07-31, with warmup beginning 2006-01-03.

The unpatched arm must reproduce exact Core, transaction, close-decision, and EX3 V6 parity before perturbations are allowed.

## Treatment

Candidate B inherits the exact authoritative EX3 V6 Candidate A implementation and adds one finite-memory release only.

A session is neutral for this treatment when:

- native target is full risk;
- effective native target is full risk;
- the normal divergence inputs are available; and
- the current EX3 V6 divergence predicate is false.

After eight consecutive neutral sessions, if authoritative EX3 V6 still holds exposure below the native target because of retained overlay state, the treatment clears the retained EX3 episode/divergence state and returns to the current native target.

The treatment:

- changes no Wealth Core rule;
- changes no Sentinel trigger threshold or exposure level;
- has no future-data or baseline-path access;
- preserves next-session allocation timing;
- is research-only and may not be merged or promoted by this experiment.

## Paired design

Each full-PIT perturbation produces one Wealth Core path. Both controllers consume that exact path:

- A: authoritative unpatched EX3 V6;
- B: EX3 V6 plus the convergence release.

Cases:

- one exact 20-year baseline;
- 16 deterministic leave-one-out security cases selected from baseline-held security IDs by fixed SHA-256 ordering;
- 1% deterministic universe dropout with seeds 11, 29, and 47.

Performance is never used to choose cases.

## Primary robustness measurements

Core path:

- first and last divergence;
- exact portfolio-match fraction;
- median Jaccard overlap;
- maximum differing holdings;
- first post-divergence 20-session exact reconvergence;
- terminal reconvergence status;
- Core CAGR/DD/Sharpe and terminal-NAV deltas as diagnostics.

Sentinel, separately for A and B:

- first and last allocation divergence versus its own baseline;
- allocation-divergence sessions and fraction;
- first post-divergence 20-session exact reconvergence;
- terminal reconvergence status;
- divergence persisting after the excluded security has left the baseline portfolio;
- path amplification = Sentinel allocation-divergence fraction / Core portfolio-divergence fraction;
- economic amplification = absolute full-system CAGR perturbation / absolute Core CAGR perturbation when defined;
- full-system CAGR/DD/Sharpe and terminal-NAV deltas as diagnostics.

## Fail-closed evidence rules

The final aggregator refuses a verdict unless all 16 leave-one-out cases and all three dropout cases are present, each with exactly one result and one paired daily tape aligned to the baseline dates.

A quiet period before the first divergence can never count as reconvergence.

## Precommitted verdict logic

The robustness verdict is based on path stability and Sentinel propagation. CAGR, drawdown, Sharpe, and terminal NAV are diagnostic and cannot create a positive robustness verdict.

`MATERIAL ROBUSTNESS IMPROVEMENT` requires all of:

- at least 25% reduction in median Sentinel allocation-divergence fraction across the 16 leave-one-out cases;
- at least 25% reduction in median Sentinel/Core path-amplification ratio;
- no increase in leave-one-out cases that never achieve a post-divergence 20-session reconvergence;
- at least 12 of 16 leave-one-out cases improve allocation-divergence fraction;
- no more than 4 of 16 leave-one-out cases worsen it;
- no more than one of the three 1% dropout cases worsens allocation-divergence fraction.

`SOME IMPROVEMENT, BUT BUTTERFLY ISSUE REMAINS` requires lower median allocation divergence, non-worse median path amplification, more leave-one-out wins than losses, and no more than one dropout loss, while falling short of the material gate.

`WORSE` requires worse median allocation divergence and path amplification, more leave-one-out losses than wins, and dropout evidence that is not directionally better.

All other complete outcomes are `NO MEANINGFUL IMPROVEMENT`.

Any later change to these rules requires a new experiment version and new evidence.
