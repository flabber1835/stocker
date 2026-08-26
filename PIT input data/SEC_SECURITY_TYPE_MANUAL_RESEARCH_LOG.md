# Orion SEC security-type manual research log

This log records manual SEC EDGAR work performed because GitHub-hosted runners received HTTP 403 responses from SEC.gov. The acceptance rule is unchanged: evidence must be public strictly before the Orion decision/buy date; current mappings may be used only as retrieval hints; unresolved cases remain unknown/ineligible.

## 2026-08-25 continuation

### Newly resolved

- `POT` buy `2006-12-08` — verified common from pre-buy 10-K evidence.
- `SQM` buy `2005-06-03` — verified common-equity ADR from pre-buy SEC 6-K plus SEC continuity evidence.
- `BBRC1` buy `2000-05-19` — verified common from Burr-Brown 1999 10-K.
- `BGO` buy `2003-12-03` — verified common from Bema Gold 2002 40-F.
- Batch 08: `ADVP`, `AEH1`, `CGP`, `DELL1`, `CSE1`, `LU1`, `VRTS1`, `WLA` — all verified common from SEC registration evidence filed before their Orion buys.
- Batch 09: `BGEN`, `KMG1`, `MEDX1`, `SNDK1`, `SII1`, both `THOR1` buys, and `TOY` — all verified common from SEC registration evidence filed strictly before the relevant buy.
- Batch 10: both `BUD1` buys, `CELL1`, `CPNLQ`, `GNET1`, both `MFNXQ` buys, `MOVIQ`, and `NEWP1` — all verified common from SEC registration evidence filed strictly before the relevant buy.
- Batch 11: `SCIO1`, `SSTI1`, `TCF1`, `TFSIQ`, `UCBHQ`, and `VOLT2` — all verified common from SEC registration evidence filed strictly before the relevant buy.
- Batch 12: `AZA.A`, both `DTGF` buys, `EV1`, and `EYE1` — verified common from SEC evidence filed before the relevant Orion buy. `AGN1` has a same-day `1998-09-29` S-8 identifying Common Stock, but because the filing date equals the Orion buy date it is **not counted as resolved** pending session-phase/publication-cutoff proof.
- Batch 13: `FALB`, `IGT1`, `KM`, `LIT1`, `VRTY1`, and `WCOEQ` — verified common from causal pre-buy SEC evidence. `FALB` uses a 2005 SEC-filed exhibit explicitly describing Falconbridge common shares; the others use SEC registration evidence. Full provenance is in `SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE_BATCH_2026-08-25_13.csv`.
- Batch 14: `DSGX` — verified common from Descartes Systems Group S-8 filed `1999-08-03` for `FOREIGN COMMON STOCK`, before the 2000 buy.
- Batch 15: `ELN` — verified common-equity ADR from Elan F-6 filed `1993-07-12` for depositary receipts for common stock; `MGA` — verified common from Magna International F-3 filed `1994-02-28` for foreign common stock; `GPRO1` — verified common from Gen-Probe Schedule 13G dated `2011-02-11` explicitly identifying common stock, before the `2011-06-03` Orion buy.
- Batch 16: `GELX` — verified common from GelTex S-4 filed `1999-10-05` for common stock, before the 2000 buy.

### Investigated but not yet admitted

- `NOK` buy `1998-07-07` — pre-buy SEC ownership filing exists and later 20-Fs establish the NOK ADS history, but the exact pre-buy security-title evidence still needs direct extraction.
- `SAP` buy `1998-07-07` — later SEC filings say SAP ADSs began NYSE trading on `1998-08-03`, after the Orion buy; remains a listing/identity anomaly.
- `ARMH1` buy `1999-04-23` — later 20-F says 1998 IPO/ADS history, but contemporaneous registration evidence is still being sought.
- `AV1` buy `2003-09-29` — post-buy 2003 10-K is explicit; earlier evidence still required.
- `AGN1` buy `1998-09-29` — same-day common-stock registration evidence exists, but the strict `< decision_session` rule means it remains unresolved until an earlier filing is found or exact filing/publication time proves it was available before Orion's decision phase.
- `AWE` buy `2004-05-14` — later 2004 filings explicitly identify AT&T Wireless common stock, but pre-buy evidence is still required.
- `CLTZF` buy `1998-07-07` — a Colt Telecom F-3 filed `1998-07-13` identifies foreign common stock, but it is six days after the Orion buy and is therefore not causal for that decision.
- `FRFHF` buy `2008-02-21` — explicit Fairfax filings located so far are after the buy; earlier evidence is still required.
- `LMLP1` buy `2000-03-29` — explicit LML common-stock registration found `2000-11-06`, after the buy; not admissible.

### Count checkpoint

The prior authoritative checkpoint was **69 unresolved executed-buy rows**. Batch 13 safely resolved 6, batch 14 resolved 1, batch 15 resolved 3, and batch 16 resolved 1. Authoritative remaining count: **58 unresolved executed-buy rows**.

## Governance

All positive, negative, ambiguous, and unresolved findings are to be committed to this Orion branch as they are established. Successful executed-buy coverage is only the first economic gate; full candidate/session coverage and a provenance-retaining fail-closed `SEC_SECURITY_TYPE_PIT_ONLY` tape are still required before certification.
