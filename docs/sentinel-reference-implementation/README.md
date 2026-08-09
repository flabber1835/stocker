# Sentinel 1.1 Python-only raw-Sharadar reference — corrected

This package is the corrected standalone Sentinel 1.1-RC (`zero recovery gate`) historical implementation.

## What was fixed

1. **Slow-stress session age / 2022 off-by-one**
   - The ordinary-stress sensor now counts the first active session as session 1 without an extra increment.
   - On the reference history, **2022-05-17 is stress duration 30**.
   - The slow-severe decision is therefore made after the 2022-05-17 close and **0% Core becomes effective at the 2022-05-18 open**, matching the frozen allocation oracle.

2. **Measurement-window initialization**
   - The 2006-07-31 measurement start is explicitly normalized to NAV 1.0.
   - Warm-up history remains available to the strategy, but the prior warm-up interval is not accidentally compounded into the reported 20-year NAV.

## Fresh full-corpus validation

A new run was executed from the standalone source using the raw Sharadar corpus only.

- Period: 2006-07-31 through 2026-07-31
- Sessions: 5,032
- Candidate allocation parity vs frozen Sentinel 1.1: **5,032 / 5,032**
- Parent effective allocation parity: **5,032 / 5,032**
- Damaged breadth mismatches: **0**
- Green breadth mismatches: **0**
- Wealth Core shadow normalized max relative error: **4.44e-16**

Raw-Sharadar restatement:

- CAGR: **22.2593842783%**
- Maximum drawdown: **-21.9490456703%**
- Ending multiple: **55.6775262012x**

Frozen Sentinel 1.1 reference:

- CAGR: **22.2517484667%**
- Maximum drawdown: **-21.9490456703%**
- Ending multiple: **55.6080182991x**

Difference after the strategy fixes:

- CAGR: **+0.7636 basis points**
- Maximum drawdown: effectively **0.0000 percentage points**
- Ending wealth: **+0.1250%**

## Why the last NAV difference is intentionally not “patched away”

The remaining difference is not a Sentinel decision difference. It starts on **2007-07-30**, the first parent Sentinel transition, while allocation, breadth and the immutable Wealth Core shadow remain exact.

The retained frozen Sentinel 1.1 replay is a lineage-compatible historical reconstruction. On intervals where Sentinel 1.1 is identical to Sentinel 1.0x, it preserves the frozen parent scalar NAV factor. The later 1.1 recovery-ramp work independently reconstructed the additional 55% / 65% transition-open behavior. In other words, the frozen 1.1 NAV preserves an older parent open-accounting lineage rather than recomputing every historical transition using one uniform raw-Sharadar open reconstruction.

This corrected standalone deliberately uses one uniform rule for all dates:

- prior allocation owns close -> next open;
- new allocation owns next open -> close;
- Wealth Core open equity is rebuilt from the actual certified position state and Sharadar raw/as-traded opens;
- BIL uses its Sharadar adjusted open and total-return close;
- cost is 10 bp on changed allocation notional.

Making the raw-only standalone match the frozen NAV bit-for-bit would therefore require importing or embedding historical parent accounting outputs. That would violate the purpose of this file: **strategy and accounting recomputed from raw Sharadar, with no frozen path/oracle as a runtime input**.

Thus the certification conclusion is:

> **Sentinel 1.1 strategy semantics are now exact. The remaining 0.125% terminal NAV difference is a known historical accounting-lineage difference, not a strategy divergence.**

See `PARITY_REPORT.json` and `transition_accounting_delta.csv` for machine-readable evidence.

## Run

```bash
python sentinel_1p1_standalone.py \
  --sharadar /path/to/sharadar \
  --start 2006-07-31 \
  --end 2026-07-31 \
  --out ./sentinel_1p1_output
```

Expected raw files in the Sharadar directory are the annual `SHARADAR_SEP_YYYY.csv.gz` files plus `SHARADAR_TICKERS.zip`, `SHARADAR_ACTIONS.zip`, and `SHARADAR_SFP.zip`.
