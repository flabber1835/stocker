# Provenance — terminal + issuer corrected lineage

`README.md` and `ISSUER_CORRECTION_REPORT.md` are the **upstream** documents,
verbatim, covered by `SHA256SUMS.txt` (18/18 verify clean). This file is the
repository's own record.

Source archive: `docs/Sentinel_1_1_Terminal_and_Issuer_Corrected.zip`
(sha256 `670d043a8a6469f600cc14dd29b7ebccd41cbd52fe28b60dc3a704ca840ad529`,
received 2026-08-09).

**This is the only Sentinel reference lineage to use.** It supersedes and
DELETES `Sentinel_1_1_Terminal_Order_Corrected.zip`, which itself superseded
`Sentinel_1_1_Python_Only_Corrected.zip`. It carries BOTH corrections: the atomic
terminal-action reconciliation and the issuer-identity parse.

## THE DIRECTION OF THIS FIX IS THE OPPOSITE OF THE LAST ONE

The terminal-order correction found a defect in the reference and raised a
question against our engine. **This one found a defect in the reference that our
engine does not have.** The standalone split Sharadar's `relatedtickers` on
commas and semicolons only; Sharadar serves that field primarily
**whitespace-separated**, so a two-ticker string was treated as one opaque token
and the issuer-conflict check silently stopped matching.

The fix adopts the construction already certified in this repository, and the
claim was verified here rather than taken on trust:

```text
services/bt-data/app/main.py:307        " ".join(rt)   stores it space-joined
services/backtester/.../wealth_core_replay.py:817
                                        (r["related_tickers"] or "").split()
                                        whitespace tokenization — CORRECT
shared/.../wealth_core/eligibility.py:215  build_issuer_group_key, sorted+unique
```

So Stocker's Wealth Core reads this field correctly and always has. That is worth
recording precisely because the previous correction ran the other way: the
production engine is not uniformly behind the reference, and neither artifact
should be treated as automatically authoritative over the other.

## What the defect actually did: Alphabet

```text
before   GOOG and GOOGL held SIMULTANEOUSLY. Their relatedtickers strings are
         whitespace-delimited, so the old parser produced DIFFERENT keys for what
         is one economic issuer
after    identical keys; GOOGL is blocked while GOOG is held
         2025-12-23  removed buy GOOGL  2,258 sh @ 309.625  ($699,133)
         2025-12-23  replacement ROIV  30,899 sh @  22.635  ($699,399)
```

`issuer_key_parser_changes.csv` shows the parse itself, and the pattern is
broader than Alphabet — units, warrants and share classes all carry
space-separated related tickers:

```text
AIMBU   raw "AIMAU AIMAW"   old "AIMAU AIMAW|AIMBU"   new "AIMAU|AIMAW|AIMBU"
```

A hard invariant now runs after every open fill and ABORTS if two held securities
share an issuer key. Full-history validation: 7,188 Wealth Core sessions, **0**
duplicate-issuer violations after the correction.

## Performance impact: almost none, which is the point

```text
20-year Sentinel CAGR         22.09461850%
20-year max drawdown         -21.96309788%
20-year ending multiple       54.195852100x   (+0.00136% vs terminal-only)
Wealth Core from 1998         173.768095127x
Sentinel allocation path      UNCHANGED, and so is the parent path
first path difference         2025-12-23
```

A concentration defect that barely moves the return is still a defect: holding
GOOG and GOOGL is one bet wearing two tickers, and the book's real diversification
was lower than its position count claimed for as long as it lasted. **The number
to judge this by is the 0 duplicate-issuer violations, not the +0.00136%.**

## Verified in this repository, 2026-08-09

```text
sha256sum -c SHA256SUMS.txt            18/18 OK
the four controller unit tests         PASS against the corrected source
                                       (import retargeted — the only edit to any
                                       shipped file)
our own relatedtickers tokenization    CONFIRMED whitespace-split, as credited
```

Not verified: that running `sentinel_1p1_standalone.py` against raw Sharadar
reproduces `sentinel_1p1_daily.csv`. That needs the corpus. The tape is stored;
the producer is unverified.

## CONSEQUENCE FOR `sentinel/feed/`

Sentinel's own universe ingestion is **not yet written**, and when it is it must
tokenize `relatedtickers` on WHITESPACE (and commas), not commas alone. Getting
this wrong reproduces the Alphabet defect in production, where it presents as a
book that looks diversified and is not.

`sentinel/feed/domains.py` currently accepts `resolve_identity` as an injected
callable with nothing behind it, so bars key on TICKER. That is a placeholder,
not a design: it re-introduces the ticker-reuse splice the module explicitly
refuses elsewhere, and it must be replaced by a point-in-time resolver built from
`SHARADAR/TICKERS` before the corpus is trustworthy for Wealth Core.
