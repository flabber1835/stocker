# Sentinel 1.1 — Issuer Identity Correction Report

## What was fixed

The standalone/reference implementation incorrectly parsed Sharadar `relatedtickers` by splitting only on commas/semicolons. Sharadar SEP serves this field primarily as a whitespace-separated string. The corrected implementation now uses the certified construction already present in Stocker's Wealth Core code:

1. parse `relatedtickers` as space- or comma-separated tokens;
2. normalize, sort, and de-duplicate `{ticker} ∪ relatedtickers`;
3. use the joined set as `issuer_group_key`;
4. if there are no related tickers, fall back to `P:<permaticker>`.

A hard invariant now runs after every open fill and aborts if two held securities ever share an issuer key.

## Full-history validation

- Replay corpus: raw Sharadar SEP/ACTIONS/TICKERS/SFP only
- Wealth Core replay checks: **7,188** sessions
- Duplicate economic issuer violations after correction: **0**
- Sentinel window: 2006-07-31 through 2026-07-31, **5,032** sessions
- Ending holdings: **20**
- Ending cash weight: **37.140389%**

## Alphabet defect

Before this correction, the terminal-order-corrected lineage held both GOOG and GOOGL. The old parser treated their whitespace-delimited `relatedtickers` strings as single opaque tokens, so the issuer conflict check did not match.

The corrected keys for GOOG and GOOGL are identical. The full replay therefore blocks GOOGL while GOOG is already held. On 2025-12-23 the replacement candidate becomes **ROIV** instead.

- Removed old buy: **GOOGL**, 2025-12-23
- Correct replacement: **ROIV**, 2025-12-23
- Ending GOOG positions: **1**
- Ending GOOGL positions: **0**

The first numerical path difference versus the terminal-only-corrected lineage is 2025-12-23. Sentinel's allocation path and parent allocation path remain exactly identical; only the underlying Wealth Core book/NAV changes slightly.

## Corrected performance

- 20-year Sentinel CAGR: **22.09461850%**
- 20-year max drawdown: **-21.96309788%**
- 20-year ending multiple: **54.195852100x**
- Wealth Core full-history multiple from 1998: **173.768095127x**

Compared with the prior terminal-only-corrected lineage, the 20-year ending multiple changes by only about +0.00136%; max drawdown and Sentinel allocation decisions are unchanged.

## Certification conclusion

**PASS.** The standalone now uses the same certified `relatedtickers` tokenization semantics as the production Wealth Core issuer-identity implementation, and the full historical replay proves zero simultaneously held duplicate issuer keys.
