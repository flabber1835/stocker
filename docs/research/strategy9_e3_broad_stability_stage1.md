# Strategy 9 + E3 broad-universe stability basin — Stage 1

Source E3 head: `3f27834db427e71d9bb8d0b6160c8835b739c906`
Diagnostic run: `33971822256`
Diagnostic head: `61c48d5ed6015528141650c639d2e025bb696e61`

This is a robustness diagnostic, not a production activation and not a parameter optimization exercise. The selection rule is to prefer an interior point in a flat neighborhood even when an edge point has slightly better backtest performance.

## Exact full-history results

| Point | Key settings | 20y CAGR | 20y max DD | 20y Sharpe | Max-history CAGR | Max-history max DD | Max-history Sharpe |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | REC 7; R20 -8.0%; V 11%; FAST 87.5%; healthy 62.5% | 20.3277% | -28.6186% | 1.1015 | 19.9548% | -33.4590% | 1.0737 |
| r20_center | REC 7; R20 -8.5% | 20.3277% | -28.6186% | 1.1015 | 19.9548% | -33.4590% | 1.0737 |
| recovery8 | REC 8; R20 -8.5% | 20.3000% | -28.6507% | 1.1003 | 19.9466% | -33.2817% | 1.0733 |
| recovery9 | REC 9; R20 -8.5% | 20.4140% | -28.3873% | 1.1056 | 20.0089% | -33.5567% | 1.0763 |
| recovery8_v115 | REC 8; R20 -8.5%; V 11.5% | 20.1426% | -28.6507% | 1.0933 | 19.8368% | -33.2817% | 1.0685 |
| native_880_630 | REC 8; R20 -8.5%; FAST 88.0%; healthy 63.0% | 20.3000% | -28.6507% | 1.1003 | 19.9466% | -33.2817% | 1.0733 |
| native_885_630 | REC 8; R20 -8.5%; FAST 88.5%; healthy 63.0% | 20.3000% | -28.6507% | 1.1003 | 19.9466% | -33.2817% | 1.0733 |
| native_880_635 | REC 8; R20 -8.5%; FAST 88.0%; healthy 63.5% | 20.3000% | -28.6507% | 1.1003 | 19.9466% | -33.2817% | 1.0733 |

## Stage-1 interpretation

1. `LDRC_R20=-8.5%` is preferable to `-8.0%` as a stability-center candidate because the exact broad replay is economically identical while the threshold is deeper inside the local decision plateau observed in the pre-screen.
2. `LDRC_REC` values 7, 8 and 9 all remain in a tight economic neighborhood. REC=9 has the best observed 20y CAGR/DD/Sharpe, but it is the upper edge of the tested interval and is therefore not selected merely because it performed best. REC=8 is the geometric interior point.
3. FAST damaged breadth from 87.5% through 88.5%, and healthy damaged breadth from 62.5% through 63.5% at the REC=8/R20=-8.5% center, produced identical economic outputs, transition count, cross-surface release count, divergence-entry count, FAST signal count and SLOW signal count. This is strong evidence of a real native-breadth plateau.
4. Raising `LDRC_V` from 11.0% to 11.5% changed recovery behavior and reduced performance. V=11.0% remains the center candidate pending asymmetric-edge confirmation.

## Stage-1 center candidate

- `LDRC_REC = 8`
- `LDRC_R20 = -0.085`
- `LDRC_V = 0.11`
- `FAST.dam = 0.88`
- healthy/recovery damaged ceiling `= 0.63`
- `LDRC_DD = -0.10` unchanged
- divergence SPY-r20 floor `= 0.0` unchanged pending Stage 2
- full-recovery recent-r40 floor `= 0.0` unchanged pending Stage 2
- `LDRC_CEIL = 0.55` unchanged

The Stage-1 center gives approximately 20.30% 20-year CAGR, -28.65% 20-year maximum drawdown, and 1.100 20-year Sharpe. The economic difference from the original Strategy 9 + E3 point is negligible, while several thresholds are moved away from observed discrete boundaries.

## Stage 2

Stage 2 must test the two remaining asymmetric gates around this center:

- divergence SPY-r20 floor around 0%
- full-recovery recent-r40 floor around 0%

It should also confirm the already-flat drawdown threshold and the upper side of the V-rebound threshold. The final parameter recommendation should be made only after those surfaces are checked.