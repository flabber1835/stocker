# Baseline calibration audit — issue #241

Research-only. This file corrects the interpretation of the retained PIT-sector experiment; it does not change `main` or production strategy authority.

## Executive finding

The retained **18.48%** SEC SIC→FF12 result is **not** the current **22.63% Simplified Concordance LD-RC system with only sector changed to PIT**.

The decisive control is already in `results-summary.csv` at the authoritative 30pp fast threshold:

- inherited #241 base + **current Sharadar sector**: **18.43172395% CAGR**
- same inherited base + **causal SEC SIC→FF12**: **18.47948391% CAGR**
- sector-only delta on that fixed base: **+0.04775996 percentage points/year**

Therefore the apparent `22.6302% -> 18.4795%` loss of **-4.1507 pp/year cannot be attributed to PIT sector**. Almost the entire discrepancy already exists before the sector substitution.

The correct label for 18.48% is:

> SEC-FF12 sector on the inherited #241 true-PIT research shadow/controller-input tape.

It must not be labeled:

> current deployed Simplified LD-RC with only sector made PIT.

## Where the wrong comparison entered

`sector_market_experiment.py` does exactly what its local experiment intended: it holds its supplied Wealth Core shadow/controller inputs fixed and recomputes damaged breadth under alternative peer definitions. But its supplied base is:

`/mnt/data/pit_exp_currentcat_ff12_out/sentinel_1p1_daily.csv`

That is **not** the authoritative 22.6302156% current-system control tape. It is an already-modified PIT research tape inherited from the earlier reconstruction.

The retained `true-pit-40pp-sensitivity.json` describes that earlier lineage as:

> `category-free SEP quantitative universe, latest-date SEC PIT issuer identity, strict-before SEC SIC->frozen FF12 sector, corrected raw-dollar-volume economics`

So #241's sector A/B is internally valid as a peer-definition experiment, but its baseline is unsuitable for measuring the economic cost of changing sector in the current deployed strategy.

## Confirmed upstream contributor: issuer pre-coverage handling

PR #208 established the correct SEC issuer A/B boundary:

- keep the unsupported 1998–2005 warm-up identical to the current strategy;
- switch to SEC PIT issuer authority on 2006-01-04 when evidence exists.

That causal A/B changed **zero trades and zero performance** and preserved the authoritative 20Y **22.6302156%** result.

PR #208 separately tested the rejected counterfactual of applying SEC-mode issuer treatment before SEC evidence exists. That strict-precoverage sensitivity changed the warm-up/book and produced:

- authoritative/current control: **22.63021562% CAGR**
- strict-precoverage: **21.34915344% CAGR**
- delta: **-1.28106218 pp/year**

This proves that upstream PIT reconstruction can materially move CAGR even when the intended production PIT correction itself is zero-delta. It is a confirmed mechanism capable of contaminating a later sector experiment.

The retained #241 generator source needed to prove whether its exact base used this same strict-precoverage implementation was not committed, so this **-1.281 pp is a confirmed relevant sensitivity, not yet a complete attribution of the #241 baseline gap**.

## Other retained evidence

- Category removal changed witness values but produced **no economic path change** in the retained 40pp true-PIT experiment.
- The missing SEC 2011Q2 SIC quarter was later supplied; it changed two held-name labels on 16 sessions but caused **0 fast-trigger, 0 native-allocation, 0 LD-RC and 0 NAV changes**.
- On the inherited #241 base, changing the fast damaged-breadth acceleration threshold from 40pp to the authoritative 30pp changes current-sector 20Y CAGR from **19.97939044% to 18.43172395%**. This is a **-1.54766649 pp/year nonlinear controller interaction on the altered base**, not a sector effect.

## Reproducibility defect found

The branch manifest retained hashes for several load-bearing local files but not their bytes or generator source, including:

- `pit_latestissuer_dummy_complete.py`
- `pit_latestissuer_dummy_complete_d30.py`
- `pit_exp_currentcat_ff12_out/sentinel_1p1_daily.csv`
- `true_pit_ldrc_daily.csv`
- `pit_sector_diag_full_out/sector_diag.csv`
- `held_close_history.pkl`
- `recovered_spy_bil_partial.csv`

The first-pass sector scripts therefore cannot be fully regenerated from the branch alone. This is why exact decomposition of the remaining upstream `22.63 -> 18.43` gap is not currently provable from retained #241 artifacts.

This audit, the numerical decomposition, and an executable calibration guard are now retained on the branch so this ambiguity cannot recur silently.

## Correct next experiment

A production-relevant PIT-sector experiment must satisfy this sequence:

1. Reproduce the authoritative current Simplified LD-RC 20Y control: **22.6302156206% CAGR / 1.213813871 Sharpe / -21.69582151% MDD**.
2. Apply the already-proven SEC issuer PIT boundary with the unsupported pre-2006 warm-up held identical; verify zero economic delta.
3. Keep current category semantics unless/until a separately validated category A/B is introduced.
4. With all other daily shadow/witness/controller inputs unchanged, replace **only** current Sharadar sector breadth grouping with causal SEC SIC→FF12.
5. Report that direct A/B as the actual sector effect.

Until that calibrated A/B exists, **18.48% is not a valid estimate of the current system's CAGR after only making sector PIT**.
