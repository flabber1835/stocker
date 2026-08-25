# Orion point-in-time issuer evidence

This directory is an **Orion research-only evidence archive**. It does not authorize or modify production strategy behavior and is not on `main`.

## Purpose

Retain the point-in-time issuer-identity evidence used to avoid projecting present-day Sharadar `relatedtickers` relationships backward through history.

The canonical source data are already committed on this branch under:

- `sec-filings/2006q1_form345.zip` through `sec-filings/2026q2_form345.zip`
- `tools/sec_pit_reconstruct.py`

The reconstruction rule is causal: a ticker/issuer-CIK observation is usable only from its SEC filing date onward. Current Sharadar `relatedtickers` is not an authority for historical issuer identity.

## Generated archive

`.github/workflows/orion-pit-evidence.yml` deterministically rebuilds and retains:

- `observations.csv.gz` — full normalized SEC Form 3/4/5 issuer observation tape with source provenance
- `symbol_cik_evidence.csv.gz` — compact ticker/CIK evidence spans
- `sec_cik_change_events.csv.gz` — canonical dated `(filing_date,ticker,issuer_cik)` evidence, deduplicated and sorted
- `coverage.json` — archive coverage, source hashes, date range and Alphabet control
- `SHA256SUMS.txt` — hashes of the retained generated artifacts

Generated CIKs are normalized 10-digit SEC CIK strings. This is preferred over the older convenience CSV representation that rendered CIKs as floating-point numbers.

## Alphabet validation

`sec_issuer_pilot_results.csv` retains the GOOG/GOOGL validation: both share classes resolve causally to Alphabet CIK `0001652044`, preventing a second same-issuer position when that information was already public.

## Reproducibility contract

The raw SEC ZIP corpus is the primary evidence. Derived files must be reproducible byte-for-byte from the branch-pinned reconstruction code and source ZIPs. If a generated artifact does not match its retained checksum, it is not Orion PIT evidence.
