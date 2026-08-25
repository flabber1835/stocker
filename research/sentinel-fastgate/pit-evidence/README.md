# Orion point-in-time evidence archive

This directory is an **Orion research-only evidence archive**. It does not authorize or modify production strategy behavior and is not on `main`.

## Purpose

Retain the point-in-time evidence needed to avoid projecting present-day Sharadar metadata backward through history.

The archive has two independent causal metadata lineages:

1. **Issuer identity / CIK** — replaces present-day Sharadar `relatedtickers` as historical issuer authority.
2. **Industry peer taxonomy / SIC -> FF12** — replaces present-day Sharadar `sector` as historical slow/native breadth peer authority.

## Issuer / CIK evidence

The canonical source data are committed on this branch under:

- `sec-filings/2006q1_form345.zip` through `sec-filings/2026q2_form345.zip`
- `tools/sec_pit_reconstruct.py`

The reconstruction rule is causal: a ticker/issuer-CIK observation is usable only after it was public. Current Sharadar `relatedtickers` is not an authority for historical issuer identity.

`.github/workflows/orion-pit-evidence.yml` deterministically rebuilds and retains under `generated/`:

- `observations.csv.gz` — full normalized SEC Form 3/4/5 issuer observation tape with source provenance
- `symbol_cik_evidence.csv.gz` — compact ticker/CIK evidence spans
- `sec_cik_change_events.csv.gz` — canonical dated `(filing_date,ticker,issuer_cik)` evidence, deduplicated and sorted
- `coverage.json` — archive coverage, source hashes, date range and Alphabet control
- `SHA256SUMS.txt` — hashes of the retained generated issuer artifacts

Generated CIKs are normalized 10-digit SEC CIK strings.

`sec_issuer_pilot_results.csv` retains the GOOG/GOOGL validation: both share classes resolve causally to Alphabet CIK `0001652044`, preventing a second same-issuer position when that information was already public.

## SEC SIC -> FF12 evidence

See `SEC_SIC_PROVENANCE.md` for the full source and transport record.

The corrected PIT experiment produced an as-filed SEC SIC tape for 2009Q2 through 2026Q1 with these immutable acceptance fingerprints:

- rows: **423,766**
- uncompressed CSV SHA-256: `cee14e068e0793bcaaf668ffe3bbbd09c5d2107699ecd08b71371641a3efd8b7`
- 2011Q2 cross-check: **1,695** unique `(filed, CIK, SIC)` observations

`.github/workflows/orion-pit-sic-evidence.yml` recovers the exact corrected-research artifact and refuses to retain it unless those fingerprints match. It stores a deterministic gzip copy and machine-readable provenance under `generated/`.

`ff12_sic_definition.txt` freezes the Fama-French 12-industry SIC ranges used for causal peer grouping.

The decision-time rule is strict: use the latest SIC evidence with `filed < decision_session`. Missing causal SIC becomes a singleton unknown peer. **There is never a fallback to current Sharadar sector.**

## Reproducibility contract

Raw SEC evidence and immutable fingerprints are the trust root. Derived files must reproduce their retained checksums and causal rules. If an artifact fails a retained checksum, coverage gate, or publication-time rule, it is not Orion PIT evidence.
