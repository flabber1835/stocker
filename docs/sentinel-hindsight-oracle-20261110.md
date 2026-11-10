# Hindsight Sentinel benchmark

The owner authorized this research study after proposing an ideal exposure
teacher. Phase A calculates achievable hindsight headroom and explains the
differences from recorded Sentinel. It does not train a network, optimize an LLM
prompt, deploy a controller or claim that perfect-foresight decisions can be
predicted. Production Core, Sentinel, broker state and protected backtests remain
unchanged. Core holdings/decisions are the original immutable P00 book.

## Frozen inputs, ownership and account domain

Use all 2,156 authenticated P00 closes, 2018-01-02 through 2026-07-31. Source
daily journal: 170,330,724 bytes, SHA256
9f1c682846167a1deafe4496aa4d2e6b803f5650d9f2265b34c691bae56067b2.
Checkpoint gzip SHA256:
6942c696c752ee35d8a215a6ad138c71a69d9d8dd1337dcaa01519c3e141ea56.
Original completed admission:
65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83.

This is the original homogeneous Core-plus-T-bill SCALAR RESEARCH account,
not the later persistent whole-share execution model. Use its recorded BIL
publication proxy and costs consistently, not the distinct real-BIL pilot.
Core internal cash, claims, actions, trades and costs stay embedded in its
recorded NAV. No new Core holdings or broker state are formed.

The first measured close is an unfunded $50,000 anchor. Freeze the first funded
opening allocation at the original 100%, using the exact recorded formed-basket
entry calculation. All comparisons share those two boundary rows. Optimize
effective opening allocations on rows 2..2155, each decided at the previous
close. The final close has no later observed opening: no invented execution.

Allowed allocations are exactly 0, 0.55, 1. There are 19 ordinary allocation
changes in original P00. Every hindsight candidate is allowed at most those
same 19 changes, excluding the common initial deployment. There is no chosen
minimum hold or fixed monthly calendar, and no additional turnover-notional
cap. Actual turnover and costs are reported; equal change counts do not imply
equal cost. This daily policy class includes the original Sentinel path.

## Canonical edge factors and calibration

For each ordinary day, precompute all nine old/new allocation net factors by
calling the frozen canonical research Account.advance implementation inside
the qualified runtime. The wrapper is /fixed/research/pooled_vacancy_funding/
backtest.py, SHA256
0755b13777dc247fe3d112cd4f776329b44e47a8c97d3d524a968d8fbd970fe9.
Canonical shadow_observation.py SHA256:
62266616d6f9a78d6ae9eab4d88ee2429d1ce4e08e003afcb6b60a3c2115b957.
formed_economics.py SHA256:
34ce8061a3ebc53c208163f4f63049682f8ed9f5110413e0282d857d8fd84ef0.
Import these exact source identities; never execute a Core/controller step.

Unchanged allocation a uses a*Cclose/Cprev + (1-a)*Bclose/Bprev. A changed
allocation a to b uses the old allocation's overnight mixture, the new
allocation's open-to-close mixture and (1-0.001*abs(b-a)). These are different
branches, especially at 55%; do not replace both with an open-to-open shortcut.
The shared formed opening has its own authenticated subtractive-entry-cost
formula. Preserve canonical Decimal precision 28 when replaying account NAV;
derived metrics and independent constraint checks may use precision 50.

Require full original P00 NAV/factor/held/pending/cost calibration, exact
original source boundaries, and independent formula agreement for every edge.
Report raw Core separately from a funded always-Core comparison that includes
the same entry timing and costs. All oracle paths start from identical wealth.

## Frozen optimization questions

Optimize additive log net factors, retaining daily closing wealth and its own
running closing high-water mark. Drawdown is closing peak-to-trough account
drawdown, not intraday or a guaranteed tradable loss limit. No terminal
liquidation fee is invented at the last source close.

1. Daily dynamic programming maximizes terminal wealth with at most 19 changes,
   without a drawdown constraint. This is an exact upper bound within that
   finite research class and an explicit unrealizable-foresight reference.
2. Primary: maximize terminal wealth with the same change budget and maximum
   drawdown no worse than original Sentinel's calibrated drawdown. If the DP
   optimum already meets the cap, it certifies this optimum directly.
3. Protection frontier: maximize terminal wealth with a cap equal to one half
   of the calibrated baseline drawdown, under the same change budget.
4. Matched growth: minimize maximum drawdown subject to terminal wealth at
   least the funded always-Core comparator, under the same change budget.

These objectives/caps are frozen before new outcomes. The last two are distinct
questions, not a grid for selecting a production parameter. Include baseline,
funded always-Core, funded constant55 and switching to the T-bill sleeve after
the shared first deployment as reference paths.

For risk-constrained solves use a binary daily three-state flow model. Each
chosen old/new edge contributes its log net factor to cumulative log wealth.
Running-log-peak variables satisfy h_t>=h_(t-1), h_t>=w_t; impose
w_t>=h_t+log(1-D). To minimize drawdown, minimize B with w_t>=h_t-B and a
fixed terminal-growth floor. All coefficients and timing are source-bound.
Use natural-log factors for numerical optimization and independently replay
every returned allocation path using canonical decimal factors before admission.

HiGHS 1.15.1 is a research-only runtime extension: exact CPython 3.12 Linux
wheel highspy-1.15.1-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl,
5,034,168 bytes, SHA256
9730647160a6481426729f46d9989a0507d05f3cf96f9fb180f4ab9891bea67b.
Download from its pinned files.pythonhosted.org URL, authenticate before
extraction, and mount read-only at /solver. Reuse the runtime's NumPy 2.4.6.
Record solver version, model dimensions, options, status, primal objective,
dual bound, gap and wall time. Use two threads, seed zero, relative gap 1e-7,
and at most 1,800 seconds per nontrivial risk solve. A timeout may provide a
feasible incumbent plus bounds; it is never called an established optimum.
Do not expand the policy class or retune caps after seeing results.

Numerical qualification uses a 1e-8 natural-log tolerance for DP bound/path
agreement; 2e-6 for MILP row residuals, integrality and returned-path risk/growth
constraints; and 3e-6 for solver-objective/replay agreement. Report actual
decimal-replayed metrics and these tolerances. Optimality is within the stated
numerical model/tolerances, not an exact real-arithmetic financial certificate.

## Outputs, attribution and future learning boundary

Return every session's decision and effective exposure, account NAV, high-water
mark, drawdown, edge/cost factor, switch count and source identities. Report
CAGR, terminal wealth, maximum drawdown, time underwater, occupancy at each
exposure and turnover/cost summaries for every reference and oracle path.
Show the five original zero-exposure windows and major original drawdowns.

Per-day log(net_factor_oracle/net_factor_baseline) telescopes to the log terminal
wealth gap. Attribute first to lower/higher/equal effective exposure and
transition days, with costs separately explained. Within each original
defensive cycle, distinguish earlier reduction, delayed reduction, earlier
re-entry and delayed re-entry by matching ordered reduction/restoration events;
retain unmatched and mixed cases explicitly. These are descriptive differences,
not proof that a causal policy could capture the hindsight advantage.

The full-history optimum is not necessarily unique; output one selected path,
not a unique correct answer for each day. Full-history paths and their action
values are labelled HINDSIGHT_DIAGNOSTIC_ONLY and must never be presented as
leakage-free training labels. A later learning study must generate teachers
inside each training fold or use finite-horizon labels fully matured before
the next test window. The existing unsuccessful downside-forecast study remains
relevant. This phase makes no neural-network, LLM or out-of-sample return claim.

## Execution, independent review and delivery

Verified main: 1e7f4b181fbcb998b3086833ab813c21b1c2ca8e. Deliver only through a
ready PR from codex/sentinel-hindsight-oracle. Reuse pinned legacy transport
0bc38753ac1f85b31eb95f560720e6b037e892c5 and book admission
553590ca197c55942aadeb690d5436abd49a35d1. Pin prior DATA-reader lineage
d482a44ace51114d22cc98c3a4ce251410f8d153; the new DATA module independently
authenticates those same original journal bytes. Do not merge those branches.

All counterfactual factors, optimizations, account paths and numerical
falsifiers run only in credential-free, network-disabled GitHub-hosted
containers using pinned runnable image
sha256:1b449754a48473e4737fc34f3f51ae0b4226d5e84540dea54115d4693142ed9d.
Local work is source/DATA/AST inspection, hashes, transport and interpretation
of already-admitted results. Keep original sources read-only, resources bounded,
outcomes encrypted/private, stops explicit, and UNKNOWN/OOM/nonzero outcomes
unadmitted. No local financial runtime, broker or production DB is involved.

Independent review reconstructs edge equations and every returned path, checks
constraints/objectives/metrics and attribution, verifies DP certificates and
solver bounds/status, and independently solves small exhaustive fixtures.
Falsifiers include old-exposure overnight ownership, changed/unchanged 55%
branch, formed entry, fee removal, one-day target shift, last-unexecuted intent,
switch-budget violations, peak/drawdown constraints, infeasible solver output,
source/output tampering and false claims that hindsight labels are causal.
