# Three versus five exposure levels on a retained Wealth Core path

## Authorized scope and fixed input

The owner requested the five-level experiment while retaining the existing
fractional Wealth Core path. Use the authenticated 4,035-close snapshot from
2006-07-31 through 2022-08-09, binding
`b21a537f35de5a8aeee2303a97949dde5fe0a925516cd065fc133d4b823942ad`.
The stopped main backtest remains untouched. Do not rerun Core, form another
book, repair its data refusal, or alter production/broker behavior.

Core's holdings, entries, exits, cash, corporate actions, and opening/closing
equities are shared immutable inputs. Each controller has its own exposure,
T-bill allocation, overlay state, costs and account NAV. Candidate account NAV,
holdings or fills never feed Core or controller evidence. This is the existing
scalar overlay model, not a full broker execution simulation. A changed Core
rule would require a new tape; changing Sentinel's exposure policy does not.

No future returns are fabricated. When the separately authorized Core replay
eventually advances, new authenticated sessions can extend this same lineage
once. Each Sentinel candidate then replays or continues against that common
history; it does not regenerate its own Wealth Core history.
An extension must preserve the already-authenticated prefix. A required historical
data correction creates a new version and replays the affected Core segment once;
it must not silently splice incompatible histories or rebuild Core per controller.

Development extends PR #597 on `codex/fractional-exposure-oracle`, verified HEAD
`3681f8c5fd2733c318666854c98bee18fec83f1d`, based on current `origin/main`
`69b4a78a25610bf4aaee27eb4956a0611d26d124`. Delivery uses authenticated local Git
and the connected GitHub PR. No merge or installation is authorized here.

## What the retained evidence supports

The daily export preserves native severe allocation, champion recovery allocation
and reason, final owned-impairment allocation, and typed healthy/impaired flags.
Those flags and original controller stages depend on the immutable Core, not
candidate exposure. They are sufficient for the focused staged-control test
below. The export does not contain every raw breadth, acceleration or leadership
value; this experiment does not invent those values or claim to test all possible
five-level controllers. Original controller/accounting source hashes and the
recorded baseline are checked before use.

## Predeclared state machine and paired comparison

Retain all original native severe, confirmed impairment, divergence and recovery
decisions. Add two small causal latches, shared by both experimental grids:

1. An early-warning latch starts after 1 or 2 consecutive existing impaired
   predicates. It clears after 3 or 5 consecutive existing healthy predicates.
   While the original final target is 100%, this latch caps exposure. Original
   55% protection remains 55%; original severe protection remains zero.
2. During original native-full recovery wait (`FULL_RISK_HELD`, final target
   zero), allow a probe after 3 or 5 consecutive healthy closes within that wait.
   The probe persists through neutral closes, but resets on impairment, native
   severe protection or leaving recovery wait. Original full recovery retains
   its original certification; the probe does not invent a 100% release.

The five-level policy uses 75% for early warning and 25% for the recovery probe,
alongside original 0%, 55% and 100%. Its paired three-level policy uses 55% for
both added stages. For identical parameters, state transitions and intervention
dates must match exactly across grids: only the two output levels differ. Severe
native protection jumps directly to zero. Thus reductions need less confirming
evidence than a release, and partial recovery requires more evidence to enter
than to maintain. The latches start inactive at the first retained close; both
grids use the same seed and the original first funded deployment is fixed.

Predeclare fourteen staged configurations per grid: early-warning only (four
entry/release combinations), recovery-probe only (two confirmations), and both
(eight combinations). The recorded baseline is also a selectable fallback.
The fixed illustration, independent of fitting, uses early entry 1, warning
release 3 and recovery confirmation 3 with both stages enabled. Do not expand
this menu after inspecting holdout results.

## Chronological fitting and attribution

Use the retained start through the 2015-12-31 close for fitting. Separately for
each grid, select the highest after-cost training CAGR subject to training MaxDD
no worse than recorded Sentinel. Break exact ties by lower allocation turnover,
then fewer switches, then stable configuration ID. The baseline fallback is
always feasible. Persist the training table and selected configurations before
evaluating later returns.

Evaluate the frozen selections from the 2015-12-31 baseline through 2022-08-09.
Continue each candidate's own state and overnight position across the boundary;
do not reset or optimize on holdout returns. Also report the three-level version
of the selected five-level configuration and the five-level version of the
selected three-level configuration. These paired controls distinguish changes
in action granularity from different fitted transition settings. Report the two
fixed illustrations even if fitting selects the unchanged baseline.

The later history was inspected in prior research. It is excluded from this
fit, but is not an untouched research holdout. Report full-period diagnostics
separately from holdout evidence; 25–30% CAGR with no worse drawdown remains a
target to assess, not a result to force. No neural network or new market signal
is fitted in this experiment.

Preserve the original next-open accounting: the old exposure owns the preceding
overnight and the new exposure owns the intraday after a switch. Use the same
Core/BIL factors, 10-basis-point allocation-turnover cost and unchanged-exposure
branch. More intermediate levels do not automatically add proportional cost to
a monotonic exposure change; repeated reversals do. Reconcile paired performance
differences into gross timing and allocation costs, with stage occupancy,
turnover, switches, yearly returns and cumulative monthly CAGR/multiple/MaxDD.

## Evidence and checks

Keep the source snapshot mounted read-only and the new output separate. Bound
research containers to half a CPU and 1 GiB, no network, existing pinned Python
and report dependencies. Preserve immutable source identity before and after.
Do not invoke a Core transition while generating any candidate.

Targeted tests cover prefix invariance, strict source predicates, baseline-stage
composition, severe zero protection, latches, paired state identity, next-open
timing, first funding, fitting isolation and continued holdout ownership. Verify
guard tests with isolated mutations. Independently reconstruct candidate NAVs
from raw recorded opening/closing economics, and verify all reported daily and
monthly metrics. Export configurations, daily decisions, full and holdout paths,
training selection, costs, monthly data, and an offline report. Report proof
limits and observed failures without changing the predeclared experiment.

## Results — November 16, 2026

The experiment reused the existing snapshot. A runtime profile guard watched the
canonical `sentinel.core.kernel.advance_session` function throughout fitting,
evaluation, reporting and auditing: **zero calls**. The original stopped backtest
and its Core history were not changed. Local results are retained at
`.codex-tmp/sentinel-levels-20261116/run-001/`.

Both grids selected exactly the same transition settings: early warning after
two impaired closes, release after three healthy closes, recovery probe disabled.
The five-level menu therefore selected the added 75% state but did not select a
25% probe. The independently predeclared fixed configurations exercised both
additional stages and are reported separately.

Fitting through 2015-12-31 produced 16.8646% baseline CAGR, 16.8961% for the
selected three-level policy, and 16.8821% for five levels. Their respective
training MaxDDs were 21.8318%, 21.6331% and 21.7214%. The apparent improvements
were supported by only **three changed exposure days in one January 2008 episode**.

Later-period results use the 2015-12-31 close as baseline and 1,662 return sessions
from 2016-01-04 through 2022-08-09:

| Policy | CAGR | Multiple | MaxDD | Switches | Allocation turnover |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current Sentinel | 15.7491% | 2.6281 | 22.4010% | 13 | 8.70 |
| Selected staged three-level | 14.6121% | 2.4621 | 22.4010% | 17 | 10.50 |
| Selected staged five-level | 15.1233% | 2.5356 | 22.4010% | 18 | 9.70 |
| Fixed staged three-level | 13.1733% | 2.2650 | 22.4010% | 22 | 12.15 |
| Fixed staged five-level | 14.4777% | 2.4431 | 22.4010% | 25 | 10.45 |
| SPY | 13.2104% | 2.2699 | 33.7001% | — | — |

The selected five-level policy beats its matched three-level policy by 0.5112
CAGR percentage points, but trails current Sentinel by 0.6258 points. Five levels
soften the effect of an unsuccessful warning; they do not improve this controller
relative to the unchanged baseline. The selected settings, fixed controls and
training menu were not changed after seeing these later results.

### Mechanics

Both selected policies reduce exposure on the same 56 later-period sessions.
The three-level version uses 55%; the five-level version uses 75%. A short
three-session October/November 2016 episode helps slightly. Two 2020 episodes
dominate the harm:

- The August warning holds reduced exposure for **39 sessions**, through
  October 7, despite the original controller remaining fully invested.
- The November warning holds reduced exposure for **14 sessions**, through
  December 1, again while the original controller remains fully invested.

Two impaired closes latch the early reduction even when the original five-close
confirmation never activates during the changed interval. The new latch then
requires three consecutive healthy closes to release; neutral or improving but
not yet healthy observations keep it reduced. This misses subsequent gains.
Including each rejoin overnight, the baseline gains 12.80% and 6.82% across those
two episodes versus 9.20% and 6.08% for the 75% overlay. The worst portfolio
drawdown, February 12–March 8, 2021, remains untouched.

The selected five-level holdout loses 0.034818 gross log wealth and 0.001000 to
additional allocation costs relative to baseline. Most of the shortfall is
missed market participation, not trading cost. Compared with its three-level
pair, five levels gain 0.028601 gross log wealth and 0.000800 from lower costs.
They have one more switch but less notional turnover: moving 75% to an existing
55% ceiling creates a switch that a policy already at 55% does not need. State
transition dates match; actual order-changing dates need not be identical.

Full-period diagnostics including fitting years are 16.4034% CAGR for baseline,
15.9490% for selected three levels and 16.1538% for selected five levels, all at
22.4010% MaxDD. None reaches the earlier 25–30% target. The conclusion is limited
to this predeclared signal/state design; it does not prove every finer exposure
policy is inferior. The evidence does not support adopting these added stages.

### Validation and retained artifacts

- `python -B -m pytest tests/sentinel/test_exposure_levels.py tests/sentinel/test_exposure_logic.py tests/sentinel/test_exposure_oracle.py -q -p no:cacheprovider`:
  **66 passed**.
- `python -B -m research.exposure_oracle.levels_audit --snapshot /snapshot --result /output/run-001`:
  **PASS**; independent state/return reconstruction for all 29 training candidates,
  all seven reported controller paths, 28,238 daily returns and 2,184 monthly
  series rows. Paired controls intentionally duplicate the selected paths when
  both grids choose the same settings.
- Seven isolated mutations trigger expected failures: source predicate typing,
  training endpoint, healthy release confirmation, probe persistence, drawdown
  eligibility, next-open alignment and fixed first funding. Source files remain
  unchanged.
- Report QA verifies all 193 full-history and 80 holdout displayed monthly rows,
  all eleven chart traces and 29 training rows, plus syntax and source hashes.
  Browser visual inspection was unavailable; no interactive visual check is claimed.
- The protected backtest's identity, checkpoint and committed daily prefix still
  match the retained snapshot. Its original stopped/refused state is unchanged.
- `selection.json` SHA256:
  `8033826c2befc6c31db99cbd2a07ddc864053704e422b0b017bd4b1ff28f4fbb`.
- `paths.json` SHA256:
  `dc746761ea9787f222a519e56cea0a6b830f04e9c232a13313f51cf84755c84d`.
- `holdout-paths.json` SHA256:
  `68f0e74a5da101cedebb0002f9b9f65da5a7c0232e5628e1ebcdbe125f95a40d`.

The offline report includes 193 full-history and 80 holdout monthly rows for
current Sentinel, both selected policies and SPY. JSON also retains all paired
and fixed controls, daily states, yearly returns, timing/cost attribution and
the independent audit. `mechanics.json` retains the separately reconciled
changed-episode analysis, and `core-preservation.json` records the runtime guard.
