# Sentinel Concordance LD-RC — simplification pass

**Date:** 2026-08-19  
**Status:** research simplification, not production certification  
**Objective:** simplify by subtraction. Do not search for a higher historical score.

## Starting point

The starting research candidate was the post-dividend **Sentinel Concordance LD-RC** state machine:

- corrected Sharadar volume and dividend economics;
- hardened Sentinel systemic fast trigger;
- native Sentinel partial recovery;
- independent recent-leadership confirmation before ordinary restoration to 100%;
- a latched strategy-divergence state while fully risk-on.

Original divergence-entry conjunction:

```text
Wealth Core drawdown <= -10%
AND damaged holding breadth >= 70%
AND recent-leadership shadow r20 <= -8%
AND recent-leadership shadow r40 <= -8%
AND SPY r20 >= 0%
```

The 55% cap remains latched until independent recovery evidence clears: recent-leadership shadow `r20 > 0` and `r40 > 0` for seven consecutive sessions, or a strong SPY 20-session rebound.

The corrected non-Concordance control remains **21.3433% CAGR / -24.7500% MDD**. The reconstructed full LD-RC is **~22.59% CAGR / -21.6958% MDD**, matching the retained research candidate to rounding.

## Method

No new feature was added. Conditions were removed or collapsed one at a time. A simplification was rejected if it materially surrendered the drawdown benefit, created excessive interventions, or introduced a more brittle timing threshold.

## First result: one original condition is strictly redundant

Removing the `Wealth Core drawdown <= -10%` predicate from the *original five-condition* divergence trigger produces the **exact same historical allocation path and metrics**.

Therefore the original five-condition LD trigger is unnecessarily complex. At minimum, the drawdown predicate should not coexist with all four of the other predicates.

The exact-path four-condition form is:

```text
damaged breadth >= 70%
AND recent-leadership r20 <= -8%
AND recent-leadership r40 <= -8%
AND SPY r20 >= 0%
```

This is a safe simplification because it changes no observed historical decision.

## Deeper subtraction

Representative results from the corrected 2006-07-31..2026-07-31 tape:

| Divergence entry | 20y CAGR | MDD | Sharpe | Interpretation |
|---|---:|---:|---:|---|
| Full five-condition LD-RC | ~22.59% | -21.70% | ~1.203 | starting point |
| Remove WC drawdown only | identical | identical | identical | strictly redundant |
| Remove recent r40 only, retain DD + damaged + r20 + SPY | 22.52% | -21.70% | ~1.209 | simpler, small wealth giveback |
| **WC DD + recent r20 + SPY** | **22.62%** | **-21.70%** | **~1.214** | minimal three-signal challenger |
| damaged breadth + recent r20 + SPY | 22.52% | -21.70% | ~1.209 | also viable |
| recent r20 + SPY only | 21.58% | -21.70% | — | too many false positives / too much time defensive |

The two-signal version is rejected. An internal Wealth Core stress condition is necessary; independent leadership weakness plus a healthy broad market is not sufficient on its own.

## Preferred minimal entry architecture

For explainability, the cleanest three-signal divergence detector is:

```text
1. Wealth Core is materially down from its peak;
2. independent recent leadership is materially weak;
3. SPY is flat/up rather than in a broad-market decline.
```

A representative retained numerical expression is:

```text
WC drawdown <= -10%
AND recent-leadership shadow r20 <= -8%
AND SPY r20 >= 0%
```

If true while fully risk-on, temporarily cap Core at 55%. Keep the state latched until independent leadership recovery confirms repair.

This version is preferred for **simplicity**, not because its terminal 2026 CAGR is a few basis points higher. Before a late-July-2026 divergence event, the full LD-RC is actually slightly ahead; the simplified version still materially beats corrected Sentinel with the same drawdown frontier. The late endpoint must not be used to call the simpler form a performance champion.

## Robustness of the three-signal form

A local grid varied:

- recovery persistence: 5 / 7 / 10 sessions;
- SPY V-rebound exception: 10% / 11% / 12%;
- WC drawdown trigger: -8% / -10% / -12%;
- recent-leadership r20 weakness: -6% / -8% / -10%;
- SPY divergence floor: 0% / +2%;
- cap: 55% / 65%.

Of 270 valid nearby combinations, **202 (74.8%)** beat corrected Sentinel on both CAGR and MDD. **178 (65.9%)** retained at least 22% CAGR and MDD no worse than -22.5%.

The central three-signal form also beats corrected Sentinel on CAGR and MDD across all 15 annual start-date comparisons from 2006 through 2020. The minimum CAGR advantage among those starts is about **+0.35 percentage points**, while the MDD improvement is about **3.05 percentage points** for every start that includes the common drawdown frontier.

55% versus 65% produces the same -21.70% MDD frontier and very similar long-run CAGR, again suggesting that the state classification matters more than the exact cap.

## Recovery simplification test

The recovery rule was also challenged. Replacing the two-horizon recovery witness with one horizon can work at certain persistence lengths, but it creates a more visible timing cliff. For example, r40-only recovery at 7 sessions gives about -22.43% MDD, while 10 sessions returns to the -21.70% frontier. Likewise, r20-only recovery is poor at 5-7 sessions but works around 10+.

That is not a desirable simplification: it removes one observable but makes the exact persistence count more load-bearing.

Therefore retain the conceptually simple two-horizon recovery statement:

> independent leadership must be positive over both the short and medium horizons for about a week, unless SPY is in an unmistakably strong V-rebound.

This is easier to defend than replacing it with a single horizon plus a more finely tuned day count.

## Complexity floor

The research now suggests a natural minimum:

### Entry into strategy-divergence protection

Three conceptual observations:

1. **our alpha engine is hurting** — Wealth Core drawdown;
2. **the opportunity-set thermometer agrees** — recent leadership is weak;
3. **this is not simply a market crash** — SPY is not weak.

### Exit / restoration to full risk

One independent recovery concept:

- leadership is positive across short and medium horizons persistently; or
- the broad market is rebounding so violently that waiting would be perverse.

### State behavior

- cap exposure modestly;
- latch the cap until recovery is independently confirmed.

No additional signals, factor models, regime classifier, optimizer, voting ensemble, or position-level actuator is required.

## Decision

**The full five-condition LD entry should not be treated as the preferred architecture.** It contains at least one strictly redundant condition.

The best simplification target is the **three-signal LD state machine**:

```text
WC materially down
AND independent leadership materially weak
AND SPY not weak
    -> modest temporary cap
    -> stay capped until independent leadership recovery
```

This is the current preferred *research simplification* because it is substantially easier to explain and still preserves the economic behavior that motivated Concordance.

Do not optimize the three numerical thresholds further. Before production, freeze simple rounded thresholds, rerun after the SEC point-in-time correction, retain the exact source implementation, and accumulate genuinely unseen forward sessions.
