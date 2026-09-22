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
normalizing that projection view. This avoids current-close book information
entering earlier fills. It is still a snapshot-following account model, not the
complete production command/reconciliation pipeline. Preserve all older
artifacts and report that account results are not identical-model replications.
Price paths and Core/controller control traces must retain parity.

Independently reconcile cash and shares from signed trades, including fees,
split conservation and old ownership across the overnight interval. Restart
Core, controller and accounts at predeclared cuts. Commit source hashes, complete
daily traces, binding-cause counts, signal range/quantization diagnostics and
the finite-screen outcome. Targeted tests must kill removed native fencing,
early release, ignored missing evidence, checkpoint corruption and same-close
execution faults. Passing tests does not certify economic performance.
