# PR208 SEC-PIT issuer A/B — 30pp Simplified LD-RC invariant

**Status:** historical research replay evidence; no production activation.

## Invariant

This comparison holds the full corrected-volume Simplified LD-RC chain fixed. The five-session damaged-breadth acceleration is **30 percentage points** (`0.30`) and is not a variable in this A/B. Liquidity is `SEP.close * SEP.volume`; dividends are converted to the raw execution domain as `ACTIONS.value * SEP.closeunadj / SEP.close`; decisions apply at the next executable open; BIL is the defensive sleeve; allocation changes pay 10 bp one-way cost.

A is the present-day Sharadar `relatedtickers` issuer map and is intentionally future-leaking. B uses SEC Form 3/4/5 CIK evidence strictly before each decision session, with PR208's permaticker fallback when no causal SEC observation exists. Because the SEC corpus begins in 2006Q1 while Wealth Core needs a 1998-2005 warm-up, the primary causal A/B holds that unsupported pre-SEC warm-up identical and switches to PIT authority on **2006-01-04**, the first session on which a 2006-01-03 filing can be causal under the strict-before rule.

## Control gate

A reproduced the retained authoritative 30pp Simplified LD-RC fingerprint exactly:

- CAGR: **22.6302156206%**
- max drawdown: **-21.6958215101%**
- daily Sharpe: **1.2138138710**
- ending multiple: **59.1542869097x**

## Primary A/B result

| Window | A CAGR | B PIT CAGR | A MDD | B PIT MDD | A Sharpe | B PIT Sharpe | A multiple | B PIT multiple |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 5y | 27.7401647% | 27.7401647% | -20.8688990% | -20.8688990% | 1.323889 | 1.323889 | 3.403037x | 3.403037x |
| 10y | 27.2273956% | 27.2273956% | -21.6958215% | -21.6958215% | 1.318865 | 1.318865 | 11.123907x | 11.123907x |
| 15y | 22.7327212% | 22.7327212% | -21.6958215% | -21.6958215% | 1.238258 | 1.238258 | 21.626233x | 21.626233x |
| 20y | 22.6302156% | 22.6302156% | -21.6958215% | -21.6958215% | 1.213814 | 1.213814 | 59.154287x | 59.154287x |

Every metric delta is exactly zero. More strongly, there are **0 changed scheduled buys, 0 changed executed buys, and 0 changed executed sells**. The complete daily portfolio/LD-RC tape, LD-RC event tape, and ending-holdings files are byte-identical between A and B.

## Issuer decisions that changed

Legacy `relatedtickers` falsely blocked FOXA against held FOX on 2025-04-01 and 2025-04-08. PIT has SEC evidence for FOX but no prior SEC Form 3/4/5 observation for FOXA, so FOXA resolves to its own permaticker identity (`P:111125`). The false conflict therefore disappears. It still causes no trade change because FOXA's 21-session return was respectively **-2.1217%** and **-12.3245%**, so it fails the subsequent `r21 >= 0` admission rule anyway.

On 2025-12-22, both A and B block GOOGL against held GOOG. B proves the relationship causally as `CIK:0001652044`, based on the 2025-12-18 Form 4 observation (accession `0001193125-25-325042`, `2025q4_form345.zip`).

## Why the naive strict-precoverage result is rejected

Applying SEC mode all the way back to 1998 is not an issuer-PIT A/B: there is no SEC Form 3/4/5 corpus before 2006, so PR208 falls back to individual permatickers during the 1998-2005 warm-up. That immediately changes the book: on 1998-07-06 BRK.B is no longer blocked against pending BRK.A. By 2006-07-31 the starting shadow equity already differs ($334.60m A vs $329.99m strict-B), and later controller states diverge. Its 20y result (21.3492% CAGR / -22.4263% MDD / 1.1584 Sharpe / 47.9479x) is retained only as a sensitivity warning, not as the causal SEC correction result.

## Conclusion

For the corrected-volume **30pp Simplified LD-RC** lineage, replacing future-leaking `relatedtickers` with SEC PIT issuer authority over the period where SEC evidence exists changes some issuer-conflict classifications but **does not change a single trade, LD-RC state, or historical economic result** in the 2006-07-31..2026-07-31 replay.
