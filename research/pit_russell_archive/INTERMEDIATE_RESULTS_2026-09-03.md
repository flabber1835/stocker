# PIT Russell archive reconstruction — intermediate results

Research only. This file records experiment state and evidence. It is not production or backtest certification authority.

## Isolation

All writes in this experiment are confined to `research/pit-russell-archive-reconstruction`.

Observed unchanged authority refs during this work:

- `main`: `8b42b1e109b2ff3cb6832f92757a45ced0df4c60`
- `research/backtester`: `e088bfd26c695309e259cfc44ab1e8982d6f858d`

The eventual Russell overlay can consume a read-only checkout of the backtester ref at runtime; no write or merge into `research/backtester` is required for the research experiment.

## Objective

Establish a defensible 20-year PIT backtest universe by using causally available Russell 3000 membership as the eligibility/share-class authority over Sharadar market data, then certify universe, identity, market-data causality, execution, terminal handling, and forward-leakage properties.

## Archive runner evidence

GitHub-hosted runners can query Internet Archive/Wayback and fetch archived Russell PDFs. Raw copyrighted membership PDFs are not committed. Derived factual membership rows, provenance, hashes, diagnostics, and reports may be retained.

## Annual official-source discovery

Source-discovery workflow run: `33781142327`, head `90868c293a8213de5c8a8b598a63d0c4ce433c4f`.

Three independent era jobs completed successfully: 2005–2013, 2014–2019, and 2020–2026.

Important interpretation rule: `NO_OFFICIAL_CAPTURE_FOUND` means no capture was returned by the tested URL families. It is not proof that no official artifact exists. Multiple Wayback wildcard/source queries timed out, especially for later FTSE Russell URL families.

| Year | Current official-source status | Notes |
|---:|---|---|
| 2005 | DIRECT PDF KNOWN; coverage fetch timed out | Exact archived PDF already fetched in parser runs |
| 2006 | RECOVERABLE OFFICIAL PDF | Exact archived PDF fetched |
| 2007 | UNRESOLVED | No capture returned from tested official URL families |
| 2008 | UNRESOLVED | No capture returned from tested official URL families |
| 2009 | RECOVERABLE OFFICIAL PDF | Parsed successfully |
| 2010 | RECOVERABLE OFFICIAL PDF | Parsed successfully |
| 2011 | RECOVERABLE OFFICIAL PDF | Parsed successfully |
| 2012 | RECOVERABLE OFFICIAL PDF | Parsed successfully |
| 2013 | RECOVERABLE OFFICIAL PDF | Parsed successfully |
| 2014–2019 | UNRESOLVED SOURCE PATH | Tested old/stable and FTSE wildcard families returned no captures; several queries timed out |
| 2020–2026 | UNRESOLVED SOURCE PATH | Tested old/stable and FTSE wildcard families returned no captures; several queries timed out |

The later-year result is a source-path discovery gap, not a membership-data impossibility result. Independent preserved annual constituent collections are already known for much of 2014–2023 and will be used as discovery/corroboration leads, with official provenance preferred for certification.

## Successfully parsed membership PDFs

The coordinate-aware parser passes on the known stable-format Russell PDFs for 2009–2013.

2009 validation example:

- capture: `20091014135725`
- PDF SHA-256: `d9042d3866cd4a71e7c3ebb6fc4904163987b8aaf105c18351943775bf45d6cd`
- parsed rows: 2,978
- unique tickers: 2,978
- ambiguous tickers: 0
- count gate: PASS

All 2009–2013 matrix jobs passed the extraction gate in run `33781142327`.

## 2005/2006 direct PDF evidence

### 2005

- Wayback capture: `20051030075845`
- original URL: `http://www.russell.com/us/indexes/us/reconstitution/R3000.pdf`
- PDF SHA-256: `d849ad9c3c6f08aaa4f8acc3351b046211ed27f54bb1599b3d3ca01ca99d595b`
- PDF bytes: 181,326

### 2006

- Wayback capture: `20060710045437`
- original URL: `http://www.russell.com/us/indexes/us/reconstitution/R3000.pdf`
- PDF SHA-256: `18080cd078342b05dba51f2fe75b1d1c0dd85de1a8e715fc0ce18090a44d7024`
- PDF bytes: 714,058

## 2005/2006 parser investigation

Dedicated diagnostic workflow run: `33782396784`, head `e1895d214496e17b01d50e327810d2ed4142c11c`.

Both diagnostic jobs completed successfully. `accepted_as_corpus` was explicitly false.

### Structural result

The early PDFs use a different page layout from the 2009–2013 documents. The useful `pdftotext -layout` representation contains approximately 1,500 visual rows. Each visual row can contain two independent company/ticker records. A naive sequential or terminal-token parser therefore crosses the two visual columns and creates false ticker/company pairs.

2005 diagnostics:

- raw non-empty lines: 3,006
- layout non-empty lines: 1,519
- plain non-empty lines: 6,006
- layout split-whitespace candidate: 1,476 rows / 1,476 unique tickers / 0 ambiguity
- terminal-token hypothesis: rejected

2006 diagnostics:

- raw non-empty lines: 3,019
- layout non-empty lines: 1,532
- plain non-empty lines: 6,006
- layout split-whitespace candidate: 1,477 rows / 1,477 unique tickers / 0 ambiguity
- terminal-token hypothesis: rejected

The ~1,476/~1,477 count is strong evidence that the simple layout parser is extracting only one side of a two-column table. A correct parser should reconstruct both left and right records and land near the expected ~3,000-member universe.

### Rejected parser hypotheses

The following are permanently recorded as invalid and must not be reused without new evidence:

1. Treating the final token of every raw line as the ticker.
2. Treating sequential raw text lines as company/ticker pairs.
3. Applying the 2009+ coordinate-header parser unchanged to the 2005/2006 PDFs.
4. Accepting ~700-row or ~1,477-row outputs as a complete Russell 3000 universe.

Latest rejected legacy extraction results:

- 2005: 727 rows, 234 unique tickers, 61 ambiguous tickers — FAIL
- 2006: 739 rows, 232 unique tickers, 66 ambiguous tickers — FAIL

No rejected output is accepted into the corpus.

## Current next steps

1. Implement a strict early-format two-column parser that reconstructs both visual company/ticker pairs per row using coordinate/fixed-column geometry.
2. Require 2,500–3,500 rows, near-one-to-one ticker identity, zero unexplained conflicting mappings, and deterministic output before accepting 2005/2006.
3. Expand 2014–2026 source-path discovery using later FTSE Russell conventions and independently preserved lists as discovery/corroboration leads.
4. Recover 2007/2008 directly if possible; otherwise validate a deterministic additions/deletions reconstruction method against a known holdout year before using it.
5. Persist every accepted annual universe with source, publication/effective dates, archive timestamp where applicable, content hash, constituent count, parser contract, and evidence grade.
6. Only after annual universe coverage is complete, implement Russell→Sharadar PIT identity joining and the isolated certification harness.
