# Synthetic Market Lab v1 — Adversarial World-Family Design

The registry in `world_families.py` defines strategy-independent economic scenarios. Phase 1 records structural intent and future generator levers; it does not generate or tune the full family set.

| Family | Structural design |
|---|---|
| broad persistent leadership | Slow sector/factor leadership with moderate idiosyncratic noise. |
| rapid leadership rotation | Shorter regime persistence, faster factor reversion, noisier sectors. |
| extreme top-rank instability | Weak cross-sectional persistence, higher idiosyncratic volatility, stronger crowding reversal. |
| momentum crashes | Persistent momentum interrupted by rare crowding/reversal shocks. |
| factor inversion | Extended intervals of negative conventional factor premia. |
| small-cap alpha disappearance | Suppressed size premium and compressed liquidity differences. |
| liquidity compression | Lower turnover, wider spreads, high common correlation. |
| prolonged recession | Sticky low growth, wide credit spreads, elevated distress/defaults. |
| inflationary stagnation | Persistent inflation, weak growth, restrictive rates, low productivity. |
| credit crisis | Credit shock plus liquidity stress, defaults, stronger correlations. |
| pandemic-like discontinuity | Abrupt supply/growth interruption with heterogeneous sector recovery. |
| speculative bubble and collapse | Risk-appetite expansion and crowding followed by reversal. |
| sideways low-alpha decade | Near-zero aggregate drift and weak cross-sectional premia. |
| high-volatility/no-trend | High conditional volatility, weak momentum, fast mean reversion. |
| low-volatility/high-correlation | Low idiosyncratic volatility dominated by common movement. |
| repeated sector rotation | Recurring changes in sector macro leadership. |
| commodity shock | Large commodity impulse with energy/materials and inflation pass-through. |
| rate shock | Policy/yield-curve repricing with duration-sensitive dispersion. |
| productivity boom | Persistent productivity improvement and growth leadership. |
| multiple interacting shocks | Overlapping persistent shocks with stress-correlation interaction. |

A family becomes executable only when its structural levers have explicit configuration parameters and invariant coverage. Family parameters are fixed from economic assumptions before any strategy evaluation.
