# Caesar 20 hardening experiment plan

## Objective

Test six architecture-preserving admission rules aimed at reducing the demonstrated top-of-ranking path sensitivity while freezing every other Caesar 20 economic and PIT contract.

## Frozen base

- Caesar 20: 20 slots, 5% entry weight
- corrected certified one-session dividend settlement
- exact immutable canonical PIT package and source/runtime/classifier pins used by the completed pre-hardening program
- existing liquidity thresholds, transaction cost, cooldown, review, stop, terminal, defensive and admission-budget semantics
- no prerecorded decisions
- no outcome information in candidate selection

## Why these six arms

The frozen `Slot` accounting model represents one security per 5% sleeve. Literal multi-security confidence splitting inside one logical sleeve would require an accounting-model redesign and would confound the hardening experiment with a portfolio-engine rewrite. This suite therefore tests the same economic hypothesis at the **admission-selection seam**: preserve canonical rank-1 when conviction is strong and prefer a more persistent top-three candidate when the ordering is unstable.

## Arms

1. `CONSENSUS_MEDIAN_3` — reorder only today's canonical top three by median durable rank over the latest 3 decision sessions.
2. `CONSENSUS_MEDIAN_5` — same construction over 5 sessions.
3. `GAP2_CONSENSUS_3` — keep canonical rank-1 when its ranking-score advantage over rank-2 is at least 2%; otherwise use 3-session median-rank consensus.
4. `GAP5_CONSENSUS_3` — same, with a 5% score-gap conviction threshold.
5. `TOP3_VOTE_3` — among today's top three, prefer the security with the most rank-1 appearances over the latest 3 sessions; median rank and today's rank break ties.
6. `TOP3_PERSISTENCE_3` — keep today's rank-1 when it appeared in the top three on at least 2 of the latest 3 sessions; if it did not and another current top-three candidate did, prefer the highest-ranked persistent candidate.

All history is built only from current and prior decision-session rankings. No future session is consulted.

## Primary comparison

Each arm is compared with frozen Caesar 20:

- 5/10/15/20-year CAGR
- 20-year max drawdown
- daily Sharpe
- terminal multiple
- held-count/allocation-state diagnostics
- source/PIT/classifier/dividend provenance

## Acceptance logic

A hardening candidate is interesting only if it materially reduces dependence on one-session top-rank instability while preserving most of Caesar 20's canonical economics. A normal-path result near or above ~19% 20-year CAGR with drawdown near the existing range qualifies for follow-up adversarial reversal confirmation.

This six-slot suite is the discovery stage. Only the strongest one or two arms should receive separate top-3-reversal confirmation if additional slots are authorized.
