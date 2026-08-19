# Corrected Sharadar Drawdown Forensics

**Status:** research note / smoke-test evidence, not certification  
**Date:** 2026-08-18  
**Primary question:** why did correcting the Sharadar liquidity domain degrade Sentinel's 20-year maximum drawdown from roughly -22% to roughly -40%, and does the earlier drawdown research contain the right remedy?

## Executive conclusion

Correcting Sharadar liquidity semantics did **not** invalidate the core Sentinel thesis. It exposed a brittle fast-crisis detector.

The former 20-year Sentinel 1.1 reference used the economically inconsistent combination:

```text
closeunadj * volume
```

for daily dollar volume / ADV eligibility, even though Sharadar `volume` is split-adjusted while `closeunadj` is raw/as-traded. The corrected smoke test instead uses the split-compatible quantity:

```text
close * volume
```

while leaving the rest of Wealth Core and Sentinel unchanged.

The corrected 20-year result deteriorated from approximately:

```text
CAGR       22.09% -> 20.29%
Max DD    -21.96% -> -39.93%
Ending      54.20x -> 40.23x
Sharpe       ~1.17 -> ~1.06
```

The deterioration is overwhelmingly explained by one failure in 2008: the corrected Wealth Core portfolio narrowly failed Sentinel's hard five-session damaged-breadth acceleration threshold, so the fast crisis detector did not fire. Sentinel then remained fully invested until the much slower crisis path caught up months later.

A narrow, economically motivated hardening of that fast-crisis membrane recovers almost all of the lost economics on the corrected Sharadar tape:

```text
Corrected frozen Sentinel:
    CAGR       ~20.29%
    Max DD     ~-39.93%
    Ending     ~40.23x
    Sharpe     ~1.06

Corrected + hardened fast sensor:
    CAGR       ~22.02%
    Max DD     ~-24.02%
    Ending     ~53.55x
    Sharpe     ~1.14
```

This strongly supports the earlier systemic-shock research: **sparse, high-confidence systemic loss avoidance can reduce drawdown and increase CAGR simultaneously**. What appears fragile is not that mechanism, but one exact breadth-acceleration threshold frozen into Sentinel.

---

## Scope and caveats

This is a **smoke-test research result**, not a new certified strategy claim.

Accepted for this experiment:

- the existing modern reconstructed Sharadar historical tape;
- the existing issuer-history approximation;
- no SEC point-in-time filing reconstruction;
- the retained Sentinel 1.1 standalone historical implementation;
- the same execution/cost semantics as the reference implementation.

Not established by this note:

- point-in-time SEC causality;
- production readiness;
- certification-chain integrity;
- live broker parity;
- a final parameter choice for a revised crisis detector.

The Sharadar interface remediation tracked in issue #185 remains required independently of this research result.

---

## Control: reproduce the former 20-year reference exactly

Before changing the liquidity domain, the historical standalone replay was run unchanged as a control.

Window:

```text
2006-07-31 -> 2026-07-31
```

The control reproduced the retained reference exactly:

| Metric | Former reference / control |
|---|---:|
| CAGR | 22.0946185% |
| Maximum drawdown | -21.9630979% |
| Ending multiple | 54.195852x |
| Executed buys, full replay | 722 |

This exact reproduction is important: the subsequent delta is attributable to the liquidity-domain correction rather than to an independently reconstructed or drifting Sentinel implementation.

Retained reference artifacts:

- `docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`
- `docs/sentinel-reference-implementation/sentinel_1p1_summary.json`
- `docs/sentinel-reference-implementation/trailing_scorecard_vs_spy.csv`

---

## Corrected Sharadar smoke result

Only the liquidity calculation used for the minimum daily-dollar-volume and ADV gates was changed from:

```text
closeunadj * volume
```

to:

```text
close * volume
```

No execution price, controller rule, Wealth Core ranking rule, position sizing rule, stop rule, corporate-action rule, or defensive-sleeve rule was intentionally changed.

### 20-year comparison

| Metric | Former | Corrected Sharadar | Delta |
|---|---:|---:|---:|
| CAGR | 22.09% | 20.29% | -1.81 pp |
| Max drawdown | -21.96% | -39.93% | 17.97 pp worse |
| Ending multiple | 54.20x | 40.23x | -25.8% |
| Daily Sharpe, zero RF | ~1.17 | ~1.06 | ~-0.11 |
| Total buys incl. warm-up | 722 | 742 | +20 |
| Buys inside 20y window | 462 | 477 | +15 |

The corrected and former paths differ materially in the underlying stock selections, but the most important economic divergence is the Sentinel controller's crisis timing in 2008.

### Trailing windows

The damage is concentrated in older history.

| Trailing window | Former CAGR | Corrected CAGR | Former MDD | Corrected MDD |
|---|---:|---:|---:|---:|
| 5y | 26.20% | 26.16% | -20.93% | -21.71% |
| 10y | 26.13% | 26.75% | -21.96% | -22.60% |
| 15y | 21.53% | 21.04% | -21.96% | -22.60% |
| 20y | 22.09% | 20.29% | -21.96% | -39.93% |

The last decade survives the correction remarkably well. The large degradation appears when the Great Financial Crisis enters the window.

---

## Root cause: corrected holdings changed Sentinel breadth

The Sharadar liquidity fix alters which securities pass Wealth Core's liquidity eligibility filters. That changes the candidate pool, then the selected holdings, then Sentinel's holding-level breadth inputs.

The important consequence is therefore indirect:

```text
liquidity-domain correction
    -> different eligible stocks
    -> different Wealth Core holdings
    -> different damaged/green breadth
    -> different Sentinel crisis classification
    -> different exposure path
```

The data correction did not simply lower returns mechanically. It perturbed the portfolio enough to falsify the robustness of one crisis threshold.

---

## The July 2008 failure

Sentinel's frozen fast-entry rule requires a conjunction including:

- shadow drawdown <= -10%;
- damaged breadth >= 85%;
- green breadth <= 20%;
- shadow 5-session return <= -5% **or** 10-session return <= -8%;
- damaged breadth increase over five sessions >= **40 percentage points**;
- SPY 5-session volatility / 20-session volatility acceleration >= 4%;
- external/systemic confirmation from SPY or a sufficiently severe Wealth Core loss.

See:

- `docs/sentinel-handoff/00_README/FROZEN_SENTINEL_1P1_RULE.json`

### July 2, 2008

Under the former liquidity path, the panic sensor fired.

Approximate former-path state:

```text
Wealth Core drawdown            -11.8%
damaged breadth                  95.8%
5-session WC return              -7.6%
10-session WC return            -11.8%
damaged breadth delta5          +41.7 pp
SPY 20-session return            -8.1%
SPY volatility acceleration      +6.4%
FAST crisis                      TRUE
```

The former Sentinel therefore moved to 0% Core at the next open.

With corrected liquidity on the same date:

```text
Wealth Core drawdown            -12.1%
damaged breadth                  81.8%
5-session WC return              -8.3%
10-session WC return            -12.1%
damaged breadth delta5          +29.6 pp
SPY panic evidence               still severe
FAST crisis                      FALSE
```

The corrected portfolio did not satisfy the damaged-breadth gates on that exact session.

### July 8, 2008: the clearest falsifier

A few sessions later, the corrected portfolio was unambiguously in systemic distress:

```text
Wealth Core drawdown            -13.8%
damaged breadth                 100.0%
green breadth                     0.0%
5-session WC return              -9.8%
10-session WC return            -13.3%
SPY 20-session return            -6.4%
SPY volatility acceleration     +26.9%
damaged breadth delta5          +39.13 pp
```

Every economically meaningful panic condition was satisfied **except** the five-day damaged-breadth acceleration requirement:

```text
required >= 40.00 pp
observed  = 39.13 pp
```

Sentinel therefore remained fully invested.

This is the central robustness failure.

With roughly 20-25 holdings, one holding represents around 4-5 percentage points of breadth. A financially critical crisis/no-crisis decision was therefore sensitive to approximately one holding's classification.

---

## The fast/slow dead zone

Sentinel has two major crisis-entry speeds:

### Fast

Designed for a violent panic impulse. It requires the large five-day damaged-breadth acceleration discussed above.

### Slow

Designed for persistent stress. It requires roughly 30 stress sessions before entry, along with weak return/breadth conditions.

The corrected 2008 path fell between them:

```text
not violent enough for FAST under the exact +40 pp threshold
but far too dangerous to wait for SLOW
```

This creates a **medium-speed crisis dead zone** in the controller.

Corrected Sentinel did not reach 0% Core until approximately **2008-10-06**. From the local June 18 peak to that defensive transition, it had already lost roughly **30.7%**.

That delay explains most of the new ~-40% maximum drawdown.

---

## Re-entry was harmful but secondary

Corrected Sentinel then remained defensive through much of late 2008.

On approximately **2008-12-24**, the recovery logic judged conditions sufficiently improved and returned to 100% Core. From that re-entry through roughly **2009-03-05**, the strategy lost another approximately **13.2%**.

This contributes to the final drawdown, but follow-up experiments do **not** identify generic slower recovery as the primary remedy.

Forced 55% -> 65% -> 100% recovery variants generally:

- produced only ~19.7-19.8% CAGR;
- did not repair the overall ~-40% maximum drawdown;
- sometimes worsened both return and drawdown.

Conclusion: do not redesign recovery yet. Fix crisis recognition first.

---

## What the earlier negative experiments taught us

Several prior drawdown-reduction experiments produced disappointing results. The corrected tape explains why many were negative: they attacked **generic drawdown**, not **rare systemic loss**.

### Generic ~5% portfolio stop

On the corrected path, a simple portfolio-stop family reduced drawdown but damaged compounding severely.

Representative result:

```text
CAGR                ~14.9%
Max drawdown         ~-31.1%
Defensive episodes   ~72
```

The failure mode is excessive false positives: ordinary corrections and internal rotations repeatedly cut risk.

### Generic dynamic exposure / circuit-breaker ideas

Previous nonlinear caps, persistent-bear overlays, simple drawdown circuits and more structural cash similarly tended to sacrifice substantial upside for only partial drawdown relief.

These results remain useful negative evidence. They argue against solving the corrected 2008 problem with a broad portfolio stop.

---

## The earlier systemic-shock experiment was probably the golden insight

The prior systemic-shock forensic work reached a very different conclusion from the generic stop experiments.

See:

- `docs/sentinel-handoff/06_RESEARCH_SOURCE_FRAGMENTS/systemic_shock/SHOCK_OVERRIDE_FORENSICS_REPORT.md`

That experiment found that:

1. the benefit came primarily from avoiding unusually large Wealth Core losses, not from T-bill yield;
2. the number of positive and negative defensive days did not need to be very different—negative days simply had much larger magnitude;
3. geometric compounding magnified the value of preventing a few severe losses;
4. false positives were the main source of harm;
5. externally confirmed systemic panic episodes were substantially more reliable than internal-portfolio distress alone.

Its leading research challenger used approximately:

```text
internal WC shock evidence
+ external SPY panic confirmation
+ temporary defensive exposure
+ immutable Wealth Core shadow
+ shadow-controlled recovery
```

The corrected Sharadar result independently reinforces that same mechanism.

---

## Threshold neighborhood experiment

The damaged-breadth five-day acceleration threshold was swept while leaving the rest of the corrected Sentinel logic frozen.

Representative 20-year result:

| Minimum damaged-breadth delta5 | CAGR | Max DD |
|---:|---:|---:|
| 40%+ | 20.29% | -39.93% |
| 38-39% | 21.71% | -24.96% |
| **24-37%** | **22.02%** | **-24.02%** |
| 20-23% | 21.37% | -25.65% |

Important observations:

- the favorable result is not located at one exact 30.000% optimum;
- a broad region from roughly 24% through 37% produced the same historical allocation path;
- 45 neighboring combinations across related damaged-breadth / volatility / SPY-confirmation values produced the same favorable path in the smoke analysis;
- the current 40% threshold sits just outside that stable region and on the wrong side of a large economic cliff.

This does **not** prove 30% is the correct production threshold. It demonstrates that the current exact 40% threshold is brittle under a legitimate data-domain correction.

---

## Sparse intervention is the strongest evidence

The hardened fast sensor does not continuously interfere with Wealth Core.

Relative to corrected frozen Sentinel, the favorable challenger changed exposure in essentially two periods over twenty years.

### Main intervention

```text
2008-07-09 -> 2008-10-03
```

The hardened version was defensive while corrected frozen Sentinel remained fully invested. The paths then reconverged when the original slow detector finally caught the crisis.

### Secondary intervention

Approximately one trading day around the August 2011 stress episode, where the hardened detector entered the same defensive state earlier.

Most importantly:

> From 2016 through July 2026, the favorable hardened challenger produced no material allocation-path difference from corrected frozen Sentinel in this smoke experiment.

The improvement is therefore not explained by constant de-risking. It is driven by a tiny number of timing corrections.

---

## Corrected + hardened fast sensor

A central hardened neighborhood around roughly 30-35 percentage points of five-session damaged-breadth acceleration produced approximately:

| Metric | Corrected frozen | Corrected + hardened fast sensor |
|---|---:|---:|
| CAGR | 20.29% | **22.02%** |
| Max drawdown | -39.93% | **-24.02%** |
| Ending multiple | 40.23x | **53.55x** |
| Daily Sharpe | ~1.06 | **~1.14** |

This nearly restores the former economic result while retaining corrected Sharadar liquidity semantics.

Former uncorrected reference ending multiple was ~54.20x versus ~53.55x for the corrected+hardened challenger.

That is the strongest evidence so far that the old ~22% CAGR was not simply an artifact of the Sharadar volume-domain defect. Rather, the correction exposed a separate fragility in the controller's risk sensor.

---

## Refined hypothesis: lower drawdown can increase CAGR, but only with precision

The data support a more precise version of the working hypothesis:

> Reducing drawdown increases CAGR when the avoided loss is sufficiently severe and the crisis detector is sufficiently precise that preserved capital exceeds the gains forfeited during defensive periods.

The earlier generic stop experiments demonstrate that lower drawdown does **not** automatically imply higher CAGR.

The systemic-shock work and corrected 2008 experiment demonstrate the favorable case:

```text
rare event
+ high-confidence systemic confirmation
+ severe conditional downside
+ sparse intervention
= lower drawdown and higher geometric CAGR
```

---

## Preferred research direction: bridge the medium-speed dead zone

Do **not** simply replace `0.40` with `0.30` and call the problem solved.

A more principled candidate is to preserve the existing fast path and add a separately justified **medium-fast systemic bridge**.

Conceptually:

```text
FAST = existing fast crisis rule

OR

MEDIUM_FAST_SYSTEMIC =
    WC drawdown <= -10%
    AND damaged breadth >= ~85%
    AND green breadth <= ~20%
    AND (WC r5 <= -5% OR WC r10 <= -8%)
    AND damaged breadth delta5 >= ~30%
    AND SPY volatility accelerating
    AND broad-market / SPY trend clearly negative
```

The reason to require stronger external confirmation on the lower-acceleration branch is economic rather than statistical:

> If internal portfolio damage is severe but develops slightly more gradually, broad-market panic evidence can substitute for the missing few percentage points of internal breadth acceleration.

This aligns directly with the earlier systemic-confirmed shock research.

---

## What should *not* be changed yet

Current evidence argues against the following as the next move:

- a generic 5% portfolio stop;
- a generic 12.5% circuit breaker;
- broad nonlinear dynamic exposure caps;
- structural additional cash;
- changing Wealth Core itself to solve this controller defect;
- forcing every recovery through 55% -> 65% -> 100%;
- reducing genuine severe-crisis exposure merely to 25% or 40% instead of fully defensive.

On the corrected tape, once a genuine systemic panic is correctly recognized, aggressive de-risking is economically useful. The dominant problem is **missing the event**, not de-risking too much.

---

## Interpretation for Sentinel

The corrected Sharadar tape acted as a perturbation test.

A robust financial controller should not go from:

```text
"clear systemic crisis -> fully defensive"
```

to:

```text
"do nothing for roughly three months"
```

because a legitimate data-domain correction changed one holding-level breadth statistic from about 41.7 percentage points to 39.1 percentage points.

Therefore the principal architectural finding is:

> Sentinel's crisis semantics are too tightly coupled to one exact five-session breadth-acceleration threshold and one historical Wealth Core composition.

The Sharadar correction exposed this controller fragility; it did not create the underlying architectural weakness.

---

## Next validation work

The next phase should be adversarial validation, **not another broad parameter search**.

Recommended work:

1. **Single-holding perturbation tests**
   - flip one holding's damaged/healthy classification near the crisis threshold;
   - vary portfolio size / breadth denominator;
   - prove crisis semantics do not depend on one security.

2. **Leave-one-crisis-out validation**
   - design/freeze the rule without each major crisis in turn;
   - verify the held-out event still receives sensible treatment.

3. **Rolling-start / rolling-origin validation**
   - ensure the improvement is not an artifact of the 2006 start or pre-window state.

4. **False-positive audit**
   - enumerate every incremental defensive episode produced by the new bridge;
   - quantify avoided losses vs missed rebounds independently.

5. **External confirmation robustness**
   - perturb SPY volatility-acceleration and trend thresholds;
   - prefer a plateau / semantically stable region over an optimized point.

6. **Execution-cost sensitivity**
   - widen transition-cost assumptions substantially;
   - verify sparse intervention remains economically favorable.

7. **Sharadar-corrected full recertification**
   - only after issue #185's economic-domain remediation is implemented in the actual shared feed contract;
   - rerun Wealth Core and Sentinel certification outputs rather than repinning hashes blindly.

8. **SEC point-in-time work remains separate**
   - this research accepts the reconstructed Sharadar historical model;
   - it does not close the historical information-causality work tracked elsewhere.

---

## Research decision

The current leading hypothesis/challenger is:

> **Corrected Sharadar + frozen Wealth Core + existing Sentinel controller + a narrowly scoped, externally confirmed medium-fast systemic bridge across the fast/slow crisis dead zone.**

The key design objective is not a lower historical drawdown at any cost. It is to make crisis recognition **robust to small legitimate changes in portfolio composition while remaining sparse enough that ordinary volatility does not interrupt compounding**.

This finding should be preserved even if the eventual implementation uses a different mathematical form than a simple 30-35 percentage-point threshold.

---

## Related repository evidence

- Issue #185 — Sharadar financial-grade remediation, including the split-domain liquidity defect.
- Issue #175 — accepted historical model: modern reconstructed Sharadar market tape plus future point-in-time information work.
- `docs/sentinel-reference-implementation/sentinel_1p1_standalone.py`
- `docs/sentinel-reference-implementation/sentinel_1p1_summary.json`
- `docs/sentinel-reference-implementation/trailing_scorecard_vs_spy.csv`
- `docs/sentinel-handoff/00_README/FROZEN_SENTINEL_1P1_RULE.json`
- `docs/sentinel-handoff/06_RESEARCH_SOURCE_FRAGMENTS/systemic_shock/SHOCK_OVERRIDE_FORENSICS_REPORT.md`

## Bottom line

The corrected Sharadar data changed the 20-year reference enough to reveal that the frozen fast-crisis detector had a brittle threshold boundary.

The resulting ~-40% drawdown is mainly a **crisis-recognition timing failure**, not evidence that corrected Sharadar permanently destroys Sentinel's historical economics.

A sparse hardening of that detector restored approximately:

```text
CAGR       ~22.0%
Max DD     ~-24.0%
Ending     ~53.6x
```

on the corrected tape in the smoke experiment.

The highest-value next research is to validate that mechanism adversarially and structurally, not to search for another generic drawdown overlay.