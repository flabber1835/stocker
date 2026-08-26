# Orion SEC security-type manual research log

This log records manual SEC EDGAR work performed because GitHub-hosted runners received HTTP 403 responses from SEC.gov. The acceptance rule is unchanged: evidence must be public strictly before the Orion decision/buy date; current mappings may be used only as retrieval hints; unresolved cases remain unknown/ineligible.

## 2026-08-25 continuation

### Newly resolved

- `POT` buy `2006-12-08` — **verified common**. Potash Corporation of Saskatchewan Inc. original 2004 Form 10-K was filed `2005-03-11`; its later 10-K/A explicitly states that original filing date and repeats the registered security as `Common Shares, No Par Value` on the NYSE. CIK `0000855931`. Evidence is safely pre-buy. Source family: SEC accession `0001130319-05-000170`, corroborated by amendment `0001130319-05-000285`.
- `SQM` buy `2005-06-03` — **verified common-equity ADR**. The Windows retrieval pass found a contemporaneous SQM 6-K filed `2004-05-03` under CIK `0000909037` (accession `0001125282-04-001880`). Later SEC 20-Fs consistently establish that SQM Series B shares have traded on the NYSE in ADS/ADR form since `1993-09-20`, and the ADR represents Series B ordinary equity rather than preferred stock, warrants, or partnership units. This resolves the security-type question for the 2005 Orion buy while preserving the rule that current mappings are retrieval hints only.

### Investigated but not yet admitted

- `NOK` buy `1998-07-07` — SEC archive has a pre-buy SC 13G/A filed `1998-01-08` for Nokia CIK `0000924613`; later 20-Fs establish ADSs under `NOK` and that ADSs were first issued in 1994. I have **not yet admitted** the 1998 buy because the pre-buy filing's exact class/title needs to be extracted directly.
- `SAP` buy `1998-07-07` — later SEC 20-F evidence says SAP ADSs were listed on NYSE effective `1998-08-03`, after the Orion buy date. This is a potential historical-identity/listing anomaly and must not be force-classified from later evidence. It remains unresolved pending evidence of what security the Sharadar `SAP` row represented on `1998-07-07`.

### Count checkpoint

The prior checkpoint was 108 unresolved buy rows after `POT`. `SQM` is now resolved, leaving **107 unresolved buy rows** in the executed-buy gap set. Note that the standalone Windows v3 script reported 109 unresolved because it only skipped the 39 rows present in the consolidated manual file and did not include all later batch files committed separately on the branch. The authoritative count for this research log is therefore based on the branch-documented evidence set, not that script's raw unresolved count.

## Governance

All manual findings, including negative or unresolved findings, are to be recorded on this Orion research branch. A successful security-type classification is not enough by itself for final certification: after executed-buy gaps are worked down, full candidate/session coverage still has to be measured and the final `SEC_SECURITY_TYPE_PIT_ONLY` tape must retain source provenance and fail closed on unknowns.
