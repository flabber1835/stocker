# Wealth Core V5 / Sentinel EX3 V6: results and simplification roadmap

Status: research experiments completed; production implementation and certification remain separate work. Tracking: [issue #349](https://github.com/flabber1835/stocker/issues/349) and [PR #350](https://github.com/flabber1835/stocker/pull/350).

Update after round 2: the campaign now has 21 completed starts. See the [ten-arm round-2 report](../wealth-core-v5-ex3-v6-simplification-v2/results/34480037109-1/RESULTS.md) and [further simplification analysis with synthetic evidence](../wealth-core-v5-ex3-v6-simplification-v2/FURTHER_SIMPLIFICATION_ANALYSIS.md). The results and future-work descriptions below preserve the checkpoint after the first eleven starts.

## Objective and architecture

Reduce mechanics and operational complexity while preserving economic output. Wealth Core decides what to hold and maintains its immutable independent shadow book. Sentinel consumes observations and decides exposure. Execution places orders and reconciles broker outcomes. Broker state remains confined to execution and reconciliation.

All completed arms preserve Wealth Core's economic projection, transactions and close decisions. Peer breadth is a Sentinel observation. Removing or optimizing that calculation leaves Core stock selection independent.

## Authority and evidence

- Baseline: Wealth Core V5 with Sentinel EX3 V6 `r40_m04_rec8`, broad full-PIT universe.
- Measurement: 2006-07-31 through 2026-07-31, 5,032 sessions; warmup starts 2006-01-03.
- Frozen generated oracle SHA256: `335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d`.
- Canonical dataset SHA256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
- Original matrix: [run 34436432038](https://github.com/flabber1835/stocker/actions/runs/34436432038), source `f769623e86e949c35a0ddf7dc7df29744c298eae`.
- Coherent combined candidate: [run 34441488484](https://github.com/flabber1835/stocker/actions/runs/34441488484), source `8d03d04c0787ddd9b1bed7ecef58183f22288a47`.
- The original ten authorized replays and the separately authorized additional replay have completed: **11 total starts**. Future full replays require additional authorization.
- Specifications, validation records, transformations, workflows and budget claims are retained in this PR. Large daily tapes and logs are in Actions artifacts with 90-day retention. The completed published summaries are preserved below as repository text.

The all-window preservation gate remains fixed: absolute CAGR difference <= 0.25 percentage points/year, maximum-drawdown deterioration <= 1 percentage point, and absolute ending-multiple change <= 5%, independently over trailing 5/10/15/20 years. Passing historical screening establishes evidence for those windows. Future behavior and production hardening require additional validation.

## Interpretation of the completed matrix

Six of nine individual treatments pass the preservation screen. Selective peers and bounded counters reproduce the historical allocation and NAV path exactly. The ten-close recovery ramp provides a structural reduction and improves its standalone 20-year CAGR to 21.6701% with maximum drawdown -26.7056%.

The ten-close and twenty-close recovery ramps are alternative designs. Each removes the intermediate 65% stage. A separate 65%-to-55% output mapping becomes redundant in either single-stage design. Consequently a literal combination of all six passing arms is not a coherent configuration.

The original matrix arm named `combined` means peer removal + twenty-close ramp + removal of both cross-surface and SPY rebound recovery routes. Its 20-year CAGR is 20.9814% and it fails the preservation screen. The later coherent combined candidate is a distinct composition described next.

## Tested coherent candidate

The follow-up composes:

1. Selective peer evaluation for holdings whose damage classification still depends on peers; all holdings remain eligible as neighbors.
2. Bounded Native and EX3 decision counters.
3. One fragile-recovery stage at 55%, followed by 100% after ten healthy closes, retaining the frozen prior-close threshold-check timing.
4. Removal of the SPY rebound release from both the recovery episode and divergence latch.

Cross-surface recovery remains active. The candidate has three exposure levels: **0%, 55%, 100%**. Severe entry, fragility selection and the other retained rules remain part of the controller.

Headline: **21.8332% 20-year CAGR, -27.3562% maximum drawdown, 51.9214x growth**. Baseline: 21.5572%, -27.3755%, 49.6193x. The candidate changes allocation on 36 sessions, reduces transitions from 28 to 26 and reduces pair-correlation evaluations from 1,574,966 to 248,321 (approximately 84.23%). These counts measure computational work; they do not establish an equivalent reduction in end-to-end runtime.

The combined candidate's recorded verdict is **FAIL_PRESERVATION_SCREEN**. Its 20-year CAGR improves by approximately 0.2760 percentage points, exceeding the symmetric 0.25-point limit by approximately 0.0260 points. The 5/10/15-year windows pass; the ending-multiple change is +4.640%. The verdict remains unchanged. Maximum interim NAV path divergence reaches 8.039%, so endpoint similarity does not establish path equivalence.

## Hardening benefit and limits

Fewer active recovery stages and release predicates reduce the cases requiring transition, restart and snapshot validation. Bounded decision counters simplify state validation. Selective peer evaluation primarily reduces computation; it retains the residual-history dependency and peer-classification semantics.

Research transformations demonstrate the tested behavior. Production cleanup still needs explicit state schemas, cause/reason coverage, migration handling and exact decision comparisons. Wealth Core/Sentinel separation remains an invariant throughout implementation.

## Further simplification opportunities

These are proposed follow-up tasks. They have not been implemented or economically tested as a new combined candidate.

| Opportunity | Expected benefit | Required evidence |
|---|---|---|
| Delete obsolete 65% ramp branches and stage index for the chosen single-stage controller | Smaller recovery state and fewer snapshot fields | Exact decision/reason parity against the tested candidate; threshold timing, unhealthy resets, severe re-entry and restart tests; explicit old-state migration policy |
| Remove unused rebound-only configuration and reason branches | Fewer configuration combinations and validation paths | Dependency audit and source/decision parity; retain SPY inputs used by fast entry, divergence or cross-surface recovery |
| Share healthy-condition and streak-update helpers | Fewer duplicated rules to maintain | Verify identical predicates and availability semantics before sharing; boundary, missing-value and timing tests; distinct counters retain their reset rules |
| Cache each symmetric peer correlation once per session and pair | Additional computational savings | Exact breadth and allocation parity; deterministic tie ordering, floating-point threshold boundaries, missing-history handling and session-local cache validity |
| Separate audit counters from decision state | Smaller state required for deterministic recovery | Dependency audit; snapshot/restart equivalence; retain decision-bearing memory, episode boundaries and auditable history |

The highest-value sequence is to specify the chosen state schema and cleanup intent, implement the parity-preserving changes, and prove exact decisions plus restart behavior against the tested candidate. This phase can use retained tapes and synthetic tests; any new full-PIT replay needs its own budget authorization.

### Larger structural experiment: remove the peer network completely

Standalone `no_peers` produced 21.4285% 20-year CAGR and -27.3755% maximum drawdown. Its 20-year ending multiple decreased 2.0965%. The 10-year CAGR improved 0.3679 percentage points, which exceeded the symmetric preservation limit. Its allocation differed on 154 sessions and its maximum NAV path divergence was 6.633%.

Complete removal would eliminate residual histories and peer correlations from this damage sensor. Its interaction with the coherent ten-close/no-rebound candidate is **untested**. The earlier matrix's `combined` arm also changed recovery duration and cross-surface behavior, so it cannot isolate that interaction. A future peer-removal follow-up should hold the coherent candidate's remaining rules fixed and preregister both its comparator and acceptance criteria.

## Evidence appendix: original completed matrix

Original publication: https://github.com/flabber1835/stocker/issues/349#issuecomment-5613613145

# V5 / EX3 V6 simplification results

Status: **COMPLETE**. [Run 34436432038](https://github.com/flabber1835/stocker/actions/runs/34436432038). Source `f769623e86e949c35a0ddf7dc7df29744c298eae`.

Ten replay starts maximum. Slot claims are permanent repository refs under `research-budget/simplification-v1/slot-*`. Failed starts remain charged. Artifact claims below count retained evidence; repository refs are the budget authority.

Claims represented in artifacts: 10/10. Missing or failed arms: none.

| Arm | Preservation | 20y CAGR | 20y max DD | 20y multiple | Changed allocation sessions | Max NAV path difference |
|---|---|---:|---:|---:|---:|---:|
| baseline | PASS | 21.5572% | -27.3755% | 49.6193 | 0 | 0.000% |
| selective_peers | PASS | 21.5572% | -27.3755% | 49.6193 | 0 | 0.000% |
| bounded_counters | PASS | 21.5572% | -27.3755% | 49.6193 | 0 | 0.000% |
| map65_to55 | PASS | 21.5249% | -27.5662% | 49.3558 | 20 | 0.531% |
| ramp10 | PASS | 21.6701% | -26.7056% | 50.5491 | 20 | 1.874% |
| ramp20 | PASS | 21.5249% | -27.5662% | 49.3558 | 20 | 0.531% |
| no_peers | FAIL | 21.4285% | -27.3755% | 48.5790 | 154 | 6.633% |
| no_cross_surface | FAIL | 21.3276% | -27.3755% | 47.7778 | 18 | 3.914% |
| no_spy_rebound | PASS | 21.7623% | -27.5195% | 51.3209 | 20 | 7.030% |
| combined | FAIL | 20.9814% | -27.5662% | 45.1238 | 198 | 10.085% |

## All-window deltas

Pass requires every window: absolute CAGR delta <= 0.25 pp/year, drawdown deterioration <= 1 pp, absolute terminal-multiple change <= 5%. Higher returns beyond the symmetric preservation limit fail.

| Arm | Window | CAGR delta (pp) | Max DD delta (pp; positive improves) | Multiple change | Pass |
|---|---|---:|---:|---:|---|
| baseline | 5y | +0.0000 | +0.0000 | +0.000% | True |
| baseline | 10y | +0.0000 | +0.0000 | +0.000% | True |
| baseline | 15y | +0.0000 | +0.0000 | +0.000% | True |
| baseline | 20y | +0.0000 | +0.0000 | +0.000% | True |
| selective_peers | 5y | +0.0000 | +0.0000 | +0.000% | True |
| selective_peers | 10y | +0.0000 | +0.0000 | +0.000% | True |
| selective_peers | 15y | +0.0000 | +0.0000 | +0.000% | True |
| selective_peers | 20y | +0.0000 | +0.0000 | +0.000% | True |
| bounded_counters | 5y | +0.0000 | +0.0000 | +0.000% | True |
| bounded_counters | 10y | +0.0000 | +0.0000 | +0.000% | True |
| bounded_counters | 15y | +0.0000 | +0.0000 | +0.000% | True |
| bounded_counters | 20y | +0.0000 | +0.0000 | +0.000% | True |
| map65_to55 | 5y | -0.0690 | -0.2090 | -0.263% | True |
| map65_to55 | 10y | -0.0673 | -0.1907 | -0.531% | True |
| map65_to55 | 15y | -0.0434 | -0.1907 | -0.531% | True |
| map65_to55 | 20y | -0.0324 | -0.1907 | -0.531% | True |
| ramp10 | 5y | +0.2412 | +0.7342 | +0.923% | True |
| ramp10 | 10y | +0.2351 | +0.6700 | +1.874% | True |
| ramp10 | 15y | +0.1514 | +0.6700 | +1.874% | True |
| ramp10 | 20y | +0.1129 | +0.6700 | +1.874% | True |
| ramp20 | 5y | -0.0690 | -0.2090 | -0.263% | True |
| ramp20 | 10y | -0.0673 | -0.1907 | -0.531% | True |
| ramp20 | 15y | -0.0434 | -0.1907 | -0.531% | True |
| ramp20 | 20y | -0.0324 | -0.1907 | -0.531% | True |
| no_peers | 5y | +0.0000 | +0.0000 | +0.000% | True |
| no_peers | 10y | +0.3679 | -0.0000 | +2.946% | False |
| no_peers | 15y | -0.2087 | -0.0000 | -2.531% | True |
| no_peers | 20y | -0.1287 | -0.0000 | -2.096% | True |
| no_cross_surface | 5y | +0.0000 | +0.0000 | +0.000% | True |
| no_cross_surface | 10y | -0.0716 | +0.0000 | -0.564% | True |
| no_cross_surface | 15y | -0.3078 | +0.0000 | -3.711% | False |
| no_cross_surface | 20y | -0.2296 | +0.0000 | -3.711% | True |
| no_spy_rebound | 5y | -0.0520 | -0.1577 | -0.198% | True |
| no_spy_rebound | 10y | +0.0412 | -0.1439 | +0.326% | True |
| no_spy_rebound | 15y | +0.0265 | -0.1439 | +0.326% | True |
| no_spy_rebound | 20y | +0.2051 | -0.1439 | +3.429% | True |
| combined | 5y | -0.0690 | -0.2090 | -0.263% | True |
| combined | 10y | -1.0508 | -0.1907 | -8.001% | False |
| combined | 15y | -1.2206 | -0.1907 | -13.974% | False |
| combined | 20y | -0.5758 | -0.1907 | -9.060% | False |

Full JSON includes runtime, peer work counts, turnover, tail returns, underwater durations and fixed crisis windows. Per-arm artifacts retain daily tapes, Core parity evidence, generated sources and logs for 90 days. Screening is historical evidence; production implementation and certification require separate review.


## Evidence appendix: completed coherent candidate

Original publication: https://github.com/flabber1835/stocker/issues/349#issuecomment-5613952064

# Combined simplification candidate

[Follow-up run 34441488484](https://github.com/flabber1835/stocker/actions/runs/34441488484). One additional replay authorized.

**FAIL_PRESERVATION_SCREEN**. Core economic projection, transactions and close decisions match the verified baseline.

| Window | Baseline CAGR | Candidate CAGR | Baseline max DD | Candidate max DD | Multiple change | Pass |
|---|---:|---:|---:|---:|---:|---|
| 5y | 31.0337% | 31.0407% | -20.4196% | -20.3984% | +0.027% | True |
| 10y | 26.4739% | 26.6624% | -27.3755% | -27.3562% | +1.500% | True |
| 15y | 22.2368% | 22.3582% | -27.3755% | -27.3562% | +1.500% | True |
| 20y | 21.5572% | 21.8332% | -27.3755% | -27.3562% | +4.640% | False |

Changed allocation sessions: 36. Maximum absolute NAV path difference: 8.039%.
20y multiple: 51.9214x. Allocation transitions: 26 (baseline 28).
Peer pair calculations: 248,321 (baseline 1,574,966).

Candidate: selective peers + bounded counters + one-stage 55%-to-100% recovery after ten healthy closes + removal of SPY rebound release. Cross-surface recovery retained.

Acceptance in every 5/10/15/20y window: absolute CAGR delta <= 0.25 pp/year, drawdown deterioration <= 1 pp, absolute multiple change <= 5%. Detailed JSON includes tail returns, underwater periods, turnover and crisis diagnostics. Historical screening precedes a separately reviewed production implementation.
