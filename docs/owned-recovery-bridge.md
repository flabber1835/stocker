# Owned-book partial recovery experiment

## Registration before implementation

2026-09-22. Research only. Base verified by `git fetch origin main`:
`ee23c894c97a2c4023654ce3a56a62728f5b061e`. Delivery is a feature-branch
pull request to `flabber1835/stocker:main`; no production selection changes.
This follows the mechanics assessment in PR #437. No historical optimization
or new twenty-year replay is authorized by this experiment.

Freeze exactly one challenger, **recovery bridge**, alongside unchanged current
Sentinel and Owned55. Owned55 already has owned-specific recovery for its own
latch. The new mechanism addresses a different restriction: the legacy
leadership recovery hold *after Native has recovered*.

At each close, run current Sentinel and Owned55 unchanged. Count consecutive
sessions with Native at 100%, owned r20 strictly positive, damage at most 63%,
and green breadth at least 20%. Nonfinite/missing evidence or Native defense
resets the count. Cap the count at eight. If the count reaches eight and the
current recovery reason is exactly `FULL_RISK_HELD`, allow 55%, capped by
Native and the owned ceiling. Otherwise use Owned55's target. The bridge is
not latched: lost health withdraws it at the next decision. Existing leadership
full-recovery rules and divergence ceilings remain unchanged. Eight and 55%
reuse existing design values; neither is claimed optimal. All decisions execute
at the following open. State identity binds the rule and frozen parent source;
duplicate/out-of-order sessions and altered checkpoints refuse.

This deliberately preserves independent zero causes and full-release evidence.
It offers limited participation during healthy-owned/weak-leader disagreement.
The expected failure mode is extra loss or churn when apparent owned recovery
relapses. A healthy leader cohort alone must not qualify the owned bridge.

## Frozen synthetic panel and screening decision

Use canonical production warmup (252 sessions), two formation ages (40 and
120 sessions), sixty securities and 120 scenario sessions. The original seven
price formulas from PR #433 remain controls: healthy, healthy with a neutral
split, synchronized shock, staggered damage, gradual decline, temporary
correction and leadership rotation. Add six deterministic paths, with all
multipliers applied on top of the existing small ordinary drift/noise:

| Path | Stock multiplier | Market multiplier |
|---|---|---|
| Rebound then relapse | .82 day 0; 1.012 days 15–34; .82 day 45 | .92 day 0; 1.004 days 15–34; .92 day 45 |
| Owned recovery, weak alternatives | .82 all day 0; days 15–74: 1.008 initially held, .998 others | .92 day 0; otherwise 1 |
| Leaders recover, weak owned | .82 all day 0; days 15–74: .999 initially held, 1.008 others | .92 day 0; otherwise 1 |
| Concentrated winner then loss | first two initial holdings 1.025 days 0–39, .94 days 40–49 | 1 |
| Stationary high volatility | alternating exp(+.025), exp(−.025) | alternating exp(+.015), exp(−.015) |
| Repeated shocks | .86 on days 0, 30, 60; 1.006 days 10–24, 40–54, 70–94 | .94 on shock days |

These are mechanism stimuli, not independent market samples. Record whether
each intended condition actually occurs; an unexcited bridge is inconclusive,
not acceptance. Add controlled observation-level witnesses for missing evidence,
strict eight-session timing, leader/owned disagreement, relapse withdrawal,
native independence, monotonic stronger owned recovery and restart at each
transition. Such witnesses validate logic, not coherent market economics.

Before results: screen out a historical follow-up if any new scenario loses
more than 2% of initial capital versus Owned55, worsens drawdown by more than
2 percentage points, or adds more than 0.25% of initial capital in fees. Require
at least one coherent scenario with useful bridge activity and improved terminal
value versus Owned55, and no difference in the healthy control. These are
provisional conservative research budgets, not approved production risk limits.
Retain every result if the screen fails; do not adjust the policy or generator.

## Ownership and accounting

Reuse the pinned synthetic feed, canonical Core kernel and production Decimal
projection. One immutable Core path feeds all three controllers. Accounts use
whole shares, $100,000 formation allocation, 10 bp trading costs and zero-yield
synthetic bills. No broker, database or NAS is involved.

The older phase runner passes the completed *current close* Core state to its
simulated opening projection. This experiment instead projects only the prior
close's published holdings and target at the next open, with current splits
normalizing that projection view. It is a snapshot-following account model,
not the complete production command/reconciliation pipeline. Preserve all older
artifacts and report that account results are not identical-model replications.
Price paths and Core/controller control traces must retain parity.

**Clarification after source tracing, before panel completion:** registration
initially described the older ordering as possible future-information leakage.
That is not established for these synthetic paths. `adapter.step_session`
executes yesterday's pending orders at today's open; ordinary close decisions
queue tomorrow's orders without changing current quantities/cash. The older
model therefore follows the book *after those known opening fills*, whereas
this experiment follows the last published close snapshot. This creates a
holdings-following lag here, not proof of a software defect in the older
ordinary-price panel. No terminal/cash-action coverage can be inferred from
either panel. Retained account differences must be described as model
sensitivity, not bias corrections or evidence invalidating prior results.

The twenty-year comparison follows a separate production scalar accountant
(`ShadowObserver._advance_strategy_economics`): prior pending allocation bears
the next intraday return, and prior held allocation bears the overnight return.
It does not call the synthetic whole-share projection helper. This finding
does not invalidate the reported 29.24x/30.66x comparison or remove its existing
data and execution-model limitations.

Independently reconcile cash and shares from signed trades, including fees,
split conservation and old ownership across the overnight interval. Restart
Core, controller and accounts at predeclared cuts. Commit source hashes, complete
daily traces, binding-cause counts, signal range/quantization diagnostics and
the finite-screen outcome. Targeted tests must kill removed native fencing,
early release, ignored missing evidence, checkpoint corruption and same-close
execution faults. Passing tests does not certify economic performance.

## Results: complete finite panel

All 26 paths completed (13 formulas x two formation ages). The frozen numerical
screen passed: two improvements, 24 identical terminal results versus Owned55,
no worsened maximum drawdown, no exceeded loss/fee budget, and both healthy
controls unchanged. This clears the numerical screen for further research;
it is **not sufficient evidence for promotion**. No twenty-year replay has
been started for this challenger.

| Formation / stimulus | Current end NAV | Owned55 end NAV | Bridge end NAV | Extra bridge decisions | Increment vs Owned55 | Max drawdown, all three |
|---|---:|---:|---:|---:|---:|---:|
| 40 / owned recovery | $108,040.19 | $108,040.19 | $110,261.46 | 4 | +$2,221.27 | -17.91% |
| 120 / leader recovery / Core replacement | $116,981.71 | $116,981.71 | $119,089.60 | 5 | +$2,107.88 | -17.22% |

Capital is $100,000 and each scenario is 120 sessions. These are terminal
dollar differences, not a forecast or a twenty-year CAGR estimate. Additional
fees were $2.08 and $0.90. No parameter or formula was altered after viewing
results. See the complete matrix and daily traces in
`audit/owned-recovery-bridge/summary.json` and its hashed compressed artifacts.

### What improved, and what did not

In the first useful case Native clears on day 33. Eight healthy owned/native
observations permit the bridge at day 40, executing at day 41's open. Current
Sentinel and Owned55 remain at zero until day 44's close, executing at day 45's
open. The bridge captures four otherwise missed intraday intervals without
overriding Native. Full leadership recovery is already economically positive
at the bridge dates; its persistence clock has not yet reached eight.

The second useful case is **not proof that healthy leaders justify buying a
still-damaged original book**. The 120-session formation age allows the Core
review/replacement process to change holdings. At the bridge dates the *new*
owned book has 10–14 holdings, 50.86–71.42% of Core NAV in equities, zero damaged
breadth and 100% green. Decisions on days 32–36 execute on days 33–37, before
the normal full-release decision on day 37. A 55% allocation to this Core is
roughly 28–39% stock exposure at decision marks, not 55% stocks. The difference
between the two formation ages shows why a controller must measure today's
actual shadow ownership rather than a fixed original cohort.

### Remaining adverse coverage and structural limitations

1. Rebound/relapse and repeated-shock paths **did not activate the bridge**.
   Their unchanged returns prove no intervention on those paths; they do not
   measure loss from a relapse after an actual bridge entry. The observation
   witnesses prove immediate withdrawal on lost health and preserved Native
   fencing, but not the size of next-open gap loss. This is a remaining risk
   qualification requirement, despite the numerical screen passing.
2. No useful bridge interval has negative leaders r20. The favorable cases
   demonstrate a persistence-clock mismatch. They do not establish success in
   prolonged owned-positive/leader-negative market disagreement. Only the
   controlled observation witness exercises that condition long enough.
3. The legacy full-release comparator remains non-monotone. In a fixed-state
   witness with leaders r20 +2%, leaders r40 -5% and SPY r20 +2%, owned r20 +1%
   releases 100%; increasing owned r20 alone to +3% leaves this challenger at
   55%. Current Sentinel would leave the latter at zero. The bridge reduces
   the disparity but does not solve it. `test_retained_legacy_full_release_is_not_globally_monotone`
   explicitly retains this limitation instead of calling the whole controller
   monotone because the new sub-rule is monotone with its parent fixed.
4. Signal numerical range is ample, but information resolution is uneven.
   In the first useful case r20 spans -19.39% to +20.60%, with 120 distinct
   observations; damage has only seven values. In the second, damage takes
   only zero or one. Both successful intervals have damage=0 and green=1, so
   these paths do not validate calibration near the 63%/20% recovery boundaries.
   Tests establish exact boundary behavior, not statistical signal quality.
5. The dedicated concentration stimulus reaches about 11.6% maximum single-name
   stock weight. Other rebuilding paths reach one holding (100% of the stock
   sleeve), illustrating why cash fraction and position count must accompany
   breadth. The bridge did not activate during that one-name state. Stationary
   volatility paths do not trigger defense; this remains consistent with
   measuring volatility acceleration rather than its absolute level.

Recommendation: retain this frozen challenger as a useful **limited recovery
bridge**, not a completed repair or proven better production policy. Before
promotion, require an actually entered bridge followed by an adverse gap/relapse
and explicitly settle the remaining relative-return full-release behavior.
If historical research is authorized next, run this exact frozen policy and
retain its adverse episodes; do not optimize these scenarios for more profit.

### Prior results and account-model sensitivity

The fourteen original case/formation combinations have **identical Core
observations and current-controller decisions** to the retained phase study.
Changing from following the post-opening-fill Core to following its prior-close
snapshot moves current-account terminal value by -$668.85 to +$63.51 across
those controls. The largest change is leadership rotation at formation 120;
healthy controls are exactly unchanged. These are execution-model sensitivities,
not corrections to a demonstrated look-ahead bug. The first registration and
interim commentary overstated that suspicion; the source-traced clarification
above supersedes it. All earlier artifacts remain intact.

The historical 29.24x/30.66x result is not invalidated by this finding. Its
different scalar accounting path preserves prior-allocation next-open timing.
It remains subject to its original data caveats and is not equivalent to a
broker-executed whole-share return.

### Validation

The independent auditor regenerated prices and reconciled **9,360 account-days**
of cash, holdings, fill prices, fees, opening equity, closing NAV and daily P&L.
It checked previous-session ownership/target timing, exact trace coverage,
fourteen retained Core/controller controls and split-neutral observations and
decisions. A same-close allocation corruption was rejected. Online checks cover
3,280 production-controller parity closes, 208 Core restart pairs, and 624
restart pairs each for controllers and accounts. Production constants stayed
unchanged.

Nineteen focused tests pass. Five isolated policy mutants are killed: early
release, removed Native cause, ignored owned health, removed owned ceiling and
removed checkpoint commitment. Syntax, whitespace and repository test-ownership
validation pass. These research tests are invoked explicitly, outside the
permanent production CI test roots; no green-CI claim substitutes for them.
Exact commands and artifacts are in `audit/owned-recovery-bridge/README.md`.
