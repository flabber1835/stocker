# Certification decision: fixed-forward causal ranking contract

Date: 2026-08-31

Status: ACCEPTED

Scope: strict-PIT research/production causal certification only. This decision does not modify `main`.

## Question

The first strong-equivalence failure occurred on 2006-08-08: corrected production and retained research had the same 842-security eligible universe and the same economic portfolio state, but their leadership/durable ranking hashes differed.

Two possible signal authorities existed:

1. the canonical package's stored Sharadar `SEP.close` value, which is vendor split-adjusted using the vendor snapshot's adjustment basis; and
2. Wealth Core's production signal contract: `signal_close(t) = raw_close(t) * cumulative_split_factor(t)`, where the cumulative factor contains only split ratios effective on or before historical session `t`.

The second contract is the normative causal contract because it cannot incorporate a split that had not happened yet and it is the contract implemented by the shared production feed.

## Evidence

Canonical PIT dataset:

`f9fb220871ad4152549d31a5da6e0dbcdd327dc7b05843764511b0e800ddb19b`

Pinned production source:

`887f479b15ad861313da666ad698034d3847121c`

Initial ranking diagnostic:

- run `33411456328`
- artifact `9765650269`
- session `2006-08-08`

The first independent 80-digit adjudicator used stored canonical `SEP.close`. It found that retained research matched that stored series more closely than production. That result answered only "which engine matches the vendor-adjusted stored column?" and is not sufficient to decide the causal strategy contract.

A second independent 80-digit adjudicator reconstructed every disputed signal from canonical raw closes and canonical causal split ratios, without calling either production or research signal helpers:

- run `33414296781`
- artifact `9766402373`
- adjudicator source commit `de9a49dc2d4241433a079bc73d4fdd302dad7393`
- workflow launch commit `123f8499611a5c7a7d24bf881cd48a05f24a6d71`

Verdict:

`PRODUCTION_MATCHES_FIXED_FORWARD_CAUSAL_REFERENCE`

Exact ordering checks:

- production leadership: PASS
- production durable ranking: PASS
- research leadership: FAIL
- research durable ranking: FAIL

Production numeric error against the 80-digit reference was approximately floating-point roundoff (`~1e-15`). Research differed materially (`momentum` max error about `8.10e-4`; durable-score max error about `1.34e-3`). Witnesses included BKNG, CELG, MOGN and SLG.

## Decision

Production is authoritative for this dispute. Retained research must be repaired to reproduce the fixed-forward causal signal basis and production's ranking arithmetic. The strict equivalence gate must not be weakened or changed to accept the research ordering.

Specifically:

- do not use the canonical package's stored vendor-adjusted `SEP.close` as the research strategy signal;
- reconstruct the research signal chronologically from canonical `raw_close` and same-or-prior-session canonical `split_ratio` values;
- use the corresponding fixed-forward signal basis for the execution-open review signal;
- preserve the raw/as-traded price and raw-compatible volume domains for marking, execution and liquidity;
- eliminate `float32` truncation from the signal history used to choose leadership/ranking order;
- compute durable-score volatility with arithmetic equivalent to the production contract where ranking order is economically active;
- retain the exact ranking-hash gate. Any later divergence must fail closed and be independently adjudicated.

## Rationale

Using a current-vintage split-adjusted historical column as the normative signal can encode the effect of corporate actions that occur after the historical observation. Even when ratios often cancel in returns, vendor rounding/rebasing can alter close rankings near ties. The fixed-forward construction is explicitly chronological: a split changes the cumulative factor only on its effective historical session. It therefore preserves continuity without importing future split knowledge.

The correction belongs to the retained research implementation/backtester certification layer. It is not a strategy change and it is not evidence that the pinned production strategy requires a ranking fix.

## Required validation before resuming the 20-year chain

1. Re-run the 2006-08-08 diagnostic and require research leadership and durable ranking to equal production.
2. Re-run the complete 2006 annual strong-equivalence segment and require all exact and numeric gates to pass.
3. Only then resume the restartable annual 20-year causal certification.
