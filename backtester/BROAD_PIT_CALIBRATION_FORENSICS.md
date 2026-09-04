# Broad PIT calibration forensics

Date: 2026-09-03

## Scope

This is a diagnostic/calibration-readiness review of the frozen broad-universe full-stack PIT LD-RC replay. It does **not** select or activate any new strategy parameter.

Primary frozen benchmark:

- Actions run `33832270731`
- artifact `9922250531`
- frozen strategy source commit `c14f77b3c6c6fcc14cf00e8916d7968c853a5d6c`
- 20-year window `2006-07-31` through `2026-07-31`
- broad PIT control CAGR `20.4861%`
- max drawdown `-28.8704%`
- Sharpe `1.1097`

The central question is which parts of the machinery ceased to have the same meaning when historical metadata became causal/PIT.

## Executive verdict

The first PIT run does require recalibration, but the evidence does **not** support a wholesale retuning of Wealth Core or LD-RC.

The dominant problem is the **portfolio-health breadth domain feeding native Sentinel FAST/SLOW**:

1. PIT sector/issuer metadata changes `damaged`/`green` breadth and the held portfolio.
2. Strict-prior SEC SIC coverage is sparse and strongly time-varying; unknown sector authority becomes a singleton peer, weakening sector contagion.
3. The old FAST damaged-breadth thresholds were calibrated on a materially different sector/eligibility geometry.
4. This causes FAST to miss exactly the early 2010 and 2018 protection events that the non-PIT controller catches. SLOW then fires much later, after most of the drawdown, and sits out part of the rebound.
5. Recent-leadership R20/R40 is **not** the source of the PIT/non-PIT divergence: its threshold crossings are identical in the controlled comparison.

The correct calibration order is therefore:

**freeze PIT data/domain semantics -> normalize/stabilize breadth -> calibrate native FAST -> reassess SLOW -> then examine ramp/LD-RC.**

Do not start with LD-RC recovery thresholds or Wealth Core ranking parameters.

## 1. Wealth Core is not the primary problem

20-year controlled comparison:

| Path | CAGR | Max DD | Sharpe |
|---|---:|---:|---:|
| non-PIT raw Wealth Core | 16.97% | -44.46% | 0.859 |
| PIT raw Wealth Core | **17.18%** | -45.14% | **0.866** |
| non-PIT final control | **21.48%** | **-21.63%** | **1.169** |
| PIT final control | 20.49% | -28.87% | 1.110 |

PIT raw Wealth Core is slightly stronger on CAGR than non-PIT raw Wealth Core. The economically important degradation appears after the controller is applied.

The non-PIT controller improves raw Wealth Core by roughly 4.50 CAGR points and about 22.8 drawdown points. The PIT controller improves raw Wealth Core by roughly 3.30 CAGR points and about 16.3 drawdown points.

This means the first calibration target is **risk-state measurement/timing**, not stock ranking.

The PIT/non-PIT replay also remains close in trade count:

- non-PIT: 755 buys / 735 sells
- PIT: 747 buys / 727 sells
- split events: 10,435 in both
- dividends held: 1,357 non-PIT / 1,387 PIT

There is no evidence here of a gross trading/accounting failure.

## 2. PIT changes the breadth state, not recent leadership

Controlled PIT-vs-non-PIT comparison, Actions run `33834083222`:

- native target differs on **232** sessions
- final allocation differs on **208** sessions
- FAST signal differs on **9** sessions
- SLOW signal differs on **10** sessions
- control reason differs on **123** sessions

Threshold-crossing disagreements:

| Threshold | Disagreement sessions |
|---|---:|
| damaged 60% | 240 |
| damaged 75% | 149 |
| damaged 85% | 87 |
| green 20% | 92 |
| green 25% | 146 |
| recent leadership R20 <= 0 | **0** |
| recent leadership R20 <= -8% | **0** |
| recent leadership R40 <= 0 | **0** |

The first native-target divergence occurs on `2008-07-02`.

Recent leadership R20/R40 never diverges in this controlled metadata comparison. This cleanly localizes the main PIT calibration break to **held-portfolio health / sector contagion / the holdings path**, not the leadership return witness.

The largest annual final-control differences also occur in exactly the years where the breadth timing changes matter most:

- 2018: non-PIT -3.64%, PIT -18.88%: **-15.23 pp**
- 2010: non-PIT +38.38%, PIT +25.25%: **-13.13 pp**
- 2026 YTD: PIT +60.82%, non-PIT +48.93%: PIT **+11.89 pp**
- 2021: PIT trails by 5.27 pp

PIT is not uniformly worse. The problem is event timing, which is exactly what calibration should address.

## 3. The key FAST failure is the meaning of `damaged >= 0.85`

The retained FAST rule requires, among other conditions, damaged breadth at least 85%.

That threshold is extremely sensitive because damaged breadth is measured on roughly 20-25 held positions and includes sector-contagion amber status.

### 2008

On `2008-07-02`:

- non-PIT damaged: `19/22 = 86.36%` -> FAST fires
- PIT damaged: `19/23 = 82.61%` -> FAST does not fire

PIT eventually reaches a FAST trigger on `2008-07-08`, so this becomes a delay rather than a complete miss.

### 2010

On `2010-05-07`:

- non-PIT damaged: effectively `21/24 = 87.5%` -> FAST fires
- PIT damaged: `19/24 = 79.17%` -> FAST does not fire

The PIT path remains exposed. Its later SLOW decision is `2010-06-29`, by which time Wealth Core drawdown is already about `-20.09%`.

From that late SLOW decision, raw Wealth Core then returns:

- +2.76% over 20 sessions
- +2.27% over 40 sessions
- **+11.11% over 60 sessions**

So PIT misses the early crash-response path and then becomes defensive near the rebound.

### 2018

On `2018-10-11`:

- non-PIT damaged: `17/20 = 85%` -> FAST fires
- PIT damaged: `16/20 = 80%` -> FAST does not fire

One holding's damaged classification is enough to move the controller from protection to full risk.

PIT does not enter zero-risk SLOW until the decision on `2018-12-19`, with Wealth Core already at about `-28.10%` drawdown.

From that late SLOW decision, raw Wealth Core returns:

- +4.31% over 20 sessions
- +8.58% over 40 sessions
- **+10.53% over 60 sessions**

This is the clearest reason the 20-year PIT max drawdown is `-28.87%`: the early FAST event was missed because PIT damaged breadth no longer crossed the old 85% calibration boundary.

### 2020 control witness

On `2020-02-27`, both PIT and non-PIT damaged breadth are 100%; FAST fires in both. The PIT machinery protects the COVID break effectively.

Therefore FAST logic itself is valuable. The calibration problem is the **breadth thresholds under the new PIT measurement domain**.

## 4. SLOW looks late, but much of that is downstream of missed FAST

PIT SLOW decisions and subsequent raw Wealth Core returns:

| SLOW decision | WC DD at decision | +20 sessions | +40 | +60 |
|---|---:|---:|---:|---:|
| 2010-06-29 | -20.09% | +2.76% | +2.27% | **+11.11%** |
| 2011-10-03 | -21.98% | **+8.42%** | +9.72% | +10.93% |
| 2018-12-19 | -28.10% | +4.31% | +8.58% | +10.53% |
| 2022-05-17 | -19.62% | -4.04% | **-12.15%** | -9.29% |

Three of four PIT SLOW decisions are followed by strong rebound returns. The 2022 SLOW episode is genuinely useful and protects a continuing bear phase.

This does **not** support simply weakening or removing SLOW. The correct sequence is:

1. repair/recalibrate FAST breadth so early 2010/2018 protection is evaluated correctly;
2. rerun the event set;
3. only then calibrate SLOW entry/hysteresis to distinguish a continuing bear such as 2022 from a late-bottom signal such as 2011/2018.

The production/replay convention that SLOW exits on the sixth healthy observation is intentional; it is not an off-by-one bug.

## 5. PIT SEC sector coverage is too nonstationary for blind threshold tuning

A dedicated metadata coverage audit was run as Actions `33834404728`.

Important caveat: this diagnostic projects strict-prior metadata onto the active current-TICKERS common/listing population, not the exact daily eligible or held portfolio. Liquid selected names may have better coverage. The time trend is still material enough to be a calibration blocker.

Strict-prior SIC coverage:

| Snapshot | SIC coverage |
|---|---:|
| 2006-07-31 | **0.0%** |
| 2010-06-30 | **6.7%** |
| 2011-10-03 | 53.6% |
| 2015-08-25 | 63.5% |
| 2018-12-19 | 68.3% |
| 2020-02-28 | 69.0% |
| 2022-05-17 | 66.5% |
| 2025-12-31 | 76.0% |
| 2026-07-31 | 85.3% |

The PIT FF12 model intentionally maps missing sector authority to `UNKNOWN:<security_id>`.

That has an economically important consequence: an unknown security becomes its own singleton sector. The `sector_red_fraction >= 0.50` contagion condition is then no longer comparable to the old current-sector version. As historical SIC coverage improves, the effective definition of damaged breadth changes through time even though the threshold remains fixed.

Missing strict-prior CIK similarly creates a singleton issuer, weakening historical issuer-family duplicate blocking.

**Do not optimize damaged=85%, damaged=75%, green=20/25%, or sector-red=50% against this moving metadata-coverage surface and call the result calibrated.**

Before numerical calibration, choose one stable approach:

- recover stronger causal sector/issuer history;
- define an explicitly coverage-aware PIT breadth calculation;
- use a taxonomy-robust causal peer construction such as the already-designed prior-only dynamic-peer experiment;
- or deliberately remove the sector-contagion component and calibrate a new PIT individual-breadth definition.

The choice is architectural/data-domain calibration. Threshold fitting comes afterward.

## 6. FAST acceleration is also domain-dependent

There is a real strategy-version difference:

- retained broad replay FAST damaged-breadth delta5 threshold: `0.30`
- frozen main Sentinel 1.1 rule: `0.40`

A one-variable semantic alignment experiment changed **only** `0.30 -> 0.40` on the same PIT data.

Actions run `33834321035`:

- FAST signal changes: 10 sessions
- native target changes: 87 sessions
- final allocation changes: 104 sessions

Results:

| Window | PIT FAST .30 | PIT FAST .40 | Delta |
|---|---:|---:|---:|
| 5y | 27.64% | 27.64% | 0.00 pp |
| 10y | 24.82% | 24.82% | 0.00 pp |
| 15y | 20.86% | 19.82% | **-1.04 pp** |
| 20y | **20.49%** | **18.85%** | **-1.64 pp** |
| Max | 20.07% | 18.89% | -1.18 pp |

20-year max drawdown also worsens from `-28.87%` to `-29.35%`.

This proves that blindly importing the old/main `.40` parameter into PIT is wrong. It had meaning in the old breadth domain; in the current PIT domain it is too restrictive.

The retained `.30` performs better, but that does **not** make `.30` the calibrated PIT answer. It means the acceleration threshold must be recalibrated only after the PIT breadth definition is stabilized.

## 7. Current LD-RC v3 is not the first calibration target

The current Simplified LD-RC v3 parameters on main match the retained controller family: 55% divergence ceiling, Wealth Core DD -10%, recent leadership R20 -8%, seven-session recovery, SPY V-rebound >11%.

The existing alternative recovery arm B provides useful sensitivity evidence:

- 20-year Control CAGR: 20.49%
- 20-year B CAGR: about **20.83%**
- same 20-year max drawdown
- Control has slightly better Sharpe and wins the 5-year/10-year comparisons

There is a few-tenths-of-a-point recovery-timing opportunity, but it is far smaller than the 2010/2018 breadth-state problem.

Only three post-2006 LD-RC divergence entries occur in this PIT path. That is too small a sample to confidently tune divergence thresholds now.

LD-RC should therefore remain frozen during the first native-breadth calibration pass.

## 8. Recovery ramp deserves a later sensitivity pass

The native ramp after severe episodes uses 55% and 65% exposure stages.

Raw Wealth Core is positive during most historical ramp segments, so the ramp often gives up rebound return. The same ramp is useful in portions of 2022 where the bear market resumes.

This is a legitimate calibration area, but entry classification must be corrected first. Otherwise ramp parameters are being fitted to episodes that should sometimes have entered through a different FAST/SLOW path.

Priority: after FAST and SLOW.

## 9. Broad-universe geometry itself must be frozen

The broad replay intentionally disables the exchange gate because a current TICKERS snapshot cannot prove historical exchange point-in-time.

The retained `TOP=10%` rule therefore operates on a larger and changing eligible population:

- 2008-12-23: 1,005 eligible -> leadership/candidate population **101**
- 2022-01-03: 1,791 eligible -> population **180**

The older authoritative 2022 control fingerprint expected a leadership population around **96**.

The portfolio still holds 25 positions, so 25 positions represent about one quarter of the 2008 top-decile pool but only about one seventh of the 2022 pool.

This changes:

- stock-selection selectivity;
- the statistical smoothness of recent-leadership R20/R40;
- recovery-confirmation behavior;
- comparability to the old controller calibration.

Before calibrating LD-RC or leadership thresholds, explicitly freeze what the broad PIT eligibility domain is supposed to be. Options include recovering causal exchange/security-type authority or deliberately accepting the larger exchange-agnostic liquid-SEP domain as the new production/research universe.

Fixed nominal liquidity gates (`$20m` ADV20 and `$5m` daily dollar volume) also span nearly three decades without normalization. They contribute to a time-varying eligible population and should be examined during universe calibration.

## 10. Stop/review/cooldown: no evidence yet to retune

Current Wealth Core mechanics include:

- 30% trailing stop from peak (`STOP_RET=0.70`)
- age-119 review
- 21-session cooldown
- 4% entries
- 25 slots

Raw PIT Wealth Core remains strong at 17.18% CAGR over 20 years. The current artifact does not emit a complete trade ledger with sell reason, per-trade return, review outcome, cooldown opportunity cost, or candidate-rank displacement.

Therefore the correct conclusion is **diagnostic gap**, not “these values need changing.”

Before considering calibration of stop/review/cooldown, instrument and retain:

- every entry/exit and reason;
- entry/open basis and peak;
- stop distance at exit;
- age-119 review state;
- candidate rank at review and exit;
- 21-session post-exit counterfactual return;
- cooldown blocks and replacement selected.

Do not touch these parameters based on the present aggregate curve.

## 11. Execution/capacity is a separate calibration problem

The research book starts at `$100m`, uses 4% entries and a flat 10 bps transaction-cost model. Eligibility permits ADV20 as low as `$20m`.

At the initial `$100m` book size, a fresh 4% allocation is `$4m`, which can be 20% of the minimum accepted ADV. As the simulated NAV grows, nominal order size grows further. The benchmark does not impose a full market-impact/participation execution model.

So the 20.49% result is useful for strategy economics but should not be interpreted as a capacity-certified `$100m` live result.

For the user's actual smaller account this may be economically minor, but production capacity/slippage should be calibrated separately from signal thresholds.

## Calibration priority

### P0 — before numerical parameter optimization

1. **Freeze the broad PIT eligibility domain.** Decide exchange/security-type semantics and whether the 1,791-name 2022 eligible set is intentional.
2. **Stabilize sector/issuer authority.** Improve historical causal metadata or define a coverage-aware/taxonomy-robust breadth rule.
3. **Create an explicit PIT controller parameter version.** Main's `.40` FAST acceleration is not portable; retained `.30` is not yet an approved PIT calibration.
4. **Add calibration telemetry.** Emit damaged denominator/count, amber cause by holding, sector-known/unknown status, ddam5/r5/r10/volacc, native state, trade ledger and sell reasons.

### P1 — first actual parameter calibration

1. FAST `damaged` level threshold (`0.85` in the old domain).
2. FAST damaged-breadth 5-session acceleration threshold (`0.30/.40` domain issue).
3. The sector-contagion `red fraction >= 0.50` interaction.
4. Green-breadth threshold only after the held-path/sector definition is frozen.

Use event-level objectives as well as CAGR: early protection, maximum loss avoided, false defensive entries, days to entry, rebound missed, and worst drawdown.

### P1/P2 — then SLOW

Re-evaluate SLOW damaged 75%, duration, path-return and recovery hysteresis after FAST is fixed. Explicitly force the calibration to distinguish:

- 2010/2011/2018 late-bottom cases;
- 2022 continuing-bear case.

### P2 — recovery/ramp/LD-RC

- 55/65 native ramp timing;
- LD-RC recovery confirmation;
- divergence latch, possibly considering longer-horizon recent leadership state.

Do not optimize these first.

### P3 — only with better instrumentation

- 30% stop;
- age-119 review;
- 21-session cooldown;
- turnover/cost assumptions;
- execution participation/capacity.

## Calibration-window policy

If/when calibration begins:

- use **2006-07-31 onward** for development/calibration;
- do not use 1998-2005 to select parameters;
- after parameters and architecture are frozen, use 1998-2005 as a locked historical check;
- recognize that 1998-2005 is not pristine because its baseline results have already been observed;
- future paper trading remains the genuinely new OOS evidence.

## Reproducibility

Baseline broad PIT:
- run `33832270731`
- artifact `9922250531`
- SHA256 `e842bbf79615a022ea750019ab997445e5ab61e803a947647f8c4255d1919aae`

PIT vs non-PIT geometry:
- run `33834083222`
- artifact `9922813532`
- SHA256 `e948dee28a2726cfb75d083c5add14c81309df6e1a0749df459089fd3c9173b9`

FAST `.30 -> .40` semantic alignment:
- run `33834321035`
- artifact `9922907749`
- SHA256 `60b724f8d0631500124e69629820b2f69cf5411797d28b685ced21ccb458cba7`

PIT metadata coverage:
- run `33834404728`
- artifact `9922783105`
- SHA256 `3e4ae92495f7f757495bf00ae58ac33053e453c3e3503e7ebd1ef2a760b5a772`

Machine-readable conclusions are in `backtester/evidence/broad_pit_calibration_forensics_2026-09-03.json`.
