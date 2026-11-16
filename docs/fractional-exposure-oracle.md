# Fractional Core hindsight exposure experiment

## Purpose and boundary

The owner requested a separate daily hindsight search on the fractional Wealth
Core path already running locally. Show the CAGR/maximum-drawdown trade-off and
highlight maximum CAGR subject to the actual Sentinel path's drawdown. The
running replay, its source, processes, checkpoints and output remain untouched.
This experiment changes neither Wealth Core nor Sentinel nor broker execution.
The Core/BIL return tape is fixed; only the modeled exposure path changes.

The oracle intentionally knows the entire selected future. Its result is an
upper benchmark within its declared exposure grid, not an attainable forecast,
a causal trading rule, or evidence that Sentinel could have known those choices.
Historical input corrections and research limitations remain inherited.

## Authenticated input and periods

Read one atomically published checkpoint pointer, authenticate its compressed
bytes and binding against identity.json, and copy only its committed daily.jsonl
prefix into a separate experiment directory. Verify length, SHA256, last session,
measurement count, chronological uniqueness and the exchange-session schedule.
Retain the checkpoint, identity and source prefix with an experiment manifest.
Never restore, truncate, repair or write to the running replay. Subsequent runs
can take a newer snapshot without changing an existing experiment.

Accept arbitrary start/end sessions within that immutable prefix. Rebase all
paths to one at the first selected close, with maximum drawdown reset there.
Carry Sentinel's actual held exposure at that close into the first overnight.
If the selected period includes the original cash-only baseline, preserve the
first funded-open deployment exactly; optimize subsequent opens. This avoids
inventing the funded-entry composition from a summary tape. No terminal
liquidation is added. Periods need at least two closes and never extrapolate
beyond completed source data.

## Economics and allowed actions

Use recorded, fully resolved Core opening/closing equity and recorded BIL
adjusted opening/closing/previous prices. Keep the original close-to-next-open
decision timing: yesterday's holding receives the overnight move; the new
exposure applies after today's open. The oracle knows future returns but does
not gain an additional close or intraday trading opportunity.

Preserve the production scalar accountant's two branches. Unchanged exposure
uses the weighted full-session Core/BIL factors. A changed exposure uses the
old exposure overnight, the new exposure intraday, and the retained factor
`1 - 0.001 * abs(new - old)`. Internal Core trading costs already belong to its
fixed returns. The first funded-open factor is replayed unchanged. Validate
every actual transition against recorded economics and the canonical scalar
accountant before searching. Bind the relevant production accountant sources.

The owner clarified that the only actions are **0%, 55%, and 100%**. Search
switch timing among exactly those three states; do not add intermediate
exposures or a finer grid. Reject an actual input path using any other state,
so it cannot silently enter a different comparison universe. The action set
is long-only and unlevered. Optimality applies to this finite action set and
floating-point tolerance, not to continuous allocations.

## Search and correctness

Precompute each day's log net factor for every previous/current exposure pair.
Maximizing final log wealth also maximizes CAGR for a fixed period. Solve the
unconstrained path by dynamic programming with previous exposure as its state.

For a drawdown cap D, a second state is current log drawdown from the running
peak: `z_next = max(0, z - log_factor)`, bounded by `-log(1-D)`. Retain all
nondominated labels for each ending exposure: one label dominates another if
its accumulated log wealth is at least as high and its current drawdown is no
greater. Future factors depend only on exposure and date, so such a label can
never improve a continuation. Do not quantize drawdown or use a beam and call
it exact. Backpointers reconstruct the selected path. Explicit state/resource
limits refuse an unfinished search; they never silently discard live labels.

A feasibility recurrence keeping the smallest reachable current drawdown per
exposure determines feasibility for a cap. Bisection brackets the smallest
feasible maximum drawdown. Sample caps between this floor and the unconstrained
path's drawdown, plus the actual Sentinel cap. If the unconstrained optimum is
already inside a cap, it is also that cap's optimum. Keep feasible/infeasible
statuses, numerical tolerances, frontier dominance and search counts visible.

Validate optimized paths independently in Decimal, enforcing the requested cap
and allocation bounds. Exhaustive short synthetic histories must agree with
unconstrained, constrained and feasibility dynamic programs, including costs,
overnight gaps, unchanged-exposure accounting, dominated-label pruning, boundary
drawdowns and first deployment. Verify the actual path is feasible in its own
cap and cannot beat the selected oracle on an action grid containing its path.
Guard-removal falsifiers cover provenance and the drawdown/action boundaries.

## Comparison and output

Emit machine-readable daily decision/held exposures, NAV, drawdown and log-growth
differences; monthly metrics; a frontier; period summaries; and a standalone
HTML report with the trade-off curve and exposure/wealth/drawdown charts. Show
actual Sentinel, the selected oracle, always-Core and always-BIL reference paths
under the same boundary convention. Distinguish decisions at the preceding
close from exposure applied at the following open.

Attribute the exact final log-wealth gap to gross-return selection and overlay
costs, then group it by the recorded executed native, recovery and owned
protection components, final restricting layer, year and contiguous defensive
episodes. Native-full is not final-full while the recovery gate still holds
exposure at zero. Retain both overnight and new opening exposures: equal new
exposures can still have different overnight returns. Compare entry/re-entry timing, protection on
falling days, exposure withheld on rising days, turnover and intermediate
time at 55%. Explain mechanisms from these records, without attributing
unobservable knowledge or treating individual stock returns as a diagnosis.

## Delivery and execution

Develop from verified main `69b4a78a25610bf4aaee27eb4956a0611d26d124` on
`codex/fractional-exposure-oracle`; use authenticated git and a separate GitHub
PR targeting main. Research code, focused tests and this design are the only
planned repository changes. Run offline in a separate resource-limited local
container, mounting source and the active replay read-only and only the new
experiment directory writable. The protected replay keeps running throughout.
Plotly is a separately pinned report-only dependency for self-contained,
zoomable charts. It does not participate in the optimizer or production runtime.

## Retained local result

The first immutable snapshot contains 3,200 closes, 2006-07-31 through
2019-04-16 (3,199 return sessions), from source binding
`163f3a826449fe4b6e72a481814643f3875d4ce230bc36c03397447b70134651`
and checkpoint
`checkpoint-c68548da9c469f6d59df584434816d47754eba9c759b1d3708e7c65f1b2ec002.json.gz`.
The main replay subsequently reported an unresolved-valuation refusal on
2019-04-17; this experiment did not stop or modify that process.

| Path | CAGR | Wealth multiple | Maximum drawdown | Exposure changes |
|---|---:|---:|---:|---:|
| Actual Sentinel | 14.7286% | 5.73309 | 21.8318% | 18 |
| Hindsight optimum at Sentinel's cap | 189.5736% | 739032.77819 | 4.7862% | 1342 |
| Hindsight path with 1.0507% cap | 188.4440% | see retained frontier | 1.0133% | 1359 |

The actual drawdown cap is nonbinding: the unconstrained maximum-growth path
already fits within it. This path uses 1,778 full-exposure and 1,421 zero-exposure
sessions, and no 55% sessions. Actual Sentinel uses 2,543 full, 598 zero and 58
55% sessions. The stricter 1.0507% cap introduces 22 sessions at 55%; at the
minimum feasible drawdown near 0.303655%, the best path uses 55% for 166 sessions.
Partial exposure therefore still has a role under a tighter hindsight risk cap.

The log-wealth advantage decomposes into 13.094708 from gross return selection
and -1.327865 from extra overlay costs, totaling 11.766843. Grouping by the
actual controlling state attributes 72.57% of that additive gap to sessions at
full exposure, 17.30% to native severe protection, 8.20% to recovery holds, and
1.93% to the owned 55% ceiling. These are path-gap attributions, not estimates
of the benefit from deleting a gate. In particular, 214 zero-exposure sessions
occur after native exposure is full but before the recovery gate releases.

The dominant oracle advantage is frequent daily loss avoidance, not merely
retiming a handful of regime switches. Recovery persistence is a separately
identifiable review target. For example, actual exposure stays at zero for 93
sessions from 2010-05-10 through 2010-09-20; the oracle switches within that
interval, spending 48 sessions at full exposure and 45 at zero. This is not
evidence that uninterrupted early re-entry would reproduce the oracle.

`python -B -m pytest tests/sentinel/test_exposure_oracle.py -q -p no:cacheprovider`
reports **34 passed** in the pinned Python 3.12 image. Removing the drawdown,
three-action and committed-prefix guards in isolated processes makes all three
selected falsifiers fail. The real-data run independently reproduces every
ordinary actual transition with the canonical accountant, validates optimized
paths in Decimal, reconciles attribution, and verifies monotonic optimal CAGR
as caps relax. The initial deployment remains authenticated and fixed rather
than reconstructed. Both completed analysis runs retain the same path hash:
`47b680eb22157df858a2f3aa04e2965bcdd0f01593b471e58775f1b75065cf2a`.
The second report distinguishes native, recovery and owned-protection reasons.
