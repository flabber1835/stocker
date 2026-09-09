# Wealth Core V5 / Sentinel EX3 impedance matching v1

Date: 2026-09-08

## Objective

Re-match the frozen Sentinel EX3 / Research Champion controller to Wealth Core V5 after the V5 affordability correction and the frozen 20-slot selection.

The experiment is research-only. Wealth Core V5 security selection, Median-5, 20-slot / 5% sizing, 10 bp cash reserve, next-valid-open whole-share sizing, one-session dividend lag, PIT corpus, execution timing, and transaction economics are frozen.

## Starting controller

Research Champion v1 baseline:

- LDRC_REC: 8 sessions
- LDRC_R20: -8.5%
- LDRC_V: +11.0%
- LDRC_DD: -10.0%
- divergence SPY floor: 0.0%
- full-recovery recent-leadership r40 floor: 0.0%
- divergence ceiling: 55%
- native FAST damaged breadth: 88%
- native healthy damaged ceiling: 63%

The E3 cross-surface release remains unchanged: positive recent-leadership persistence plus owned Wealth Core r20 > 0, recent leadership >= Wealth Core, and SPY >= Wealth Core.

## Mechanical diagnosis before the ten full replays

The frozen V5 20-slot daily tape shows three current divergence entries: March 2021, July 2021, and July 2026. The latter two sit close to the -8.5% recent-leadership r20 threshold and were economically useful defenses. The V5 tape does not support moving LDRC_R20, LDRC_DD, the SPY divergence floor, or the 55% ceiling in this first matching pass.

The clearest mismatch is recovery timing. During several native-Sentinel recovery episodes, owned Wealth Core V5 had already resumed positive behavior while the EX3 full-recovery route remained blocked because recent-leadership r40 had not yet crossed 0%. The most visible example is 2010: native Sentinel returned to full risk on 2010-08-10 while EX3 remained at zero exposure until 2010-09-21, missing a material Wealth Core rebound. Similar timing tension appears in later episodes, while the major 2008, 2015, 2020, and 2022 defensive episodes remain valuable.

A tape-prescreen that re-evaluated the exact EX3 state machine on the frozen V5 signals identified a broad local basin when the full-recovery r40 floor is relaxed to roughly -2% through -5%, especially near -4%. REC values 7-10 all remained viable around that basin. This prescreen selects where the expensive full replays are spent; final selection uses the full PIT economic replays.

## Ten-slot budget

Exactly ten full-PIT experiment arms are run in parallel:

1. `baseline`: REC 8, r40 floor 0%, FAST damaged 88%, healthy damaged 63%
2. `r40_m02_rec8`: REC 8, r40 floor -2%
3. `r40_m03_rec8`: REC 8, r40 floor -3%
4. `r40_m04_rec8`: REC 8, r40 floor -4%
5. `r40_m05_rec8`: REC 8, r40 floor -5%
6. `r40_m04_rec7`: REC 7, r40 floor -4%
7. `r40_m04_rec9`: REC 9, r40 floor -4%
8. `r40_m04_rec10`: REC 10, r40 floor -4%
9. `r40_m04_rec8_fast90`: arm 4 plus native FAST damaged threshold 90%
10. `r40_m04_rec8_healthy65`: arm 4 plus native healthy damaged ceiling 65%

All unlisted parameters remain frozen at Research Champion v1.

## Integrity gates

Every arm must:

- consume the same immutable canonical PIT package and 2006-07-31 through 2026-07-31 measurement window;
- reproduce the frozen V5 Wealth Core core-tape hash exactly;
- reproduce the frozen V5 Wealth Core transaction CSV hash exactly;
- reproduce the frozen V5 Wealth Core close-decision CSV hash exactly;
- preserve Median-5, 20 slots, 5% entry target, 10 bp reserve, next-open whole-share execution, total-cash V5 close affordability, and one-session dividend lag;
- change only the explicitly named controller seams;
- make the baseline arm reproduce the existing V5 + EX3 20-year metrics exactly.

## Selection criteria

Primary: broad robustness across adjacent REC/r40 arms, not the single highest CAGR.

Report 5/10/15/20-year CAGR, maximum drawdown, daily Sharpe, ending multiple, average allocation, exposure-level session counts, and transitions. A controller change is recommended only when the full replays preserve the defensive function while improving recovery matching across the local parameter neighborhood.
