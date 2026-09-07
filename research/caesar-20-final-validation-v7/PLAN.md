# Caesar 20 final pre-hardening validation

Status: preregistered before execution.

Frozen candidate: Caesar 20 = 20 slots, 5% nominal entry weight, corrected one-session dividend settlement, factual security classifier, 21-session cooldown, 119-session review age, 30% trailing-stop loss boundary, one-at-a-time post-initialization admissions, certified PIT corpus.

## Eight causal replay slots

Five deterministic security jackknives exclude one disjoint security-id modulo-5 bucket at admission time. Each removes approximately 20% of the security opportunity set and together covers the complete universe once. These are causal name-concentration tests and do not use realized returns to choose excluded names.

1. JACKKNIFE_BUCKET_0
2. JACKKNIFE_BUCKET_1
3. JACKKNIFE_BUCKET_2
4. JACKKNIFE_BUCKET_3
5. JACKKNIFE_BUCKET_4
6. LIQ_ADV40M — doubles the 20-session average-dollar-volume floor from $20m to $40m.
7. LIQ_ADV80M — quadruples the 20-session average-dollar-volume floor from $20m to $80m.
8. LIQ_DAYDV10M — doubles the same-day dollar-volume floor from $5m to $10m.

No arm changes the PIT package, security-type authority, dividend timing, ranking features, exit semantics, cooldowns, defensive logic, or terminal economics.

## Statistical validation requiring zero economic replay slots

The workflow also computes from frozen existing portfolio-size artifacts:

- Deflated Sharpe Ratio for Caesar 20 using 33 documented minimum trials, plus 100- and 250-trial multiplicity sensitivity.
- Combinatorially Symmetric Cross-Validation / Probability of Backtest Overfitting across the full tested size family 16,18,19,20,21,22,23,24,25.
- White-style paired block-bootstrap Reality Check against SPY across the same candidate family.

The statistical candidate family and artifact IDs are fixed before this workflow runs.

## Acceptance interpretation

The purpose is fragility detection, not optimization. No stress arm may become a new candidate from this run. Caesar 20 remains frozen. Strong evidence is broad survival across all five disjoint name jackknives, acceptable economics at materially higher liquidity thresholds, low PBO, high DSR probability after multiplicity adjustment, and a significant Reality Check after data-snooping correction.

Performance outcomes are not used to alter any arm during execution.
