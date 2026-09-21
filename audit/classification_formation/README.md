# First causal divergence: classification, not initial strategy behavior

Four independent fresh books processed 128 sessions, January 3 through July 6,
2006, in 946.55 seconds total. Starting cash was USD 100,000. The unchanged
production source was 624395dd04c48af7de3a8930cfd586ca2cc81245. The original
replay checkout, inputs, supplements, checkpoints and reference were not edited.

| Scenario | July 6 NAV | Exact reference positions and quantities |
| --- | ---: | ---: |
| Original inputs, control | $99,368.92559160099 | 13 / 20 |
| Correct parsed dates only | $98,890.42987245199 | 12 / 20 |
| Seven historical classification links only | $99,382.53663482302 | 20 / 20 |
| Parsed dates plus seven links | $99,399.52961482300 | 19 / 20 |
| Retained research reference | $99,382.53663482303 | 20 / 20 |

The control matches retained daily NAV, Core NAV, holding count and controller
decisions on all 128 dates. No book is injected: all scenarios first submit entry
orders July 5 and fill July 6. The seven-link scenario restores every reference
quantity without any strategy change. Its cash is $505.4166348230015 and its
first-fill fees total $99.3951881769999945. Its $13.61104322203 advantage over
the original control is only the first-day economic effect, not the later
return-gap attribution.

Cash reconstructed as $100,000 plus ledger cash movements, added to shares
times raw July 6 closes, independently reconciles Core NAV for all four paths
within $0.000001. See comparison.json, which also retains per-ticker quantities.
All scenarios remain fully exposed on July 6; Core and controlled NAV agree.
This isolates the formation result from controller allocation and later
missing-price/terminal accounting.

## The date fix exposes another alias, not a failed investment thesis

Combined corrections replace BFH (83 shares) with JLL (57 shares). BFH is
Bread Financial's modern ticker; its historical ticker was ADS. The retained
positive-evidence source already contains ADS common-stock evidence dated
February 1, 2006, CIK 1101215, accession 0001101215-06-000001.

The company's [2022 SEC announcement](https://www.sec.gov/Archives/edgar/data/1101215/000110121522000058/form_8-k.htm)
identifies ADS -> BFH as a common-stock ticker change with unchanged CUSIP.
Its [2022 annual report](https://www.sec.gov/Archives/edgar/data/1101215/000110121523000049/bfh-20221231.htm)
also confirms unchanged legal entity structure. Later identity documentation
can decode a vendor's renamed historical label without supplying future prices
or returns. BFH was not added to these completed, preserved scenarios.

Thus date parsing must be corrected, but a date-only repair with incomplete
identity links is not a fair economic universe. The seven-name result establishes
the cause of the first book mismatch; it does not prove the 56.27x return or
quantify the full subsequent performance effect. The selected seven names make
this a causal diagnostic, not an out-of-sample test.

## Next economic test

Use consistent reconstructed historical security types and interval-specific
aliases across both engines, keep strategy parameters frozen, and compare Core,
controller and SPY on matched dates. Treat material terminal economics separately.
Bound unresolved inputs economically or report the affected result as inconclusive;
do not label missing classification evidence as strategy failure, tune to the
reference return, or turn this into an exhaustive SEC archival exercise.

## Verification and reproduction

Base: 82f8d774448517b134deafe6d3bd989b2b9b8053. The external harness is PR #426;
the pinned production kernel is from PR #425. Later PR head updates are not
substituted for the production-source manifest verified by this experiment.

    python -B -m pytest -q -p no:cacheprovider research/classification_check/test_classifier.py

Result: 12 passed. Reintroducing ten-character date slicing in memory makes the
late-month, future-date and same-day calendar checks fail (3 independent
falsifiers). Pyflakes and syntax checks pass. No golden fixture was repinned.

The runner and compare commands are in research/classification_check. Full daily
diagnostics remain at C:/GitHub/stocker/.codex-tmp/classification-formation-20260921-04.
Compact results and first-trade records are retained here. The earlier local
startup attempts failed on missing/mismatched dependencies before any successful
session and are not economic evidence. This run records its matching numeric
and calendar package versions in identity.json.

The full final snapshots and first-trade records are gzip-compressed for a small
review diff. The source archive contains the exact executed Python bytes matching
identity.json; repository text uses LF line endings. Original local run outputs
remain byte-for-byte untouched.
