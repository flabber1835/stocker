# Simplification round 2 — ten additional full-PIT starts

Preregistered 2026-09-10 under the user's instruction to store the simplified code and run the next experiments with ten slots. The repeated instruction is one authorization: **10 additional starts**, giving a total ceiling of 21 across all three rounds. Tracking issue #349; research PR #350. Scope is research.

## Frozen reference and stored code

The reference is the completed coherent candidate from run 34441488484, head 8d03d04c0787ddd9b1bed7ecef58183f22288a47. Its standalone source is stored in `../wealth-core-v5-ex3-v6-simplification-v1/simplified_candidate.py`, SHA256 `26b99f4a5f7fefc9d295479cc604e85a761db64cc5416664145fdd1b94b72939`. The adjacent manifest preserves exact metrics and provenance. The source file was verified against the completed job's generated-source identity before publication.

Reference composition: selective peers + bounded counters + ten-healthy-close single-stage recovery + removal of SPY rebound release; cross-surface recovery retained. 20y CAGR 21.833176632696083%, max DD -27.35619982948002%, multiple 51.92142251352529. This candidate's original-V5/V6 preservation-screen failure remains recorded.

Dataset SHA256 `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`; the full-PIT universe, frozen runtime, costs, next-open timing, dividend lag, price domains and 5,032-session measurement horizon remain identical to round 1. All Core source and economic invariants remain fixed.

## Ten-arm matrix, fixed before results

| Slot | Arm | Change from the stored candidate | Claim |
|---:|---|---|---|
| 1 | baseline | Fresh replay of exact stored source | Byte-identical reference qualification |
| 2 | cleanup_state | Remove obsolete Native ramp stage index and 65% branches; remove inactive CandidateA rebound variable/branches | Exact decisions, reason and NAV paths |
| 3 | symmetric_peers | Compute a held pair's correlation once per close and reuse its reverse lookup | Exact breadth, decisions and NAV; reduced work |
| 4 | clean_cached | Combine cleanup_state and symmetric_peers | Exact combined parity |
| 5 | no_peers | Replace peer damage by individual DD/R21 damage | Eliminate the peer sensor dependency |
| 6 | fixed_ramp10 | Always enter the ten-close 55% ramp after severe recovery; delete the fragility shortcut and its six-value R40 history | Remove recovery branch and memory |
| 7 | persistence_only | Remove cross-surface release and its positive-streak state; use existing full-health REC8 confirmation | Remove one release route and counter |
| 8 | no_peers_fixed_ramp | no_peers + fixed_ramp10 | Test interaction of breadth and fragility removal |
| 9 | no_peers_persistence | no_peers + persistence_only | Test interaction of breadth and release simplification |
| 10 | minimal_recovery | no_peers + fixed_ramp10 + persistence_only | Test the largest specified reduction |

All treatment arms start from the same stored candidate. Arms 5–10 also receive the parity-preserving cleanup so their stored generated sources reflect the simpler state. Native ordinary/fast/slow causes, rearm and dwell rules remain intact. Divergence entry/latch and the native exposure ceiling remain intact.

Correlation caching is local to a single breadth calculation. It caches the first evaluated orientation, preserving the held-id tie ordering and the correlation arithmetic for that first evaluation. Tests must prove reverse-orientation equality including unavailable histories, constants and the .145 threshold. Missing or tied correlations must not change neighborhood selection. The cache cannot span sessions or corpora.

The fixed-ramp arm retains the original prior-close checkpoint timing and healthy/reset rules. The persistence-only arm retains the original R20 > 0, R40 > -4%, REC8 rule and its role in clearing the divergence latch. These arms remove whole dependencies; they do not tune thresholds.

## Preflight and replay gates

Before a slot claim: verify generated sources and their controller-only AST scope; compile all ten arms; exercise boundary, missing-data, seeded state, restart and peer-differential falsifiers. Every changed guard receives a falsifier. Exact arms must also match the fresh reference's allocation, NAV, reason and native paths in full PIT.

The reference artifact is downloaded from run 34441488484 and verified against its checksums, generated source hash, run/head identity and Core hashes. The fresh baseline requires byte-identical daily, transaction and close-decision tapes to that artifact. Only a validated baseline unlocks the other nine arms.

Every arm must reproduce the original fixed Core economic hash, transaction hash and close-decision hash. Sensor changes may alter damaged breadth; all original Core economic fields remain exact. Non-breadth-changing arms also require the full original Core/sensor tape hash.

## Two economic comparisons

Report separate preservation flags against (a) the stored simplified candidate and (b) the original V5/V6 `r40_m04_rec8` baseline from run 34436432038. Keep each comparator's actual source identity. Each flag requires every trailing 5/10/15/20y window to satisfy: absolute CAGR difference <= 0.25 pp/year, max-DD deterioration <= 1 pp and absolute terminal-multiple change <= 5%.

A pass against the simplified candidate does not establish preservation of original V5/V6. The candidate's existing original-screen failure is retained. Exact engineering arms can prove decision parity while inheriting that original-screen status. No thresholds will be relaxed after outcomes. Report original-preserving only where the original comparison passes.

Report path divergence, changed allocations, longest underwater spell, tail return, turnover, transitions, peer work counts and fixed crisis windows alongside window metrics. Selection favors mechanism reduction subject to the explicit evidence; the maximum CAGR is not a selection rule. Production hardening and promotion remain separate decisions.

## Budget and documentation

A unique permanent ref `refs/heads/research-budget/simplification-v2/slot-01` through `slot-10` is claimed immediately before each full replay. A failed start remains charged. Duplicate claims fail closed. Original 10 + follow-up 1 claims remain unchanged. This workflow performs no automatic replay retries.

Dedicated trigger: this directory's LAUNCH.json. Run baseline first and nine treatments in parallel after it passes. Per-arm source, driver, identity, slot claim, logs, tapes, diagnostics and SHA256 checksums are retained as 90-day Actions artifacts. Final complete or incomplete outcomes and both comparator tables are posted to #349. Generated source snapshots and compact final reports are committed to the research branch automatically after aggregation. A failed aggregate publication is reported as a documentation failure.
