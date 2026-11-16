# Target CAGR with minimal changes to Sentinel

The owner set a research goal of 25–30% CAGR and selected two constraints:
maximum drawdown no worse than current Sentinel over the same period, and
switching decisions as close as possible to current Sentinel. On November 16
the owner explicitly deferred repairing the stopped main backtest. Leave its
source, checkpoints and output unchanged. Use its completed, authenticated
2006-07-31 through 2022-08-09 prefix (4,035 closes) for this experiment; the
incomplete twenty-year replay is not the study period.

Develop on the existing research PR #597, whose base is current verified main
`69b4a78a25610bf4aaee27eb4956a0611d26d124`. No production or broker change.
Use the canonical fractional Core return path, BIL sleeve, modeled 10-basis-point
allocation turnover costs and next-open convention. Copy only authenticated
committed data to a new immutable snapshot. First funded deployment stays fixed.

## Objective and search

Select one of 0%, 55%, or 100% for every trading session. A decision at close t
acts at the following open; its preceding overnight belongs to the old holding.
Find a final CAGR in [25%,30%], with daily-close MaxDD at most recorded
Sentinel's MaxDD on this same prefix. This is a target band, not a request to
maximize CAGR beyond 30% or to reproduce the unconstrained daily oracle.

Define closeness lexicographically:

1. Minimize the number of return sessions whose applied exposure differs from
   Sentinel's corresponding prior-close decision.
2. Among those paths, minimize total absolute exposure deviation, in percentage
   points summed across sessions.
3. Among ties, minimize the number of exposure switches.

This counts changed decisions, not calendar distance from an existing switch.
An isolated one-day change still counts as one changed decision even if it
requires an exit and re-entry. Report fragmentation and turnover explicitly;
closeness does not establish predictability or operational simplicity.

Reuse the exact three-action transition equation. For efficiency first compute
the maximum possible log growth for every exact changed-day budget and ending
action using dynamic programming without a drawdown constraint. The first budget
that can reach 25% gives a rigorous lower bound for the constrained objective.
Independently replay its path and check the full CAGR band and drawdown. Do not
claim that ignoring drawdown establishes feasibility.

At a proposed changed-day budget, forward/backward dynamic programs provide an
upper growth bound through each transition. Exclude a transition only if even
that bound cannot reach the lower CAGR target. Preserve a numerical margin so
roundoff cannot prune a borderline feasible path. Search the retained network
with mixed-integer linear programming: binary transition flows, cumulative log
wealth and monotone log peaks. Constraints enforce initial state, path continuity,
exact changed-day count, terminal log-wealth band, and log drawdown at every close.
Minimize deviation, then fix the proved deviation and minimize switches. If a
budget is infeasible, examine the next budget. Never infer infeasibility from a
time limit or absence of a solver incumbent.

Record dynamic-program bounds, solver statuses, primal/dual bounds and remaining
optimality gaps. A resource-limited feasible result is only best-found at the
unproved objective level. Independently replay every reported path in Decimal,
including its band, drawdown, changed days, deviations and switches. Reject a
numerically invalid returned path rather than relaxing the economic conditions.
Preserve the existing exact-accounting tolerances and the exact target bounds;
an interior margin must not exclude a closest solution on the band boundary.

Use the already isolated SciPy 1.16.3/HiGHS research dependency, one solver/BLAS
thread, at most half a CPU and a bounded memory/time envelope. Preserve intermediate
results and bounds for continuation. The production image remains unchanged.
See [SciPy milp](https://docs.scipy.org/doc/scipy-1.16.3/reference/generated/scipy.optimize.milp.html)
for solver status semantics. Test tiny cases against exhaustive enumeration and
verify that transition pruning never removes a feasible optimum.

The evidence audit separately reconstructs returns directly from the recorded
economic fields without importing the search or accounting implementation. It
checks every Decimal NAV and monthly metric, independently recomputes the growth
budget bounds, and, when the retained network is small, exhaustively enumerates
its complete paths to verify all three objective levels. Enumeration has an
explicit resource limit; hitting it must not silently turn into beam search.

## Signal analysis

For every changed decision, inspect what was known at the preceding close:
native fast/slow signals and active states; ordinary/base-fast stress memory;
owned healthy/impaired predicates and confirmation counters; and the recovery
stage's actual reason and desired allocation. These are recorded production
signals, not predictions reconstructed from the hindsight labels. Identify
earlier exit, earlier recovery, avoided false exit, and reduced overshoot only
where the actual stage evidence supports that interpretation. Reconcile added
growth into market timing and costs, by contiguous change episode and calendar
period; show concentration rather than attributing results to stock names.

Compare changed-day signal prevalence with unchanged days under the same actual
exposure state. A common signal that also fires on many harmful days does not
identify a useful switch. Report false positives, recall, base rates, proximity
to actual transitions, length of changed runs and turnover. Inspect existing
signals first before considering new ones. The daily export contains boolean
signals/state but not all raw breadth/recent-leadership values. Missing values
in this export are an evidence-availability limitation, not proof that production
lacks those signals. Use matching authenticated checkpoint observations when
available; any further raw-signal replay must remain separate and preserve the
main backtest.

Any predictive model or fitted threshold must generate its training oracle labels
within its own chronological training period. Do not train on a slice of the
full-period optimum: it may depend on test-period returns. Candidate causal rules
must be evaluated on all eligible days, with the same costs and next-open timing,
including their false signals. Clearly separate hindsight explanation, same-sample
causal diagnostics and chronological validation. Additional signals or architecture
changes remain hypotheses until they earn later-period evidence.

For this first diagnostic, evaluate a fixed, small menu of overrides: reduce full
exposure on the existing owned-impaired predicate, ordinary-stress state, or
absence of the existing healthy predicate; raise zero exposure on the existing
healthy predicate or the recovery-wait state. Test each at the two possible
alternative actions. Apply each predicate every eligible close, preserve the
first deployment, and account for resulting costs and overnight holdings. These
are same-sample causal rule diagnostics, not trained policies or out-of-sample
results. A disagreement with the selected sparse oracle is a label false positive,
not necessarily a money-losing decision; report actual economic performance too.
Group contiguous changed decisions into episodes and include their following
rejoin session when attributing wealth, because the changed position owns that
overnight. Report matched-state signal prevalence and chronological blocks without
claiming that inspecting the full-period oracle leaves those blocks untouched.

Retain the snapshot, path, solver bounds, per-decision/episode diagnostics,
monthly CAGR/multiple/MaxDD for target policy, Sentinel and SPY, and an offline
report. The conclusion must state whether the target is hindsight-feasible,
how many existing decisions must change, whether their timing is identifiable
from current signals, and which remaining information gaps matter. Reaching the
target in hindsight does not establish a causal strategy capable of that CAGR.

## Completed experiment — November 16, 2026

The selected path meets the lower end of the requested band after costs. The
objective prefers fewer changes, so it does not spend more changes reaching 30%.

| Policy | CAGR | Multiple | MaxDD | Switches |
| --- | ---: | ---: | ---: | ---: |
| Current Sentinel | 16.4034% | 11.4051 | 22.4010% | 25 |
| Closest hindsight target | 25.0010% | 35.7304 | 20.6137% | 63 |
| SPY | 9.6964% | 4.4064 | 55.2019% | — |

Twenty-two of 4,034 applied decisions change (0.545%). With only 21 changes,
even the unconstrained maximum-growth path reaches at most 24.6917% CAGR.
The 22-change optimum also minimizes total deviation at 2,200 percentage-point
days and switches at 63. Both MILPs terminate optimally with zero gap. A separate
multiplicative dynamic program and exhaustive audit find six admissible complete
22-change paths in the growth-pruned network and confirm all three objective
levels. No production or main-backtest source/output was modified.

The required behavior is 20 changed decisions from 100% to 0% and two from 0%
to 100%; no 55% decisions change. There are 21 changed episodes: twenty last one
session and one lasts two. Only six changed decisions are within five sessions
of an actual switch. The target retains all 269 recovery-wait decisions. About
92% of the extra log wealth comes from timing around actual full-exposure periods;
the rest comes from two brief entries while native severe protection is active.
This objective predominantly asks for short-horizon loss avoidance, not simply
shorter waits before a sustained recovery.

The selected path adds 1.179962 gross log wealth and loses 0.038019 to additional
allocation costs, for 1.141943 net log wealth and a 3.13285-fold improvement over
the baseline final wealth. Episodes include the next rejoin overnight in this
attribution. The benefit is concentrated: the 2020–August 2022 block has 23.11%
actual CAGR versus 60.55% for the hindsight target. The target band applies to the
whole period, not every year or block.

The existing final predicates do not identify the required rare days precisely:

- Ten of the 20 ideal exits were classified healthy at their decision close.
  Their same combined boolean state also appears on 2,075 unchanged full-exposure
  days. Absence of a warning is not evidence of a safe next session.
- Only two ideal exits satisfy owned impairment. Acting on that predicate at
  every eligible full-exposure close changes 19 decisions, including 17 outside
  the selected sparse oracle. The full-exit version returns 16.0978% CAGR; the
  partial 55% version returns 16.2786%, both below baseline.
- Ordinary stress catches two ideal exits but acts on 204 decisions. Its 55%
  version returns 15.0161% CAGR with 22.8133% MaxDD.
- Exiting whenever health is absent catches ten ideal exits but acts on 901
  decisions; its 55% version returns 12.3682% CAGR.
- The existing healthy predicate does not identify either brief ideal re-entry.
  Applying a 55% early-recovery override on all 207 eligible closes returns
  15.6335% CAGR. A 55% bridge on all recovery-wait days returns 14.6833% with
  25.3141% MaxDD.

All ten fixed predicate/action diagnostics reduce CAGR. Label disagreements are
not individually classified as economic losses; full-path economics incorporate
their benefit, harm, costs and overnight exposure. These results do not rule out
better continuous thresholds, combinations or different hindsight paths with
more changed decisions. They do rule out interpreting this 22-day optimum as an
already-discovered simple exit/recovery setting.

The next useful evidence would be a separate, authenticated daily export of the
existing continuous breadth, return, volatility-acceleration and recent-leadership
inputs. Fast protection already uses several of these; adding a second volatility
input without first testing the existing one is not justified. Study their ability
to discriminate brief losses at matched exposure states, fit only within bounded
chronological training periods, and measure all false alarms after costs. The
current evidence neither establishes the need for new market inputs nor supports
replacing Sentinel with a neural network.

### Evidence and validation

Local evidence: `.codex-tmp/sentinel-target-cagr-20261116/run-004/`.
`report.html` contains all 193 cumulative monthly rows for current Sentinel,
the target, and SPY, alongside the complete changed-decision table. `monthly.json`,
`signal-analysis.json`, `solver.json`, `budget-bounds.json`, `paths.json`, and
`audit.json` retain the machine-readable evidence and hashes. Earlier runs are
retained; run-004 uses the exact target boundaries and the final research source.

- Source binding: `b21a537f35de5a8aeee2303a97949dde5fe0a925516cd065fc133d4b823942ad`.
- Paths SHA256: `430b7eaa33650470ba990a6384097d996896112d54d0aa14bde5203f48b0f1f2`.
- Monthly SHA256: `a6576bc3a3bf28de0036544a9f29932fb930113d11e2ba21bb24036026cf2bba`.
- `python -B -m pytest tests/sentinel/test_exposure_target.py tests/sentinel/test_exposure_target_analysis.py tests/sentinel/test_exposure_oracle.py -q -p no:cacheprovider`:
  **52 passed**. Includes exhaustive synthetic comparisons, boundary cases,
  source/output separation, signal timing, fixed deployment and rejoin attribution.
- `python -B -m research.exposure_oracle.target_audit --snapshot /snapshot --result /output/run-004`:
  **PASS**; 8,068 independently reconstructed Decimal return rows, 193 monthly
  rows across three series, and exhaustive objective confirmation (peak 64 labels).
- Six isolated guard mutations produce their expected test failures: accepting an
  invalid solver path, tightening away a target-boundary solution, using the
  outcome close's signal, changing fixed deployment, omitting the rejoin overnight,
  and ignoring the exhaustive-audit resource limit. Source files remain intact.
- Report verification compares all 193 displayed monthly rows to audited data,
  checks all eight chart traces and 22 changed-decision rows, and verifies that
  unproved solver objectives are labeled best-found. Syntax and run-source hashes
  pass. A browser was unavailable, so no interactive visual inspection is claimed.
- The protected run remains stopped at its original refusal. Its committed daily
  prefix, checkpoint and identity still match the experiment's authenticated copy.

Runtime uses the existing pinned Python 3.12 image, isolated SciPy 1.16.3 and
Plotly 6.5.0, no network, read-only source/input mounts, half a CPU and 1 GiB RAM.
