# Orion SEC security-type manual research log

This log records manual SEC EDGAR work performed because GitHub-hosted runners received HTTP 403 responses from SEC.gov. The acceptance rule is unchanged: evidence must be public strictly before the Orion decision/buy date; current mappings may be used only as retrieval hints; unresolved cases remain unknown/ineligible.

## 2026-08-25 continuation

### Newly resolved

- `POT` buy `2006-12-08` — **verified common**. Potash Corporation of Saskatchewan Inc. original 2004 Form 10-K was filed `2005-03-11`; its later 10-K/A explicitly states that original filing date and repeats the registered security as `Common Shares, No Par Value` on the NYSE. CIK `0000855931`. Evidence is safely pre-buy. Source family: SEC accession `0001130319-05-000170`, corroborated by amendment `0001130319-05-000285`.
- `SQM` buy `2005-06-03` — **verified common-equity ADR**. The Windows retrieval pass found a contemporaneous SQM 6-K filed `2004-05-03` under CIK `0000909037` (accession `0001125282-04-001880`). Later SEC 20-Fs consistently establish that SQM Series B shares have traded on the NYSE in ADS/ADR form since `1993-09-20`, and the ADR represents Series B ordinary equity rather than preferred stock, warrants, or partnership units. This resolves the security-type question for the 2005 Orion buy while preserving the rule that current mappings are retrieval hints only.
- `BBRC1` buy `2000-05-19` — **verified common**. Burr-Brown Corporation's 1999 Form 10-K, filed `2000-02-14` under CIK `0000715577`, states that the security registered under Section 12(g) is `Common Stock, $0.01 Par Value`. Evidence batch 07 records the exact SEC source and is safely pre-buy.
- `BGO` buy `2003-12-03` — **verified common**. Bema Gold Corporation's 2002 Form 40-F, filed `2003-05-20` under CIK `0000879338`, identifies its authorized capital as common shares without par value. Evidence batch 07 records the exact SEC source and predates the Orion buy.

### Investigated but not yet admitted

- `NOK` buy `1998-07-07` — SEC archive has a pre-buy SC 13G/A filed `1998-01-08` for Nokia CIK `0000924613`; later 20-Fs establish ADSs under `NOK` and that ADSs were first issued in 1994. I have **not yet admitted** the 1998 buy because the pre-buy filing's exact class/title needs to be extracted directly.
- `SAP` buy `1998-07-07` — later SEC 20-F evidence says SAP ADSs were listed on NYSE effective `1998-08-03`, after the Orion buy date. This is a potential historical-identity/listing anomaly and must not be force-classified from later evidence. It remains unresolved pending evidence of what security the Sharadar `SAP` row represented on `1998-07-07`.
- `ARMH1` buy `1999-04-23` — later ARM Holdings 20-F evidence says its IPO occurred `1998-04-17` and its ordinary shares were represented by Nasdaq ADSs under `ARMHY`. That later retrospective evidence is not being used as the sole causal admission; a contemporaneous 1998 registration/F-6/F-1 source is still being sought.
- `ADVP` buy `2000-11-09` — a post-buy `2000-12-14` Form 8-A/A identifies AdvancePCS Class A Common Stock and references the original `1996-09-30` 8-A. Because the directly inspected form is post-buy, this row remains unresolved pending a pre-buy filing itself (the 2000 10-K/10-Q/8-K chain is being searched).
- `AV1` buy `2003-09-29` — Avaya's 2003 10-K explicitly identifies common stock on NYSE, but the filing covers fiscal year ended `2003-09-30` and is after the buy. Earlier 2003 10-Q or 2002 10-K evidence is still required.

### Count checkpoint

The prior authoritative checkpoint was **107 unresolved buy rows** after `SQM`. `BBRC1` and `BGO` are now resolved, leaving **105 unresolved executed-buy rows**. The standalone Windows script's raw unresolved count remains non-authoritative because it skipped only the consolidated manual file and not every later batch file committed separately.

## Governance

All manual findings, including negative or unresolved findings, are to be recorded on this Orion research branch as they are established. A successful security-type classification is not enough by itself for final certification: after executed-buy gaps are worked down, full candidate/session coverage still has to be measured and the final `SEC_SECURITY_TYPE_PIT_ONLY` tape must retain source provenance and fail closed on unknowns.
