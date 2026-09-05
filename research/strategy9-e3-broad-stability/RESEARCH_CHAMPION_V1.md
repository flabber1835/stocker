# Research Champion v1

Date selected: 2026-09-05

## Name

**Research Champion v1** = Strategy 9 + E3 at the stability-selected broad parameter center.

This is the research strategy state selected after the Stage 1 and Stage 2 stability-basin exercise. It is selected for local robustness / plateau centrality, not for the highest historical CAGR.

## Exact configuration

| Parameter | Research Champion v1 |
|---|---:|
| LDRC_REC | 8 sessions |
| LDRC_R20 | -8.5% |
| LDRC_V | +11.0% |
| LDRC_DD | -10.0% |
| divergence SPY floor | 0.0% |
| full-recovery r40 floor | 0.0% |
| FAST damaged breadth | 88.0% |
| healthy damaged ceiling | 63.0% |

The E3 cross-surface release requires:
- 8 positive recent-leadership r20 sessions;
- owned Wealth Core r20 > 0;
- recent leadership r20 >= owned Wealth Core r20;
- SPY r20 >= owned Wealth Core r20.

Existing persistence and SPY V-rebound release routes remain. Wealth Core mechanics, the residual-correlation peer definition, portfolio mechanics, execution timing, and other Strategy 9 mechanics are otherwise unchanged from the accepted lineage.

## Stability lineage

- Original E3 source head: `3f27834db427e71d9bb8d0b6160c8835b739c906`
- Stability Stage 1 run: `33971822256`
- Stability Stage 2 run: `33974007040`
- Final stability-verdict head: `256d0f55386ccfdcea58accd12135d263f5c9092`
- Full verdict: `research/strategy9-e3-broad-stability/FINAL_STABILITY_VERDICT_2026-09-05.md`

Broad-history center result used for selection:
- 20y CAGR: 20.3000%
- 20y max drawdown: -28.6507%
- 20y Sharpe: 1.100287
- 20y ending multiple: 40.300396x

These broad-history results are **selection/robustness evidence, not the formal PIT-certified result**.

## Formal PIT certification contract

The Research Champion formal certification workflow is:

`.github/workflows/backtester-research-champion-pit-20y.yml`

It must:
1. bind `source_sha == strategy_sha == github.sha`;
2. use the official reusable mandatory PIT / financial / causality suite;
3. use pinned runtime main SHA `887f479b15ad861313da666ad698034d3847121c`;
4. consume the immutable canonical PIT package referenced by `backtester/data/canonical-pit-20y.json`;
5. run the 2006-01-03 warm-up, 2006-07-31 measurement start, and 2026-07-31 end;
6. preserve the financial-grade 15-session dividend settlement lag, resolved-NAV requirement, terminal grace, and fail-closed missing leadership-return rule;
7. promote the selected E3 Candidate A economics into the authoritative `research_nav` / `research_allocation` path before certification;
8. prove exact parity between the promoted authoritative path and Candidate A;
9. terminate at the repository's common authoritative PIT finalizer.

Only a finalizer result of `PIT_CERTIFIED` constitutes formal certification. This document does not pre-claim that result.

## Branch policy

`research/research-champion` is the isolated certification branch. It does not modify Production, E5/coupling, or the PIT-corpus branches.

Once a commit on this branch receives `PIT_CERTIFIED`, that exact commit SHA is the immutable Research Champion v1 certified source identity. Later documentation/reporting should reference that SHA rather than silently redefining the Champion.
