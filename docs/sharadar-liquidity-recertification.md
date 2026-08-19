# Sharadar liquidity-domain correction — recertification evidence

Issue #185 corrects one economic-domain error at the Sharadar → Wealth Core
boundary:

```text
OLD / INVALID
    closeunadj * Sharadar reported volume

CORRECT
    closeunadj * (reported volume * close / closeunadj)
    == close * reported volume
```

Sharadar `close` and `volume` share the split-adjusted basis; `closeunadj` is the
as-traded/raw price. The old expression mixed those bases. The corrected adapter
normalizes volume before `VendorBar` reaches Wealth Core, so raw-price liquidity
is split-invariant.

This document separates **input-domain impact** from **strategy-output impact**.
The first is measured directly from retained Sharadar SEP files below. The
second must come from authoritative Wealth Core rehearsals and must not be
inferred from row counts.

## Retained-source input audit

Source: retained per-year Sharadar SEP files for 1997–2026 used during the #185
review. When duplicate filenames existed, one complete retained copy of that
year was selected; rows were not de-duplicated across different years.

Audit population:

```text
SEP rows scanned                                      46,254,680
rows with positive finite close/closeunadj/volume    43,611,244
rows with material closeunadj/close split basis       9,754,992
```

### Signal-session $5M dollar-volume predicate

For every valid row the audit compared:

```text
old    = closeunadj * volume
correct = close * volume
```

against the canonical `$5,000,000` threshold.

```text
old PASS, corrected FAIL      465,370
old FAIL, corrected PASS      670,874
-------------------------------------
total predicate flips       1,136,244
```

The defect is therefore **bidirectional**. Forward-split histories can make old
liquidity look too large; reverse-split histories can make it look too small.

Representative retained-year counts:

```text
year    old PASS/new FAIL    old FAIL/new PASS
2020                 2,922               30,622
2021                 2,541               57,629
2024                   416                8,669
2026                    46                1,770
```

### Actual 20-session $20M ADV predicate

This audit reproduces Wealth Core's `adv20_dollars` window convention: arithmetic
mean of the 20 observations ending at the signal session, with unusable
price/volume observations making the rolling value unavailable. The old and
corrected dollar-volume series are compared at the canonical `$20,000,000`
threshold.

Across the retained 1997–2026 history:

```text
old ADV PASS, corrected FAIL      522,343
old ADV FAIL, corrected PASS      336,997
-----------------------------------------
total ADV predicate flips         859,340
```

Representative retained-year counts:

```text
year    old PASS/new FAIL    old FAIL/new PASS
2020                 4,602               14,331
2021                 4,044               30,152
2022                 3,241               12,821
2024                 2,128                5,626
2026                   146                1,009
```

These counts prove that the prior input domain can materially change the
liquidity gates. They are **not** the final eligible-universe delta: Wealth Core
also requires point-in-time listing/issuer/category/exchange evidence, minimum
price, continuous 126-session history, valid volatility, leadership ranking and
admission constraints. A predicate flip can therefore be masked by another
independent refusal. Likewise, a changed eligible population does not imply a
trade changed.

## Authoritative strategy-output comparison

Do not repin expected hashes merely because the corrected implementation is
intentional. Run the same canonical full-retention chain rehearsal on the
pre-correction and corrected runtimes/corpora, export both authoritative rows,
and compare them with:

```bash
python scripts/sentinel_rehearsal.py export \
  --run-id <BEFORE_RUN_ID> --out before-rehearsal.json

python scripts/sentinel_rehearsal.py export \
  --run-id <AFTER_RUN_ID> --out after-rehearsal.json

python tools/wealth_core_liquidity_recertification.py \
  --before before-rehearsal.json \
  --after after-rehearsal.json \
  --out liquidity-recertification.json
```

Both rehearsals must use `retention_mode=full`, the same date window, starting
cash, `WealthCoreConfig`, and `EligibilityConfig`. The comparator refuses unlike
economic specs.

The retained report provides:

- changed parity-hash layers;
- exact added/removed session trade intents;
- final-book identity/hash difference;
- before/after/delta for ending equity, total return, CAGR, maximum drawdown,
  trade count and turnover;
- benchmark/excess CAGR changes; and
- a report-only Sharpe ratio derived from the retained resolved-equity series
  using the explicit convention `rf=0`, simple session returns, sample standard
  deviation and `sqrt(252)` annualization.

Sharpe is refused if any session lacks a resolved equity. Missing valuations are
not interpolated or carried forward.

## Definition of acceptable completion

The liquidity correction is not economically recertified until the authoritative
before/after rehearsal report exists and is reviewed. In particular, issue #185
must not be closed merely because:

- live and backtester adapters agree with each other;
- unit tests prove the algebraic invariant; or
- new expected hashes were generated.

The final review must state the actual trade differences, CAGR, maximum drawdown,
Sharpe and whether the previously selected Wealth Core strategy remains the
selected/champion strategy after corrected inputs. If champion selection was
originally established by a multi-variant experiment/sweep, that same selection
process must be rerun on corrected inputs rather than inferred from the baseline
rehearsal alone.
