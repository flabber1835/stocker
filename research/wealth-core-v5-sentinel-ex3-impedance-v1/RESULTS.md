# Wealth Core V5 / Sentinel EX3 impedance matching — final results

Date: 2026-09-09 UTC

## Verdict

Wealth Core V5 has shifted the recovery timing of the stock-selection core enough that the existing Sentinel EX3 full-recovery confirmation is no longer impedance matched.

The robust configuration change is:

- **full-recovery recent-leadership r40 floor: 0.0% -> -5.0%**

Keep the rest of Research Champion / EX3 unchanged:

- LDRC_REC: 8 sessions
- LDRC_R20: -8.5%
- LDRC_V: +11.0%
- LDRC_DD: -10.0%
- divergence SPY floor: 0.0%
- divergence ceiling: 55.0%
- native FAST damaged breadth: 88.0%
- native healthy damaged ceiling: 63.0%

This recommendation changes one controller parameter. Wealth Core V5 remains frozen at Median-5, 20 holdings, 5% target entry weight, 10 bp close admission reserve, total-cash one-share affordability, next-valid-open whole-share sizing, and one-session dividend lag.

## Full-PIT result

The selected `REC=8 / r40=-5%` arm is exactly path-identical to the adjacent `REC=8 / r40=-4%` full replay.

| Window | Current EX3 CAGR | Selected CAGR | Current Max DD | Selected Max DD | Current Sharpe | Selected Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| 5y | 30.7740% | **31.0337%** | **-18.6471%** | -20.4196% | **1.3531** | 1.3466 |
| 10y | 26.2856% | **26.4739%** | -28.4492% | **-27.3755%** | 1.2474 | 1.2466 |
| 15y | 21.6889% | **22.2368%** | -28.4492% | **-27.3755%** | 1.1647 | **1.1776** |
| 20y | 20.7251% | **21.5572%** | -28.4492% | **-27.3755%** | 1.0946 | **1.1211** |

20-year ending multiple improves from 43.2496x to 49.6193x.

The 20-year delta is +83.2 bp/year CAGR, +1.07 percentage points of max-drawdown improvement, and +0.0265 Sharpe. The 5-year window has higher CAGR but a 1.77 percentage-point deeper maximum drawdown and a slightly lower Sharpe. That recent-window tradeoff is real and is caused primarily by earlier release of the 2021 divergence state.

## Ten-slot full-PIT matrix

All ten conceptual experiment slots completed successfully in GitHub Actions run `34319850800` at experiment head `54af0c9e50e4bf0c0d4242dafcf7fff0b75eb0f3`.

| Arm | REC | r40 floor | FAST damaged | Healthy damaged | 20y CAGR | 20y Max DD | 20y Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 8 | 0% | 88% | 63% | 20.7251% | -28.4492% | 1.0946 |
| r40_m02_rec8 | 8 | -2% | 88% | 63% | 20.7551% | -28.0917% | 1.0959 |
| r40_m03_rec8 | 8 | -3% | 88% | 63% | 21.2386% | -27.3755% | 1.1107 |
| r40_m04_rec8 | 8 | -4% | 88% | 63% | **21.5572%** | **-27.3755%** | **1.1211** |
| r40_m05_rec8 | 8 | -5% | 88% | 63% | **21.5572%** | **-27.3755%** | **1.1211** |
| r40_m04_rec7 | 7 | -4% | 88% | 63% | 21.6286% | -27.2237% | 1.1239 |
| r40_m04_rec9 | 9 | -4% | 88% | 63% | 21.4749% | -27.7796% | 1.1176 |
| r40_m04_rec10 | 10 | -4% | 88% | 63% | 21.5960% | -28.1587% | 1.1233 |
| r40_m04_rec8_fast90 | 8 | -4% | 90% | 63% | 21.5931% | -27.3755% | 1.1222 |
| r40_m04_rec8_healthy65 | 8 | -4% | 88% | 65% | 21.5155% | -27.3755% | 1.1189 |

The numerically highest single point is REC=7. It is not selected. REC=8 remains the mechanically centered recovery persistence value: REC 7-10 all remain in the same local economic basin, and moving REC to 7 advances four release sessions, including several sessions with negative same-day Wealth Core returns. The historical score at REC=7 is therefore treated as edge timing, not a new stable center.

FAST=90% is also not selected. Its 20-year gain over the pure r40 arm is only about 3.6 bp/year with unchanged max drawdown. Mechanically, raising the damaged-breadth threshold removes marginal FAST triggers in May 2010 and October 2018 that were followed by additional Wealth Core weakness, while retaining the February 2018 90%-damaged trigger that was followed by a strong rebound. The existing 88% setting remains the better defensive boundary.

Healthy damaged 65% is not selected. It changes very few native-Sentinel sessions and slightly weakens the 20-year economics relative to the pure r40 change.

## Why V5 moved the impedance

EX3 was originally stability-selected when the r40 floor was locally inert: -0.5%, 0%, and +0.5% produced the same path. Zero was therefore a sensible semantic center.

That property no longer holds with frozen Wealth Core V5 at 20 holdings.

The independent recent-leadership and SPY surfaces are effectively unchanged across the V4->V5 affordability correction. The Wealth Core/native-Sentinel state changed on hundreds of sessions because V5 changes the core book and the 20-holding choice changes the native damaged/green/recovery path. The relative phase between native Sentinel recovery and the independent recent-leadership confirmation surface therefore shifted.

On the frozen V5 20-holding tape, lowering the r40 floor to -4%/-5% restores exposure in four historical windows versus current EX3:

- 2010-08-11 through 2010-09-20: 28 sessions, 0% -> 100% exposure
- 2011-11-07 through 2012-01-19: 50 sessions, 0% -> 100% exposure
- 2021-06-11: one session, 55% -> 100% exposure
- 2021-09-21 through 2021-12-08: 56 sessions, 55% -> 100% exposure

The major 2008, 2015-16, 2020, 2022, and 2026 defensive behavior remains intact.

The key mechanic is the persistence counter. `full_streak` requires both positive recent-leadership r20 and recent-leadership r40 above the configured floor for every session in the streak. With the 0% floor, a still-slightly-negative r40 repeatedly resets the eight-session recovery clock even after owned Wealth Core and the 20-day leadership surface have recovered. Examples:

- August 2010: native Sentinel had returned to full risk while recent r20 was positive, but r40 was still about -0.9%. The current EX3 remained at zero exposure until late September.
- November 2011: current r40 was already positive, but earlier slightly-negative r40 values inside the required eight-session run kept resetting the current 0% persistence counter. The -5% configuration certifies the recovery earlier.
- September 2021: the same persistence counter also clears the divergence latch; lowering the floor clears that state earlier, producing the disclosed recent-window drawdown tradeoff.

## Stability of the new floor

Frozen-signal topology inspection shows the REC=8 allocation path is exactly unchanged across a broad lower-floor region beginning near -4% and extending to roughly -7.2%, with the next controller topology change below that range.

The -4% and -5% endpoints used here were both given full 20-year PIT replays and are exactly path/economics identical. -5% is selected because it lies inside the tested plateau and avoids sitting directly against the historical ~-4% streak boundary that creates the 2011 release.

## Parameters that stay frozen

The first-pass V5 tape does not support changing the divergence-entry parameters:

- LDRC_R20 remains -8.5% because the useful July 2021 and July 2026 divergence entries occur near -8.52% and -8.55%; materially tightening the threshold would remove those defenses.
- LDRC_DD remains -10%.
- divergence SPY floor remains 0%.
- LDRC_V remains +11%.
- divergence ceiling remains 55%.

The original broad stability work already identified V as a topology-sensitive boundary and REC=8 as the center of the 7-9 stable region. The V5 evidence gives a clear reason to change the recovery r40 floor and no equally strong reason to move those other dimensions.

## Integrity gates

Every successful arm:

- used the same immutable canonical PIT dataset hash `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`;
- used the same 2006-01-03 warm-up and 2006-07-31 through 2026-07-31 measurement window (5,032 sessions);
- reproduced the frozen Wealth Core V5 core-tape hash `3b40a23a7e499e0314f1d6e86b767fba648136758fdd106cdfd0ff27620b545f`;
- reproduced transactions hash `0e4828229c323ab029a5dfe49f258a3e2e379aee6b5e18169e72f9edc88652da`;
- reproduced close-decisions hash `d1f557bd139e3445538e3f94bce90fe296eba19450d939c4160fe0880e067724`;
- preserved V5 total-cash affordability, 20 slots, 5% target size, Median-5, 10 bp reserve, next-open whole shares, and one-session dividend lag;
- changed only its named Sentinel research seams.

The baseline arm additionally reproduced the existing V5+EX3 20-year CAGR, max drawdown, and Sharpe exactly.

The first two workflow launches on this research branch failed in harness staging before any portfolio replay. The corrected run `34319850800` is the ten-arm economic experiment and all 10/10 arms passed.

## Evidence artifacts

Run `34319850800`:

- baseline: `10092416123`
- r40 -2 / REC8: `10092399119`
- r40 -3 / REC8: `10091944508`
- r40 -4 / REC8: `10092241309`
- r40 -5 / REC8: `10092241074`
- r40 -4 / REC7: `10092404843`
- r40 -4 / REC9: `10092402812`
- r40 -4 / REC10: `10092392657`
- r40 -4 / REC8 / FAST90: `10092410290`
- r40 -4 / REC8 / healthy65: `10092067864`

## Architectural follow-up discovered during attribution

One controller mechanic deserves separate future research: the same `full_streak` / r40 condition currently governs both post-native recovery release and divergence-latch release.

A deterministic post-processing attribution on the already-generated full-replay tapes shows that applying the -5% floor only to post-native recovery while retaining the 0% floor for divergence release would capture most of the long-horizon recovery benefit while leaving the current 5y and 10y divergence behavior unchanged. This derived path was not one of the ten fresh full-PIT arms and is not the selected/certified configuration from this study.

The next architecture study should therefore test separate recovery and divergence confirmation floors. No additional backtester slot was spent on that hypothesis here.

## Scope

This is research-only. Production, main, the existing Research Champion branch, Wealth Core V5 economics, and Sentinel production behavior are unchanged.