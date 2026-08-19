# Sentinel Concordance — recovery-witness research

**Status:** research candidate / smoke-test evidence, not certification  
**Date:** 2026-08-18  
**Proposed candidate name:** **Sentinel Concordance**  
**Do not call this Sentinel 1.2 yet.** Reserve a versioned production name until adversarial validation, causal revalidation and exact-path certification are complete.

## Executive conclusion

Correcting Sharadar liquidity semantics exposed two distinct weaknesses in the previously frozen Sentinel path:

1. the fast-crisis detector had a brittle damaged-breadth acceleration cliff that missed the 2008 crisis on the corrected Wealth Core population;
2. even after hardening the fast detector, Sentinel still allowed Wealth Core to certify its own recovery too early.

The second point is the new result captured here.

The strongest current research architecture is:

> **one alpha engine, multiple independent thermometers, one allocation authority.**

Wealth Core remains the capital-producing alpha engine. Independent shadow books / opportunity-set witnesses do **not** receive capital. Their job is to provide evidence that the environment has truly recovered before Sentinel restores full risk.

The working name **Sentinel Concordance** refers to this requirement for agreement between the controlled book and independent recovery witnesses.

## Performance chain

Standard trailing 20-year window: **2006-07-31 through 2026-07-31**.

| Candidate | CAGR | Max drawdown | Daily Sharpe | Ending wealth / comment |
|---|---:|---:|---:|---|
| Former Sharadar / frozen Sentinel reference | 22.09% | -21.96% | ~1.17 | 54.20x |
| Corrected Sharadar, frozen Sentinel logic | 20.29% | -39.93% | ~1.06 | 40.23x |
| Corrected Sharadar + hardened fast-crisis sensor | 22.02% | -24.02% | ~1.15 | 53.55x |
| + leadership-population recovery witness | ~22.96% | -22.60% | ~1.22 | broad overlap plateau |
| + conservative three-shadow recovery consensus | 22.49% | -23.53% | ~1.18 | improves all standard trailing CAGR windows |
| **Sentinel Concordance research champion: durable independent recovery witness** | **23.24%** | **-22.60%** | **~1.22** | current research high-water mark |

The 23.24% value is a **research champion**, not a certified claim and not a parameter to freeze solely because it is the highest historical CAGR.

## Why the Sharadar correction mattered

The corrected liquidity calculation changes which securities pass the daily-dollar-volume / ADV gates. That changes Wealth Core membership, which in turn changes holding-level breadth and the crisis/recovery evidence seen by Sentinel.

The prior fast-crisis detector required, among other conditions, damaged breadth to worsen by at least 40 percentage points in five sessions. Under the former population, July 2008 crossed that threshold. Under corrected Sharadar it narrowly did not, despite overwhelming market and portfolio stress. This created a medium-speed crisis dead zone between the fast detector and the slower prolonged-stress path.

Hardening the fast sensor repaired most of the 2008 deterioration and restored the corrected 20-year result to roughly **22.02% CAGR / -24.02% max drawdown**.

See `docs/corrected-sharadar-drawdown-forensics.md` for the full 2008 root-cause analysis.

## New insight: Wealth Core can make itself look recovered

Keeping an immutable Wealth Core shadow was already superior to using the live de-risked portfolio as the recovery thermometer. But it still leaves one subtle circularity:

> Wealth Core is both the thing being controlled and the thing measuring whether it has recovered.

Wealth Core continuously adapts its holdings. Losers exit, replacements enter, and the surviving current book can regain positive 20-day returns even while the broader opportunity set that normally supplies Wealth Core's alpha remains weak.

This can create premature re-risking.

### December 2008 example

On **2008-12-23**, canonical corrected Wealth Core looked superficially healthy enough to approach recovery:

- Wealth Core 20-day return: **+0.55%**

But independent opportunity-set / shadow witnesses were still negative:

- durable independent shadow r20: **-1.58%**
- durable independent shadow r40: **-7.52%**
- raw leadership shadow r20: **-3.15%**
- defensive shadow r20: **-0.48%**

The book had improved; the broader opportunity set had not.

### January 2022 example

A similar divergence appeared around **2022-01-03**:

- Wealth Core r20: **+2.77%**
- durable independent shadow r20: **-1.57%**
- raw leadership shadow r20: **-7.15%**
- defensive shadow r20: **-0.50%**

Again, the adaptive book could look healthy while independent witnesses still described a poor environment.

## Sentinel Concordance recovery rule

The strongest simple research rule was conceptually:

```text
RISK-OFF:
    unchanged; Sentinel reductions remain authoritative

RISK-ON:
    native Sentinel recovery conditions
    AND
    durable independent witness r20 > 0
    AND
    durable independent witness r40 > 0

EXCEPTION:
    permit recovery during an unmistakably strong broad-market V rebound
```

The important asymmetry is intentional:

- **risk-off can happen quickly** on strong crisis evidence;
- **risk-on requires concordance** between the controlled book and an independent representation of the opportunity set.

## V-rebound exception and plateau

A strong-SPY-rebound exception is necessary so the independent witness does not keep Sentinel underinvested during exceptionally fast broad-market recoveries such as 2020.

Observed research neighborhood:

| SPY 20-day rebound exception | 20y CAGR | Max DD |
|---:|---:|---:|
| 8% | 23.24% | -22.60% |
| 9% | ~22.95% | -22.60% |
| 10% | ~22.95% | -22.60% |
| 11% | ~22.95% | -22.60% |
| 12% | ~22.90% | -22.60% |

Interpretation:

- the drawdown result is stable across a broad 8-12% neighborhood;
- 8% is the historical CAGR maximum in this smoke-test family;
- **do not select 8% merely because it is the maximum**;
- a central value such as ~10% may be more defensible if the architecture survives adversarial validation.

## Sparsity of the improvement

The candidate does not improve by trading more.

Research comparison:

- corrected+hardened baseline allocation transitions: **22**
- Sentinel Concordance candidate transitions: **22**
- allocation differs on only a small minority of the 5,032 sessions in the 20-year window

The gain comes from changing the timing of existing recovery transitions rather than adding a high-frequency tactical overlay.

Important relative-gain episodes included late-2008/early-2009, 2010, 2011 and early-2022 recoveries.

## Rolling-start behavior

The recovery-witness comparison was repeated from multiple historical starting points.

Observed result in the research harness:

- **15 / 15 starts improved CAGR**
- **15 / 15 starts had maximum drawdown equal or better**

This is still in-sample historical evidence, because the same overall corpus underlies the tests. It should be treated as robustness evidence, not as true out-of-sample validation.

## Revalidation of prior Wealth Core stock-selection experiments

The corrected-Sharadar work did **not** reopen the case for changing Wealth Core's core selector.

Wealth Core's durable structure remains:

- 6-1 momentum defines leadership;
- recent momentum remains positive;
- formation volatility penalizes unstable leaders;
- a durable momentum / volatility balance chooses the winner.

Parameterized research variants around that design were materially worse.

Using an action-normalized comparative harness:

| Selection variant | CAGR | Max DD | Interpretation |
|---|---:|---:|---|
| durable Core control | ~21.34% | ~-24.75% | comparison control |
| weaker volatility penalty (`vol^0.75`) | ~18.86% | ~-39.70% | decisively worse |
| stronger volatility penalty (`vol^1.50`) | ~10.47% | ~-38.86% | decisively worse |
| much faster 63-session momentum | ~-0.29% | ~-68.64% | catastrophic |

These absolute values are **not** substitutes for the certified Sentinel metrics; they came from a comparative corporate-action-normalized research harness. The relative direction is the important result.

### Raw-momentum false-alpha trap

A naive raw-momentum reconstruction briefly produced an absurd ~55% CAGR. It was rejected immediately as a forensic alarm.

Root cause: the reconstructed book held **DRYS**, and a Sharadar ACTIONS dividend row around 2007-10-11 contained a very large split-adjusted-domain `value`. Feeding that value through a raw per-share dividend path created a fake one-day portfolio explosion.

Lesson:

> Any future stock-selection comparator must use the same audited corporate-action domain semantics as canonical Wealth Core before headline performance is considered meaningful.

Do not resurrect the ~55% raw-momentum result. It is not alpha.

## Revalidation of the old multiple-shadow experiment

The earlier four-book ensemble used variants such as:

- Core
- Fast
- Trend Quality
- Defensive

As direct investments, the alternatives were inferior to Core. Historical standalone research had approximately:

| Shadow | CAGR | Max DD |
|---|---:|---:|
| Core | 18.16% | -41.16% |
| Fast | 6.36% | -61.08% |
| Trend Quality | 9.47% | -43.66% |
| Defensive | 2.99% | -30.62% |

This previously led to the correct conclusion that capital should not be rotated aggressively among the shadows.

The new interpretation is different:

> **A poor investment can still be a useful independent sensor.**

Alternative shadows need only be behaviorally different enough from Core to provide independent evidence about whether the opportunity set has healed.

A conservative three-shadow recovery consensus produced approximately:

- **22.49% 20-year CAGR**
- **-23.53% max drawdown**
- improved 5-, 10- and 15-year CAGR versus corrected+hardened baseline

It did not beat the single durable witness historically, but it may be architecturally more robust because no single alternative book owns the recovery decision.

## Revalidation of emerging leadership

The previous emerging-leadership work discovered real information before using the wrong actuator.

The overlap between long-horizon leadership and recent 21-day leadership collapsed sharply around the 2021-2022 regime change. Using that signal to **buy emerging stocks** hurt long-run CAGR badly.

Repurposing the same information as a **recovery witness** worked much better:

> leadership has not normalized -> do not yet trust Wealth Core's apparent recovery

Across a broad recent-vs-established leadership overlap neighborhood of roughly 25-40%, the research path was around:

- **22.9-23.0% CAGR**
- **-22.6% max drawdown**

and improved the standard trailing windows.

This is another example of the same pattern:

> **the sensor was useful; the original trading actuator was wrong.**

Leadership overlap also tended to identify the same problematic recoveries as the durable independent witness, which makes it useful as corroboration rather than as another parameter to optimize.

## Stop-density revalidation

The previous shadow-book / stop-density experiment correctly identified clustered stop failures as evidence of portfolio stress, but using it as another de-risking actuator behaved like expensive insurance.

On corrected+hardened Sentinel, thresholds around 5-9 stops in 20 sessions either:

- fired too often and reduced CAGR, or
- became redundant once the hardened systemic detector was already present.

Conclusion:

- retain stop-density as diagnostic evidence;
- do not add another capital-control path based on it at this stage.

## Position-level survivor/firewall work

The earlier Elastic Survivor Firewall experiment remains directionally valid:

- modestly trimming a few damaged positions can reduce concentrated-damage drawdown;
- aggressive removal / vacancy creation destroys too much compounding;
- broad systemic drawdowns cannot be solved position-by-position;
- position-level intelligence is more useful as a **classifier of drawdown type** than as a large liquidation engine.

This remains a secondary research branch, not the current performance leader.

## 2021 momentum/strategy-specific drawdown

After repairing 2008 and improving recovery, the remaining worst drawdown moved to roughly the 2021 momentum/rotation episode, around **-22.6%**.

This episode was structurally different from 2008:

- Wealth Core deteriorated materially;
- independent momentum/opportunity witnesses were weak;
- SPY remained comparatively healthy.

A separate strategy-specific / momentum-crash defensive state was tested. Reasonable variants did **not** improve the -22.6% frontier and generally reduced CAGR.

Interpretation:

> not every ~20% Wealth Core drawdown should be engineered away. Some drawdown is the cost of harvesting the underlying momentum/durable-winner premium.

Do not add a new defensive state merely to remove the 2021 drawdown unless a fundamentally new causal signal emerges.

## Ecological succession / niche experiment

This remains the most interesting unfinished Wealth Core-side idea.

Prior ecological research showed that the 2022 Energy takeover contained real cross-sectional information and could materially improve that year, but the niche actuator stayed active too frequently and siphoned capital from the superior Core engine, reducing long-run CAGR.

The unresolved idea is to use **fitness-gap / population-takeover evidence** to activate a very sparse bounded sidecar only when the challenger population is unusually dominant, and to hibernate it again when that gap closes.

The original detailed simulator artifacts are not all retained in directly reusable form. This branch should therefore be reconstructed carefully from the retained research evidence rather than approximated and treated as the original experiment.

## Current research ranking

### 1. Independent recovery witnesses — highest priority

Best current historical research result:

- **~23.24% CAGR**
- **~-22.60% maximum drawdown**
- **~1.22 daily Sharpe**

The broader, more defensible neighborhood is approximately **22.9-23.2% CAGR with ~22-23% max drawdown**.

### 2. Multi-shadow concordance — high architectural value

Even if a single durable witness has the best historical CAGR, a small ensemble of independent thermometers may be more robust under perturbation and data/vendor changes.

### 3. Ecological fitness-gap sidecar — unfinished

The information signal appears real; the sparse actuator remains unresolved.

### 4. Do not prioritize

Current evidence continues to reject or deprioritize:

- faster raw momentum;
- stronger/weaker volatility tilts around Core;
- generic portfolio stops;
- stop-density as another de-risking actuator;
- forced universal slow recovery ramps;
- aggressive position contraction;
- alternative shadows as capital allocators;
- separate 2021 factor-crash state without a new causal signal.

## Proposed architecture

```text
                     Wealth Core
                  ONE ALPHA ENGINE
                         |
                    full shadow
                         |
        +----------------+----------------+
        |                |                |
 durable-opportunity  leadership       alternative
     witness          replacement      shadow consensus
        |                |                |
        +-------- RECOVERY EVIDENCE ------+
                         |
              SENTINEL CONCORDANCE
                ONE ALLOCATION AUTHORITY
                         |
                  Wealth Core / BIL
```

The essential rule is:

> **The controlled book may contribute evidence for recovery, but it may not certify its own recovery by itself.**

## Naming recommendation

### Preferred: Sentinel Concordance

Why:

- describes the actual innovation: independent agreement before re-risking;
- does not imply another independent trading strategy;
- fits the existing Sentinel identity;
- avoids prematurely calling the research candidate “1.2”.

Recommended nomenclature during research:

> **Sentinel Concordance RC**

or more formally:

> **Sentinel Concordance — Recovery Witness Candidate**

Only after adversarial testing and certification should a versioned production identity be considered, e.g. `Sentinel 1.2 Concordance` if the architecture survives unchanged.

Other acceptable names considered:

- **Sentinel Witness** — very descriptive, but singular and less expressive of agreement;
- **Sentinel Consensus** — clear, but generic and could imply voting/majority logic that may not be the final rule;
- **Sentinel Accord** — concise, but less technically self-explanatory;
- **Sentinel Parallax** — captures independent viewpoints, but is more metaphorical than operational.

**Recommendation: keep “Sentinel Concordance”.**

## Required validation before promotion

Before this candidate is allowed to replace frozen Sentinel research logic:

1. adversarial perturbation of individual holdings and breadth denominators;
2. alternate legitimate Sharadar populations / vendor corrections;
3. leave-one-crisis-out testing;
4. rolling-origin and untouched-forward testing;
5. parameter-family / PBO analysis of the V-rebound exception and witness horizons;
6. exact next-open execution replay through the trusted ledger;
7. transaction-cost and slippage sensitivity;
8. independent implementation parity for witness calculations;
9. confirmation that witness inputs are causally available at the decision time;
10. re-run the standard 5/10/15/20-year scorecard and crisis decomposition;
11. only then re-freeze strategy identity and recertify hashes.

## Current conclusion

The corrected-Sharadar investigation has not produced evidence that Wealth Core needs a more aggressive stock selector.

Instead it has produced a more general design principle:

> **Keep the strongest alpha engine stable. Improve performance by making risk restoration depend on independent evidence about the opportunity set.**

That principle currently raises the historical research frontier from roughly **22.02% / -24.02%** to a neighborhood around **23% CAGR / 22-23% max drawdown**, without leverage and without increasing allocation-transition count.
