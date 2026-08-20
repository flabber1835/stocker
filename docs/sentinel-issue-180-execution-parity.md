# Issue 180 — production projection and scalar-maintenance parity

This note records the historical measurement required by issue #180. It does
not modify the frozen Sentinel 1.1 reference implementation or its retained
artifacts.

## Inputs

The measurement was run on the exact corrected Sentinel 1.1 reference path and
its exact certified Sharadar SFP input:

```text
sentinel_1p1_daily.csv SHA256
9bf46bfa229888d997072dd4fa3f60f772b208b1e2c55480c8cf65dd7b1c62f7

SHARADAR_SFP.zip SHA256
8d2ebf7485977d9c40ec379eb33bd9d36d39d69db13602e5c51862d03172400c

reference window
2006-07-31 .. 2026-07-31, 5,032 sessions

frozen reference result reproduced before measurement
CAGR             0.22094618498568308
max drawdown    -0.21963097876900606
ending multiple 54.195852099734765
```

The daily-path digest is the one retained in
`docs/sentinel-reference-implementation/SHA256SUMS.txt`. The SFP digest is the
one embedded in the standalone reference's `EXPECTED_HASHES`. The full raw
Sharadar replay reproduced the retained daily-path digest exactly before this
measurement was taken.

## What is measured

The frozen standalone has deliberately different semantics when the scalar does
not change: Core and BIL are compounded as a fixed return mixture and no
maintenance-rebalance cost is charged. Production physically projects the live
account toward the scalar again on each prepared session.

This measurement isolates only the incremental turnover caused by maintaining
an unchanged 0.55 or 0.65 Core scalar. Wealth Core's own stock turnover is
common to both paths and is excluded.

For an interval starting at exact Core weight `e`, with close-to-close Core and
BIL factors `Rc` and `Rb`:

```text
ending NAV factor        F = e*Rc + (1-e)*Rb
Core weight before reset   = e*Rc/F
one-way maintenance T      = abs(e - e*Rc/F)
```

`T` is the notional shifted from one sleeve to the other as a fraction of NAV.
Two-leg gross broker turnover is `2*T`.

For cost reconciliation this uses the frozen reference's own overlay convention:

```text
cost = 0.001 * shifted_notional
```

That is the same 10 bp `COST * abs(new_alloc-old_alloc)` convention used by the
standalone when the scalar changes. It is intentionally not replaced with a new
broker/slippage model here.

The reproducible calculator is
`scripts/measure_sentinel_scalar_maintenance.py`.

## Result

Across the exact 20-year reference path:

```text
unchanged 0.55/0.65 intervals             227
  0.55 intervals                           147
  0.65 intervals                            80

cumulative one-way maintenance turnover   0.4813563453211653
cumulative two-leg gross turnover          0.9627126906423306
mean daily one-way turnover                0.0021205125344544726
max daily one-way turnover                 0.009748395893292563

linear 10 bp-convention cost fraction      0.0004813563453211653
compounded ending-NAV multiplier           0.9995187586302227
compounded total NAV drag                  0.000481241369777341
annualized NAV drag                        0.00002406707635516092
```

Applied to the retained 20-year Sentinel result, the same multiplicative drag
would change:

```text
ending multiple    54.195852099734765 -> 54.16977081363404
CAGR               22.0946184986%     -> 22.0916800381%
CAGR difference                         0.293846 bp/year
```

So the semantic gap is real but economically tiny: the entire 20-year fixed-
scalar maintenance cost is about **4.81 basis points of ending NAV**, and the
CAGR-equivalent difference is about **0.29 basis points per year** under the
reference's own cost convention. This is less than one 10 bp full-NAV execution
cost quantum over the entire reference window.

## Disposition

Keep the frozen reference semantics unchanged and retain production's physical
maintenance behavior. The difference is now measured, bounded and reproducible
instead of implicit. Certification evidence must not call the two execution
paths bit-identical; the residual execution-cost difference is the 0.29 bp/year
quantity above.

The P1 correctness defects are independent of this measured P2 residual and are
fixed in production code: live sizing uses broker cash plus observed positions
valued with decision-close/canonical stale marks, unpriced Core names can still
be reduced, and missing evidence cannot authorize an increase. If a held live
name has no usable close-domain mark at all, that leg is named and excluded from
the known-value NAV rather than substituted with broker mark-to-market equity;
this conservative long-only basis may reduce the name but cannot use the missing
mark to create a new increase.