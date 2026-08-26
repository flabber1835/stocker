# Orion SEC security-type manual research log

This log records manual SEC EDGAR work performed because GitHub-hosted runners received HTTP 403 responses from SEC.gov. The acceptance rule is unchanged: evidence must be public strictly before the Orion decision/buy date; current mappings may be used only as retrieval hints; unresolved cases remain unknown/ineligible.

## 2026-08-25 continuation

### Newly resolved

- `POT` buy `2006-12-08` — verified common from pre-buy 10-K evidence.
- `SQM` buy `2005-06-03` — verified common-equity ADR from pre-buy SEC 6-K plus SEC continuity evidence.
- `BBRC1` buy `2000-05-19` — verified common from Burr-Brown 1999 10-K.
- `BGO` buy `2003-12-03` — verified common from Bema Gold 2002 40-F.
- Batch 08: `ADVP`, `AEH1`, `CGP`, `DELL1`, `CSE1`, `LU1`, `VRTS1`, `WLA` — verified common from pre-buy SEC registration evidence.
- Batch 09: `BGEN`, `KMG1`, `MEDX1`, `SNDK1`, `SII1`, both `THOR1` buys, and `TOY` — verified common from pre-buy SEC registration evidence.
- Batch 10: both `BUD1` buys, `CELL1`, `CPNLQ`, `GNET1`, both `MFNXQ` buys, `MOVIQ`, and `NEWP1` — verified common from pre-buy SEC registration evidence.
- Batch 11: `SCIO1`, `SSTI1`, `TCF1`, `TFSIQ`, `UCBHQ`, and `VOLT2` — verified common from pre-buy SEC registration evidence.
- Batch 12: `AZA.A`, both `DTGF` buys, `EV1`, and `EYE1` — verified common. `AGN1` has same-day common-stock evidence and remains unresolved pending session-phase proof.
- Batch 13: `FALB`, `IGT1`, `KM`, `LIT1`, `VRTY1`, and `WCOEQ` — verified common from causal pre-buy SEC evidence.
- Batch 14: `DSGX` — verified foreign common stock.
- Batch 15: `ELN` — verified common-equity ADR; `MGA` — verified foreign common stock; `GPRO1` — verified common.
- Batch 16: `GELX` — verified common.
- Batch 17: `HSAC1`, `IBLTZ`, `IBP1`, and `HLTH1` — verified common.
- Batch 18: `ILUM` and `JAVA1` — verified common.
- Batch 19: `LVCI`, `MGIC`, `MNMD1`, `NEU1`, `LHSP`, and `INVN1` — verified common.
- Batch 20: `NXTL`, `ORTL`, and `SDLI` — verified common.
- Batch 21: `PWER1` and `RNB` — verified common.
- Batch 22: `LPHIQ`, `VRUS1`, and `WGHTQ` — verified common from causal pre-buy SEC evidence. Full provenance is in `SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE_BATCH_2026-08-25_22.csv`.
- Batch 23: `KBL`, both earlier `COCOQ` buys, and `NGH` — resolved from causal pre-buy SEC evidence. Full provenance is in `SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE_BATCH_2026-08-25_23.csv`.

All resolved rows are preserved in numbered evidence CSV batches with CIK, historical symbol, filing date/form/file number, SEC URL, join basis, classification, and notes.

### Investigated but not yet admitted

- `NOK` buy `1998-07-07` — pre-buy SEC ownership filing exists and later 20-Fs establish the NOK ADS history, but exact pre-buy security-title evidence still needs direct extraction.
- `SAP` buy `1998-07-07` — later SEC filings say SAP ADSs began NYSE trading on `1998-08-03`, after the Orion buy; remains a listing/identity anomaly.
- `ARMH1` buy `1999-04-23` — later 20-F says 1998 IPO/ADS history, but contemporaneous registration evidence is still being sought.
- `AV1` buy `2003-09-29` — post-buy 2003 10-K is explicit; earlier evidence still required.
- `AGN1` buy `1998-09-29` — same-day common-stock registration evidence exists, but strict `< decision_session` means unresolved unless earlier evidence or exact timing proves prior availability.
- `AWE` buy `2004-05-14` — later 2004 filings explicitly identify AT&T Wireless common stock, but pre-buy evidence is still required.
- `CLTZF` buy `1998-07-07` — Colt Telecom F-3 filed `1998-07-13` identifies foreign common stock, six days after buy; not causal.
- `FRFHF` buy `2008-02-21` — explicit Fairfax filings located so far are after the buy.
- `LMLP1` buy `2000-03-29` — explicit LML common-stock registration found `2000-11-06`, after buy.
- `VSTR1` buy `1999-11-23` — explicit VoiceStream common-stock registration located in 2000, after buy; earlier evidence required.
- `TSG1` buy `2007-02-27` — pre-buy Sabre Holdings SEC evidence establishes NYSE `TSG` common stock, but the Orion/Sharadar `TSG1` alias still needs a causal security-identity join before admission.
- `SUN1` buy `2004-04-16` — the relevant issuer is Sun Microsystems, not Sunoco; pre-buy SEC evidence establishes Nasdaq `SUNW` common stock, but `SUN1` → `SUNW` still needs a causal security-identity join.
- `PHSYB` buy `1998-07-07` — SEC evidence establishes PacifiCare Class B common stock, but the directly retrieved description is retrospective; a pre-buy filing/identity bridge is still required.
- `TELFY` early buys — historical Telefonica/Spanish Telephone Company F-6 evidence for depositary receipts for common stock exists before 1998, but direct causal issuer/alias linkage still needs final confirmation.
- `CBDBY` — historical SEC F-6 evidence indicates depositary receipts for **preferred stock**, making this a likely genuine non-common case; direct historical ticker/CIK linkage still needs final confirmation before classification.

### Count checkpoint

The prior authoritative checkpoint was **38 unresolved executed-buy rows**. Batch 23 resolves four additional rows (`KBL`, two earlier `COCOQ` buys, and `NGH`), leaving **34 unresolved executed-buy rows**.

## Governance

All positive, negative, ambiguous, and unresolved findings are committed to this Orion branch as they are established. Successful executed-buy coverage is only the first economic gate; full candidate/session coverage and a provenance-retaining fail-closed `SEC_SECURITY_TYPE_PIT_ONLY` tape are still required before certification.
