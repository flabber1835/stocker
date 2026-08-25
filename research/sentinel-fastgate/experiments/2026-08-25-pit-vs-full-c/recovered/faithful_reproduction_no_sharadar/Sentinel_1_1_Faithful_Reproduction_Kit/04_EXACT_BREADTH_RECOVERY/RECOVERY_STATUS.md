# Exact breadth recovery status

The Sentinel-relevant portion of the old `position_features(g, cfg)` function has been mathematically recovered to exact daily parity with the retained frozen breadth oracle.

Validation population:

- 160,715 holding-days
- 7,061 comparable market sessions
- GREEN count parity: 7,061 / 7,061 sessions
- AMBER / damaged count parity: 7,061 / 7,061 sessions
- Mean absolute daily count error: 0.000 positions for both outputs

Exact semantics:

```python
green = (
    (own_dd > -0.075)
    & (r21 > 0.0)
    & ((age_sessions < 63) | (r63 > 0.0))
)

red = (
    (own_dd <= -0.10)
    & (r21 < 0.0)
)

sector_stress = mean(red) within each sector on the decision date

amber = (
    (own_dd <= -0.10)
    | (r21 <= -0.03)
    | ((sector_stress >= 0.50) & (~green))
)
```

Downstream Sentinel breadth is `mean(amber)` and `mean(green)`.

Boundary details matter: GREEN uses strict `own_dd > -7.5%` and `r21 > 0`; RED uses strict `r21 < 0`; AMBER uses inclusive `r21 <= -3%`; sector contagion starts at RED fraction `>= 50%` and excludes green holdings.

Numerical contract: the retained position replay stored lag closes in float32 before computing r21/r63. Preserve that behavior or explicitly prove numerical equivalence.

The only unrecovered output is the old Selective Survivor Firewall `priority` score. Sentinel 1.1 does not consume it.
