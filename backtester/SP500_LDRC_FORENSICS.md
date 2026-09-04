# S&P 500 LD-RC forensic review

Date: 2026-09-03

## Verdict

The 12.12% 20-year S&P 500 LD-RC CAGR is **not explained by a broken LD-RC implementation**. The dominant cause is the move from the broad stock-selection / leadership domain into the much smaller S&P 500 domain.

The controlled attribution is:

| 20-year path | CAGR | Max drawdown | Sharpe | Ending multiple |
|---|---:|---:|---:|---:|
| Historical old authoritative target | 22.63% | -21.70% | 1.214 | 59.15x |
| Current corrected broad non-PIT diagnostic | 21.48% | -21.63% | 1.169 | 48.95x |
| Current corrected broad full-PIT diagnostic | 20.49% | -28.87% | 1.110 | 41.57x |
| S&P 500 best-effort PIT control | 12.12% | -21.98% | 0.866 | 9.86x |
| S&P 500 raw Wealth Core | 10.76% | -44.56% | 0.701 | 7.72x |
| SPY | 11.26% | -55.20% | 0.647 | 8.44x |

The broad non-PIT to broad full-PIT change costs about **0.99 percentage points of CAGR**. The broad full-PIT to S&P control change costs about **8.36 percentage points**. The raw Wealth Core opportunity-set change alone is **17.18% broad versus 10.76% S&P**, a **6.42-point loss** before the final risk overlay.

Therefore most of the missing return comes from the **universe/domain restriction**, not from PIT cleanup and not from an LD-RC coding failure.

## Why the S&P move changes more than the stock list

The retained strategy uses `TOP = 0.10` for the cross-sectional opportunity set. That top-decile population also feeds the recent-leadership R20/R40 breadth signal used by the risk controller.

Representative geometry:

| Session | Domain | Eligible | Top-decile / leadership population | Leadership overlap |
|---|---|---:|---:|---:|
| 2008-12-23 | S&P | 450 | 45 | 0 |
| 2008-12-23 | Broad | 1,005 | 101 | 7 |
| 2022-01-03 | S&P | 498 | 50 | 2 |
| 2022-01-03 | Diagnostic broad | 1,791 | 180 | 15 |

So `TOP=10%` is not universe-neutral. On S&P, Wealth Core chooses 25 holdings from roughly 45-50 top-decile names; in the broad reference it sees roughly 100-180. This reduces cross-sectional choice materially.

The risk controller also sees a different market. Over the aligned 20-year period:

- S&P versus broad leadership R20 correlation: **0.8195**
- leadership R40 correlation: **0.8342**
- R20 sign disagreement: **15.72% of sessions**
- R40 sign disagreement: **18.28% of sessions**
- native risk target differs on **490 sessions**
- native target correlation is only **0.505**

This means the S&P restriction changes both **what is owned** and **when the system goes defensive/re-enters risk**.

## LD-RC implementation and trading audit

The continuous S&P replay was checked independently for accounting and state-machine failures.

- 7,189 daily rows and 7,189 unique sorted sessions.
- No non-positive/NaN control NAV or raw Wealth Core equity.
- The 2005-12-30 endpoint matches the sealed 1998-2005 OOS run exactly, and the 2006-01-03 continuation has no state reset.
- On 6,057 sessions where allocation stayed fully invested with no allocation transition, the control return and raw Wealth Core return agree to a maximum absolute residual of **6.66e-16**.
- There are 32 control allocation transitions.
- Independent sum of absolute allocation changes is 21.1; at the modeled 0.1% transition cost this is **0.0211**, exactly equal to the engine's recorded transition-cost sum.
- An independent replay of the ControlLDRC state machine produced **zero control-reason mismatches**.
- Independent next-session desired-allocation comparison produced **zero allocation mismatches**.
- Independent effective-native timing comparison produced **zero timing mismatches**.

There is no forensic evidence of a silent LD-RC accounting error, one-day timing error, state-transition defect, or return-propagation bug causing the low S&P CAGR.

## What the risk overlay is doing

Over the 20-year S&P window, final control allocation is:

- 100%: 4,352 sessions
- 65%: 146 sessions
- 55%: 157 sessions
- 0%: 377 sessions

The final control differs from effective native allocation on only **250 / 5,032 sessions (4.97%)**. The system is therefore not simply sitting in cash continuously.

It protects capital very effectively during major breaks. The raw S&P Wealth Core has a 20-year max drawdown of **-44.56%**; final control reduces that to **-21.98%** and raises CAGR from **10.76% to 12.12%**.

There is, however, a real S&P-specific recovery drag. One clear example is 2023. Native risk returned to full risk on 2023-04-20, but ControlLDRC remained at zero until June because its recovery rule requires seven consecutive sessions with both leadership R20 and R40 positive, unless SPY R20 exceeds 11%. That delay missed a meaningful part of the rebound.

This is a **calibration/domain-transfer issue**, not evidence that the implementation is malfunctioning.

## Data-quality findings

The S&P PIT membership tape itself is stable and does not show catastrophic daily breaks.

Across the full continuous period:

- 7,189 market sessions
- 3,458,733 eligible constituent-sessions
- 128,664 excluded constituent-sessions
- excluded fraction: **3.59%**
- mapped daily constituents: min 460, median 476, max 504, ending at 503

The exclusion fraction declines materially with time:

| Year | Excluded fraction |
|---|---:|
| 2006 | 5.56% |
| 2015 | 2.47% |
| 2020 | 1.44% |
| 2025 | 0.49% |
| 2026 | 0.14% |

These unresolved historical identities can contribute some drag, especially near 2006. They cannot plausibly explain the majority of the broad-vs-S&P CAGR gap: the 10-year and 15-year S&P weakness remains large even in periods where identity coverage is already very high.

## Was the original ~20% expectation real?

Yes. The repository's earlier mandatory control gate recorded an expected 20-year authoritative result of **22.6302156206% CAGR**, Sharpe **1.213813871**, max drawdown **-21.6958215%**, and ending multiple **59.1542869x**.

The newly rerun frozen broad diagnostics confirm that the strategy still has approximately that class of economics on a broad opportunity set:

- corrected broad non-PIT diagnostic: **21.48% 20-year CAGR**
- corrected broad full-PIT diagnostic: **20.49% 20-year CAGR**

The old 22.63% exact value should not be treated as the current acceptance number because the corrected replay semantics and broad diagnostic geometry are not identical to that old harness. It does establish that the user's expectation of roughly 20%+ was grounded in actual prior results.

## Should LD-RC have been calibrated before the first S&P run?

**No.** The unchanged first S&P run was the correct experiment. It answered the portability question cleanly: the broad-domain strategy does not transfer unchanged to S&P 500 without a major loss in return.

Calibrating first would have hidden that fact and would have contaminated the clean S&P portability test.

Now that S&P is a serious production candidate, **yes, the S&P domain should be calibrated and validated explicitly before adopting it for production**. The calibration must cover the whole domain interaction, not only one LD-RC threshold.

## Recommended next experiment

Do not start with an unconstrained threshold optimization. First run a frozen-parameter 2x2 decomposition:

1. **Broad holdings + broad leadership signals** — reference.
2. **S&P holdings + broad leadership signals** — isolates the stock opportunity-set loss while preserving the original controller breadth semantics.
3. **S&P holdings + S&P leadership signals** — current S&P result.
4. **Broad holdings + S&P leadership signals** — optional reciprocal diagnostic.

Then run a **universe-normalized breadth test**. The current `TOP=10%` produces only ~50 S&P candidate/leadership names. Test a fixed population near the original broad semantics (approximately 100 names), and/or decouple the ownership candidate pool from the leadership breadth basket. This is domain normalization, not arbitrary curve fitting.

Only after those tests should recovery/divergence parameters be calibrated. Use coarse robust parameter regions, rolling/walk-forward validation, and explicit drawdown constraints.

The 1998-2005 S&P holdout has already been observed. It is consumed for any revised S&P parameter set. Future calibration cannot call that period untouched OOS; validation must use walk-forward splits and future paper trading.

## Production implication

Do not choose S&P eligibility for production solely for database-size and operational simplicity yet. The storage simplification remains attractive, but the present evidence says the opportunity-set cost is economically large. If S&P normalization/calibration cannot recover a substantial part of the lost return without sacrificing risk control, production should retain a broader eligibility universe or use an intermediate universe such as a larger liquid U.S. equity set.

## Reproducibility

Primary S&P continuous run:
- Actions run: `33828489539`
- artifact: `9921123829`
- artifact SHA-256: `69066a3ac496f797749514ccad3556600692008106a9accfc7ea364f8e018a4d`

Broad/S&P full-PIT forensic run:
- Actions run: `33830860739`
- head: `4a8cf83f34e5f4b4a9267a46d97a631f7132c104`
- artifact: `9921789402`
- artifact SHA-256: `2f8e747a7131840dba3a78a1e841a0fc06b35cb6612ecc7ae931dc9533558436`

Broad non-PIT diagnostic:
- Actions run: `33830830167`
- calculation completed and checksums passed
- workflow subsequently failed only in an optional report-formatting call because `tabulate` was not installed; this occurred after metrics had been printed and validated

Machine-readable evidence is stored in `backtester/evidence/sp500_ldrc_forensics_2026-09-03.json`.
