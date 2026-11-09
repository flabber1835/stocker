# P00 Sentinel: bounded entry and recovery grid

## Owner authorization and purpose

On 2026-11-08 the owner authorized the Sentinel grid after the completed
[extra-hold comparison](p00-recovery-hold-results.md). This is a new research
authority for the fixed class below. The earlier single-experiment restriction
remains the scope of that earlier result. Core selection, holdings, stops,
formation, accounting and input epoch remain fixed. The original twelve-arm
campaign and Control/VOL075 backtests remain stopped. No production, PAPER/LIVE,
broker action or deployment is authorized.

The audit found late owned-position protection, delayed rebounds, and weak
global drawdown improvement. It also found that Native's fast minimum age did
not bind after healthy confirmation in any observed P00 fast episode. Vary the
entry/recovery confirmations and defensive exposure, while keeping minimum
ages, signal lookbacks, other entry predicates and leadership rules fixed.

## Fixed complete factorial class

| Research control | Values | Original value |
|---|---|---|
| Extra post-Native recovery hold | enabled, disabled | enabled |
| Native fast consecutive healthy closes | 2, 3 | 3 |
| Native slow consecutive healthy closes | 3, 6 | 6 |
| Owned impairment entry confirmation closes | 1, 3, 5 | 5 |
| Owned impairment entry damaged breadth | 0.75, 0.88 | 0.88 |
| Owned impairment active exposure ceiling | 0.25, 0.55, 0.75 | 0.55 |

The complete cross-product contains 144 configurations. Include original P00
Sentinel and the previously verified no-extra-hold configuration as explicit
controls, rather than adding uncounted profiles. All remaining parent and Owned55
constants are unchanged, including fast/slow minimum ages 10/20, the healthy
triple (Core r20 > 0, damage <= 0.63, green >= 0.20), owned entry drawdown -0.10,
owned entry green 0.20, owned recovery eight healthy closes, and the independent
leadership 55% ceiling. Do not add parameters, ranges or a second sweep after
seeing results.

Use hash-bound AST transformations of the frozen controller source
`a67bb21df8df12f1e411bfc9a562eb62180df4e1fd6f9e94c1e845a9f0978fb5`.
Change each Native healthy-streak release predicate, counter saturation and
snapshot bound together. Give every research profile distinct Native and
CandidateA snapshot schemas. All other Native transitions stay fixed. Change
CandidateA's recovery gate only for hold-disabled profiles; keep its leadership
latch and ceiling. Configure the canonical owned-impairment module through the
existing research adapter. Require exact site counts, inverse AST restoration,
independent array equations, serialized controller continuation and actual
hosted canaries across the parameter boundaries.

## Selection locked before later-period reporting

Use 2018-01-02 through 2022-12-30 as the selection period. The selection function
receives only identifiers, common Core identity, target-path group, training
metrics and training turnover, never later-period scores.

Lock these candidates using exact same-period wealth multiples and drawdowns:

1. Protection candidate: smallest training maximum drawdown among configurations
   with training terminal wealth at least as high as **both controls**. Break
   ties by higher wealth, lower turnover, then deterministic profile ID.
2. Growth candidate: highest training terminal wealth among configurations with
   training maximum drawdown no deeper than **either control**. Break ties by
   smaller drawdown, lower turnover, then deterministic profile ID.
3. Growth leaders at training drawdown budgets 50%, 75% and 100% of original
   Sentinel's training drawdown. An unattainable budget produces no candidate.
4. Retain the exact training Pareto frontier, grouping identical exposure paths;
   neither a full-history leader nor a later-period leader can replace a locked
   candidate. Always retain both controls.

Report all 144 configurations, their path aliases, parameters and scores. Show
2018-2020 development and 2021-2022 stress blocks, then 2023-2024 validation and
2025-2026-07-31 latest diagnostics separately, plus full-history and annual
results. These dates have already been inspected: chronological separation is
useful historical validation, not a claim of unseen evidence. Do not select a
new winner from the later periods. Report both improvements and deterioration,
turnover, exposure changes and aligned original defensive-window returns and
drawdowns for the controls and all locked candidates/frontier paths.

## Reuse the admitted history and exact account

Use the completed original P00 admission
`65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83`,
checkpoint `352d3ad9c74d29d34faae0e07a1a592bc9b6921259a016298bd93e62c7188978`:
126 formation observations and 2,156 measured closes. Authenticate the whole
original encrypted artifact and preserve the original repairs, publications,
uncertainty qualifications and source epoch. Refuse unexpected certificate
scope. Execute no new Core transition or book formation.

Reuse the hosted full-system controller grid's independent vector equations,
dated canonical account-factor table, 28-digit value function, rational reviewer
and chained monthly continuation evidence. Its factor-dependency guard must
prove that current close target and prior NAV do not enter the current account
factor; each distinct date/allocation pair is computed by canonical
Account.advance and independently checked. This preserves same-publication BIL,
formed-entry costs, old exposure overnight, next-open actions and ten-basis-point
allocation turnover costs. It is not a weighted daily-return proxy.

Directly execute complete canonical accounts for both controls, every locked
candidate and every unique training-frontier path; require exact agreement with
the dated-factor value paths. The original control must reproduce every saved
target and account field. Both controls must also match the independently
admitted paired experiment's complete canonical-account record commitments,
after stripping only its recorded close-target field as DATA. Record these
reference commitments before the grid runs.

The reused grid driver needs actual registry-size metadata, an explicit pointer
to P00's existing `stopped-review/core-review.json`, and its checkpoint as the
common Core identity. Add optional arguments for those locations/identity while
preserving existing defaults; change no economic equation or readiness gate.
The reviewer must independently recompute all 144 paths, every dated factor,
training lock, metric, monthly value prefix and selected direct account.

All canonical calls, restores and real-input financial calculations run only in
credential-free, network-disabled GitHub containers over read-only sources.
Local qualification is DATA/AST and inert DTOs only. Keep long-only/unlevered
exposure in {0, 0.25, 0.55, 0.75, 1}; preserve UNKNOWN outcomes. Require actual
positive worker/reviewer stops and independent whole-artifact authentication
before admitting any result. A corrected failure needs a new source/request
generation, never a blind rerun.

## Delivery

Verified main is `2714afbb25fd169295358e035cefff59db2bf67d`, independently checked
by Git fetch and the connected GitHub app. The clean existing research feature
head `a0f446ff781319ba4c7375380ccf7265fc458686` contains it. Deliver through PR542,
pushing only `HEAD:refs/heads/codex/capital-risk-research`; never merge or push
main. Only the new source-bound grid request may start this new workflow.

## Local qualification

Forty targeted DATA/AST/DTO tests passed in 4.27 seconds under the canonical
import fence. They cover all eight required parent parameter/schema sites,
all five independent vector sites, all four Native confirmation pairs and both
hold settings, aligned counter saturation/snapshot bounds, retained minimum
ages/leadership ceiling, both training-only objective constraints, unattainable
budgets, later-period rejection, actual container constructors and unchanged
capacity/transport-root guards. Bypassing the training-date guard makes its
negative test fail, as required.

The source-bound request/import probe passed with 1,455 driver source files.
AST comparisons verified that the eleven reused controller/account/factor/value
and independent accounting functions are unchanged; the generic driver changes
only its optional source-review location/Core identity and registry metadata.
Hosted canaries, all baseline/control comparisons, the full grid, independent
review and whole-artifact admission remain required before any result.

Exact targeted pytest command, with `PYTHONPATH=research/capital_risk` and the
canonical-import fence installed:
`python -B -m pytest -q -p no:cacheprovider --basetemp=C:/GitHub/stocker/.codex-tmp/p00-sentinel-grid-tests-1 research/capital_risk/forecast_tests/test_p00_sentinel_grid.py`.
