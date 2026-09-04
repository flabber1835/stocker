# Russell 1000 PIT research idea

Date: 2026-09-03
Status: research design; not yet a production strategy change

## Objective

Create a cleaner point-in-time research universe for Wealth Core / Sentinel by using historical Russell 1000 membership as the primary eligibility authority and removing historical metadata dependencies that are currently unstable under PIT reconstruction.

The goal is to preserve a broad large/mid-cap opportunity set while making the strategy's historical state depend primarily on observable market data and index membership, not on incomplete historical issuer/sector metadata.

## Core design

### 1. Universe authority

A security is eligible for the research universe only when it is an authenticated Russell 1000 constituent on that decision date.

Russell 1000 membership itself is treated as the security-type/listing eligibility authority for the experiment. We do not separately require historical Sharadar category or exchange metadata for inclusion.

Historical membership must be point-in-time/best-effort-PIT and must never be backfilled from current membership.

### 2. Security identity, not issuer-family identity

Each listed security/share class is treated independently.

We do not use SEC CIK, current Sharadar `relatedtickers`, or another issuer-family grouping to prevent simultaneous ownership of related share classes.

Example: if GOOG and GOOGL are both Russell 1000 constituents and both independently qualify under Wealth Core, both may be owned. The resulting economic concentration is an explicit portfolio rule, not an identity-resolution failure.

Stable security/ticker identity is still required to join Russell membership to the historical SEP tape and corporate actions.

### 3. Remove historical sector metadata from Sentinel breadth

Historical SIC, current Sharadar sector, and other taxonomic sector labels are not used in the experiment.

The sector-contagion component of damaged breadth is replaced by causal price-derived peer groups.

Initial correlation-peer definition reuses the existing causal dynamic-peer research design:

- trailing window: prior 252 trading sessions only;
- minimum common observations: 120;
- market factor: SPY;
- residualize each security's returns against SPY using only prior observations;
- calculate pairwise Pearson correlations of residual returns among current holdings;
- retain up to the three strongest peers whose residual correlation is at least 0.145;
- peer neighborhood = the security itself plus retained peers;
- peer stress = RED fraction within that neighborhood;
- contagion AMBER clause uses the existing >= 50% stressed-peer threshold and existing `not green` condition.

All peer calculations must end strictly before the decision session. No future returns or future membership may enter the peer graph.

### 4. Preserve the individual holding-health classifier

The existing individual GREEN / RED / AMBER predicates remain frozen for the first experiment except for substituting causal peer stress for sector stress.

The experiment is intended to test domain translation, not to optimize the classifier.

### 5. Preserve Wealth Core and LD-RC parameters

For the first R1000 run, do not calibrate strategy parameters.

Keep frozen:

- 25 positions;
- 4% nominal entry weight;
- one new entry per session after initialization;
- 126-session momentum lookback;
- 21-session recent-period skip;
- top 10% candidate/leadership fraction;
- minimum 25 leadership names;
- age-119 review;
- 30% trailing-stop retention rule;
- 21-session cooldown;
- current modeled transaction cost;
- native Sentinel thresholds;
- recovery ramp;
- Simplified LD-RC v3 thresholds and timing.

The purpose of the first run is to measure the unchanged strategy on the new PIT domain.

## Why this design

The broad full-stack PIT forensic showed that raw PIT Wealth Core remained strong, but controller performance degraded because historical `damaged`/`green` breadth changed materially when incomplete strict-prior SEC SIC/CIK authority replaced current metadata.

The problem was concentrated in breadth thresholds and FAST/SLOW timing, not in recent-leadership R20/R40.

Russell 1000 plus causal correlation peers removes two unstable dependencies:

1. historical security/category/exchange eligibility is replaced by explicit Russell 1000 membership;
2. historical issuer/sector taxonomies are removed from strategy decisions.

The expected geometry is also closer to the original Sentinel/LD-RC development domain: approximately 1,000 constituents implies roughly 100 names in a 10% leadership/candidate pool, instead of the approximately 180-name pool observed in the current exchange-agnostic broad universe in 2022.

## PIT data contract for this experiment

Economically active historical inputs should be limited to:

- Russell 1000 membership by session;
- stable security/ticker identity sufficient to join membership to SEP;
- SEP prices and volume;
- causal split/dividend/terminal-event authority;
- SPY market data;
- BIL / causal Treasury cash data when defensive;
- prior-only return history used to construct causal correlation peers.

SEC CIK, SEC SIC, Sharadar sector and Sharadar related-ticker issuer families are deliberately not strategy inputs.

## First experiment contract

The first R1000 experiment must:

1. reconstruct the strongest available best-effort PIT Russell 1000 membership history;
2. retain provenance and confidence for every membership source/year;
3. never infer historical membership from current membership;
4. run a continuous chronological replay with a full warm-up;
5. treat each Russell-listed security/share class independently;
6. replace sector contagion only with the frozen prior-only correlation-peer rule;
7. leave all other Wealth Core, native Sentinel and LD-RC parameters unchanged;
8. report 5y, 10y, 15y, 20y and Max metrics plus SPY;
9. report membership coverage/exclusions and peer-history availability;
10. persist daily evidence, summary, metrics, manifest, checksums and a human-readable conclusion.

## Evidence labels

Until historical Russell 1000 membership is authenticated to the same standard as the final golden corpus, results must be labeled:

`BEST_EFFORT_PIT_R1000_CORRELATION_PEERS`

They must not be labeled formally PIT-certified.

## Calibration rule after the first run

Do not change parameters before inspecting the unchanged first run.

If recalibration is warranted, calibrate only after the R1000 universe and correlation-peer semantics are frozen. Use 2006 onward for development/calibration and preserve 1998-2005 as the locked historical holdout to the extent still methodologically defensible.
