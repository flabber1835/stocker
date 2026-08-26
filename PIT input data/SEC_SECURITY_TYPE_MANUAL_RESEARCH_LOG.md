# Orion SEC security-type manual research log

This log records manual SEC EDGAR work performed because GitHub-hosted runners received HTTP 403 responses from SEC.gov. The acceptance rule is unchanged: evidence must be public strictly before the Orion decision/buy date; current mappings may be used only as retrieval hints; unresolved cases remain unknown/ineligible.

## 2026-08-25 continuation

### Newly resolved

- `POT` buy `2006-12-08` — verified common from pre-buy 10-K evidence.
- `SQM` buy `2005-06-03` — verified common-equity ADR from pre-buy SEC 6-K plus SEC continuity evidence.
- `BBRC1` buy `2000-05-19` — verified common from Burr-Brown 1999 10-K.
- `BGO` buy `2003-12-03` — verified common from Bema Gold 2002 40-F.
- Batch 08: `ADVP`, `AEH1`, `CGP`, `DELL1`, `CSE1`, `LU1`, `VRTS1`, `WLA` — all verified common from SEC registration evidence filed before their Orion buys. Full per-row provenance is in `SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE_BATCH_2026-08-25_08.csv`.
- Batch 09: `BGEN` (1998-10-13), `KMG1` (1999-09-03), `MEDX1` (2000-02-14), `SNDK1` (2003-11-13), `SII1` (2000-05-05), `THOR1` (2008-09-05 and 2008-12-02), and `TOY` (2005-05-25) — all verified common from SEC registration evidence filed strictly before the relevant buy. Full source dates, filing numbers, CIKs, and URLs are preserved in `SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE_BATCH_2026-08-25_09.csv`.

### Investigated but not yet admitted

- `NOK` buy `1998-07-07` — pre-buy SEC ownership filing exists and later 20-Fs establish the NOK ADS history, but the exact pre-buy security-title evidence still needs direct extraction.
- `SAP` buy `1998-07-07` — later SEC filings say SAP ADSs began NYSE trading on `1998-08-03`, after the Orion buy; remains a listing/identity anomaly.
- `ARMH1` buy `1999-04-23` — later 20-F says 1998 IPO/ADS history, but contemporaneous registration evidence is still being sought.
- `AV1` buy `2003-09-29` — post-buy 2003 10-K is explicit; earlier evidence still required.

### Count checkpoint

The prior authoritative checkpoint was **97 unresolved executed-buy rows**. Batch 09 resolves eight more buy rows (including two `THOR1` buys), leaving **89 unresolved executed-buy rows**.

## Governance

All positive, negative, ambiguous, and unresolved findings are to be committed to this Orion branch as they are established. Successful executed-buy coverage is only the first economic gate; full candidate/session coverage and a provenance-retaining fail-closed `SEC_SECURITY_TYPE_PIT_ONLY` tape are still required before certification.
