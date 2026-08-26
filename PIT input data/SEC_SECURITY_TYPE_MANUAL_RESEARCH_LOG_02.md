# Orion SEC security-type manual research log — continuation 02

Acceptance rule remains unchanged: only evidence public strictly before the Orion decision/buy date may classify the security. Current mappings may be used for retrieval only. Unknown remains ineligible.

## Newly resolved

- `STEC1` buy `2009-06-30` — **verified common**. STEC Inc. 2008 Form 10-K, filed `2009-03-12`, states that its common stock traded on Nasdaq under `STEC`. Pre-buy Form 4 evidence independently identifies issuer CIK `0001102741`, ticker `STEC`, and non-derivative `Common Stock`. Recorded in `SEC_SECURITY_TYPE_MANUAL_EDGAR_EVIDENCE_BATCH_2026-08-25_04.csv`.
- `JRCCQ` buy `2008-03-11` — **verified common**. SEC Form 3 filed `2007-12-05` identifies James River Coal Co `[JRCC]` and the non-derivative security title `Common Stock, $.01 par value per share`. Recorded in batch 04.

## Investigated but not yet admitted

- `SUN1` buy `2004-04-16` — Sun Microsystems' 2003 Form 10-K contains strong pre-buy evidence: `Our common stock trades on The Nasdaq National Market under the symbol SUNW.` The security-type fact is causal, but the final Orion alias `SUN1 -> SUNW` join still needs to be tied through the causal issuer/listing identity reconstruction before this row is counted resolved.
- `VOD` buy `1998-07-07` — later SEC materials establish an ADS program dating to 1988, but the filings located so far that explicitly describe the ADS/common-share relationship were filed after the Orion buy. Not admitted yet.
- `NOK` buy `1998-07-07` — later 20-Fs explicitly state that NOK ADSs were first issued in July 1994 and represent Nokia shares, but the exact pre-buy SEC filing carrying the security-title evidence has not yet been extracted. Not admitted.
- `SQM` buy `2005-06-03` — the SEC archive confirms a 2004 Form 20-F filed `2004-06-30`; later filings establish Series B ADR continuity back to 1993. The contemporaneous 2004 filing's exact security-title text is still required before admission.
- `SAP` buy `1998-07-07` — still treated as a potential listing/identity anomaly because later SEC evidence says SAP ADSs began NYSE trading on `1998-08-03`, after the Orion buy.

## Count checkpoint

Previous checkpoint: **108 unresolved executed-buy rows**.

Two rows were resolved in this continuation (`STEC1`, `JRCCQ`), leaving **106 unresolved executed-buy rows**.

## Governance note

The manual search is documenting both successful and unsuccessful/rejected evidence. No row is promoted merely because a later filing makes the historical classification look obvious. Alias rows must also pass the causal issuer/listing identity join before certification.
