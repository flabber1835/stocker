# Structured controller search on the retained fractional Core

## Decision and boundary — 2026-11-16, before implementation

The owner authorized the structured research programme proposed in chat: broad
bounded exploration, chronological selection, comparison after costs, and tests
of whether an improvement has a repeatable mechanism. This implements the first
batch, not a production replacement or a promise of a profitable champion.

Continue PR #597, branch `codex/fractional-exposure-oracle`, from
`9e9bfc09ceb19d822a05ba0a38e8c8106d35fb81`; fetched authoritative main is
`69b4a78a25610bf4aaee27eb4956a0611d26d124`, an ancestor of that clean branch.
Delivery is authenticated local Git plus the connected GitHub PR. No merge,
installation, broker operation, Core modification or stopped-backtest repair is
authorized. Use the same authenticated 4,035-close snapshot, 2006-07-31 through
2022-08-09, binding
`b21a537f35de5a8aeee2303a97949dde5fe0a925516cd065fc133d4b823942ad`.

Core ownership/economics are immutable common inputs. Each candidate owns only
its exposure, controller memory, T-bill allocation and modeled account NAV. The
existing next-open scalar accountant remains the economic contract, including
old exposure owning the overnight, the unchanged-allocation branch, first
funding and ten basis points per unit allocation turnover. This is not a broker
fill replay. No candidate account value or execution outcome is a feature.

The retained export has Core/SPY prices, Core cash/position count, healthy and
impaired predicates, native severe state and recorded controller decisions. It
does not have all raw historical breadth, acceleration or leadership features.
Use the available causal observations without inventing missing series. Broad
signal acquisition is a later experiment, not a reason to rebuild Core for every
candidate. No canonical Core transition may run in this experiment.

## Frozen first search batch

Seed 1729 generates 144 distinct configurations in each of four families: 576
in total. Persist the complete menu and protocol before evaluating a candidate.
There is no adaptive expansion after results are observed. All actions are
0/55/100 percent, unlevered and long only; before feature warmup use recorded
Sentinel. Constant Core, recorded Sentinel and a fixed simple trend rule are
separate controls, not hidden additional optimized trials.

1. **State:** retain native severe protection, replace owned-warning entry and
   release periods, optionally expire warnings, and allow earlier partial/full
   recovery when current healthy/return evidence confirms it. Entries 1/2/3/5/8
   impaired closes, releases 1/3/5/8/13 healthy closes, warning expiry
   0(disabled)/5/10/21/42/84, recovery confirmation 1/3/5/8 and recovery timeout
   0(disabled)/5/10/21/42. The recorded champion remains an input, not mutable
   candidate state. Timeout requires positive Core five-session momentum;
   early full recovery additionally requires positive twenty-session momentum.
2. **Trend/risk:** Core, SPY or their equal blend; momentum 5/20/63 sessions,
   trailing drawdown 20/63, negative-momentum and drawdown severe thresholds,
   and volatility warning/severe thresholds. Exposure changes require separate
   entry/release confirmation periods and a minimum intended-state duration.
   This family can replace the native controller; it does not inherit its
   severe protection. That is a research hypothesis, not changed safety policy.
3. **Predictive:** 48 ridge, 48 small regression-tree, and 48 small neural
   configurations. Predict mean excess log return and adverse cumulative excess
   return over 5/10/21 sessions, starting at the next open. No oracle labels.
   Price-only, price-plus-Core-health, and complete available-feature subsets
   test information content. Training-only standardization applies to inputs
   and targets. A fixed risk penalty and two score thresholds map forecasts to
   0/55/100, with confirmation/duration constraints. Models are bounded: ridge
   regularization, trees depth 2–5 with at least 25 observations per leaf, or a
   single tanh hidden layer of 8/16 units, fixed 120 training epochs. No random
   train/test shuffle or neural validation early stopping.
4. **Combination:** preselected state/trend/predictive members combined by
   minimum, median or rounded mean vote. No future performance weighting. This
   tests complementary information without inventing another holdings book.

Feature calculations at close t use observations through t only. The future
label covers intraday t+1 and subsequent complete sessions through t+h, so the
first overnight is not attributed to an action unavailable before t+1 open.
Training examples are admitted only when t+h is at or before the training
cutoff. Thus overlapping labels are purged at every training boundary.

## Nested chronological selection

Five outer blocks: 2013–2014, 2015–2016, 2017–2018, 2019–2020 and 2021 through
the retained endpoint. Each has the immediately preceding three calendar years
as inner validation. Predictive models train on earlier history ending before
that validation; parameters/architecture are chosen only from validation.

For each family and for the overall selector, choose maximum validation CAGR
subject to validation MaxDD no worse than recorded Sentinel in that same window.
Ties favor lower turnover, fewer switches, then stable candidate ID. Recorded
Sentinel is always an eligible fallback. Save and hash the selection before
outer evaluation. Refit learned models on all then-available history (with
label purging), then freeze them throughout the two-year outer block.

At each policy replacement, its intended controller memory is deterministically
primed from prior observations using the newly frozen parameters/model. That
memory is a function of information available at the replacement close; prior
simulated accounts are not spliced. Actual modeled overnight exposure and NAV
carry continuously between outer blocks. All candidates share recorded exposure
before the first outer baseline; the first outer overnight therefore has the
same known owner. A close decision always applies at the following open.

Save every candidate's outer path as a diagnostic of the declared search space;
do not retrospectively select the best complete outer path. The primary object
is the predeclared chronological selector. Family selectors are secondary
comparisons. The full candidate matrix supports multiplicity/neighbor analysis,
not a second round of selection. Persist training boundaries, fitted scalers,
model arrays, failures/warnings, selections, daily exposures/returns and monthly
CAGR/multiple/MaxDD. Model exports are JSON arrays, never executable pickle.

The complete historical period has been inspected in earlier research. These
are chronological model holdouts, not pristine research holdouts. The incumbent
also carries earlier research selection. A new split cannot erase that history;
forward observations are required for stronger confirmation.

## Predeclared assessment and falsifiers

The target remains 25–30% CAGR with drawdown no worse than Sentinel. A provisional
research improvement must have higher pooled outer CAGR, no greater outer MaxDD,
positive incremental log wealth in at least three of five blocks, and positive
incremental wealth after subtracting its best contiguous difference episode.
It must also keep higher CAGR/no worse MaxDD when both it and Sentinel incur
twenty basis points per allocation turnover, and when both execute one session
later. These are screening gates, not statistical proof or production approval.

For all selectors report gross timing versus trading-cost contribution, losses
avoided and gains missed, warning/recovery exposure, fold/year results, and each
contiguous changed-exposure episode including its rejoin overnight. For selected
configurations report the five nearest same-family/submodel configurations using
parameter distance, without changing the selection. These are sensitivity
diagnostics, not five new tuning opportunities.

Use 500 seeded circular shifts of each selected exposure path as a random-timing
placebo. Occupancy is identical; the cut can change boundary turnover, which is
recomputed and disclosed. Use a 500-resample, twenty-session circular block
bootstrap of centered incremental log returns with a maximum statistic across
all 576 candidate streams plus the five selectors. This is an exploratory
multiple-testing diagnostic for this batch. It cannot correct unknown earlier
trials, guarantee stationarity, or manufacture untouched history.

Tests cover causal prefix invariance, no account-feedback features, purged label
boundaries, training-only transforms, frozen selection, valid action grids,
native protection for the state family, state expiration/confirmation,
next-open and overnight accounting, continuous fold ownership, selection
drawdown eligibility, deterministic search and direct independent raw-ledger
reconstruction. Explicit mutations must make the associated guards fail.

Run in the existing pinned Python 3.12 image, read-only sources/snapshot,
network disabled, half a CPU, one GiB, single BLAS thread and low priority. The
original stopped container, input checkpoint and prefix are checked unchanged.
Only research code/docs/tests are delivered; no production source is edited.
